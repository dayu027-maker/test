# it_ticket_system.py
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import os
import shutil
from pathlib import Path

# ================== 配置 ==================
DB_PATH = "database.db"
UPLOADS_DIR = Path("uploads")
IMAGES_DIR = UPLOADS_DIR / "images"
ATTACHMENTS_DIR = UPLOADS_DIR / "attachments"

# 确保目录存在
UPLOADS_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)
ATTACHMENTS_DIR.mkdir(exist_ok=True)

# 工单类型
TICKET_TYPES = ["硬件故障", "软件问题", "网络问题", "账号权限", "采购申请", "其他"]

# ================== 数据库初始化 ==================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 用户表
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            name TEXT NOT NULL
        )
    """)

    # 工单主表
    c.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            type TEXT NOT NULL,
            description TEXT NOT NULL,
            department TEXT,
            submitter_id INTEGER NOT NULL,
            due_days INTEGER DEFAULT 7,
            status TEXT DEFAULT 'submitted', -- draft, submitted, completed, rejected
            handle_status TEXT, -- NULL, processing, completed
            handler_id INTEGER,
            resolution TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (submitter_id) REFERENCES users(id),
            FOREIGN KEY (handler_id) REFERENCES users(id)
        )
    """)

    # 审批流程表
    c.execute("""
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            level INTEGER NOT NULL,
            approver_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending', -- pending, approved, rejected
            comment TEXT,
            approved_at TEXT,
            FOREIGN KEY (ticket_id) REFERENCES tickets(id),
            FOREIGN KEY (approver_id) REFERENCES users(id),
            UNIQUE(ticket_id, level)
        )
    """)

    # 抄送人表
    c.execute("""
        CREATE TABLE IF NOT EXISTS cc_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # 文件记录表（图片 & 附件）
    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            file_type TEXT NOT NULL, -- 'image' or 'attachment'
            original_name TEXT NOT NULL,
            saved_path TEXT NOT NULL,
            size INTEGER NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets(id)
        )
    """)

    # 评论表
    c.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # 插入默认用户（仅当 users 表为空时）
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        default_users = [
            ("user1", "123456", "employee", "张三"),
            ("user2", "123456", "employee", "李四"),
            ("manager1", "mgr123", "manager", "王主管"),
            ("manager2", "mgr123", "manager", "刘经理"),
            ("cto", "cto123", "manager", "陈CTO"),
            ("admin", "admin123", "admin", "管理员"),
        ]
        c.executemany(
            "INSERT INTO users (username, password, role, name) VALUES (?, ?, ?, ?)",
            default_users
        )

    conn.commit()
    conn.close()

# ================== 工具函数 ==================
def get_user_by_username(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, password, role, name FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    return row  # (id, username, password, role, name)

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT id, username, role, name FROM users", conn)
    conn.close()
    return df

def get_user_by_id(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, role, name FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return {"id": row[0], "username": row[1], "role": row[2], "name": row[3]} if row else None

def save_file_to_disk(uploaded_file, folder: Path):
    """保存文件并返回相对路径"""
    safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_file.name.replace(' ', '_')}"
    save_path = folder / safe_name
    with open(save_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return str(save_path.relative_to("."))

def get_files_by_ticket(ticket_id, file_type=None):
    conn = sqlite3.connect(DB_PATH)
    if file_type:
        df = pd.read_sql_query(
            "SELECT * FROM files WHERE ticket_id = ? AND file_type = ? ORDER BY uploaded_at",
            conn, params=(ticket_id, file_type)
        )
    else:
        df = pd.read_sql_query(
            "SELECT * FROM files WHERE ticket_id = ? ORDER BY uploaded_at",
            conn, params=(ticket_id,)
        )
    conn.close()
    return df

def create_ticket_in_db(title, ticket_type, description, dept, submitter_id, due_days, status="submitted"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        INSERT INTO tickets (
            title, type, description, department, submitter_id, due_days, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, ticket_type, description, dept, submitter_id, due_days, status, now, now))
    ticket_id = c.lastrowid
    conn.commit()
    conn.close()
    return ticket_id

def add_approval_to_db(ticket_id, level, approver_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO approvals (ticket_id, level, approver_id) VALUES (?, ?, ?)
    """, (ticket_id, level, approver_id))
    conn.commit()
    conn.close()

def add_cc_to_db(ticket_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO cc_users (ticket_id, user_id) VALUES (?, ?)", (ticket_id, user_id))
    conn.commit()
    conn.close()

def add_file_to_db(ticket_id, file_type, original_name, saved_path, size):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        INSERT INTO files (ticket_id, file_type, original_name, saved_path, size, uploaded_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (ticket_id, file_type, original_name, saved_path, size, now))
    conn.commit()
    conn.close()

def update_ticket_status(ticket_id, status, handle_status=None, handler_id=None, resolution=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    fields = ["status = ?", "updated_at = ?"]
    params = [status, datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    if handle_status is not None:
        fields.append("handle_status = ?")
        params.append(handle_status)
    if handler_id is not None:
        fields.append("handler_id = ?")
        params.append(handler_id)
    if resolution is not None:
        fields.append("resolution = ?")
        params.append(resolution)
    params.append(ticket_id)
    sql = f"UPDATE tickets SET {', '.join(fields)} WHERE id = ?"
    c.execute(sql, params)
    conn.commit()
    conn.close()

def update_approval_status(approval_id, status, comment):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        UPDATE approvals SET status = ?, comment = ?, approved_at = ? WHERE id = ?
    """, (status, comment, now, approval_id))
    conn.commit()
    conn.close()

def get_tickets_by_submitter(submitter_id):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT * FROM tickets WHERE submitter_id = ? ORDER BY id DESC
    """, conn, params=(submitter_id,))
    conn.close()
    return df

def get_approvals_by_ticket(ticket_id):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT a.*, u.name as approver_name 
        FROM approvals a 
        JOIN users u ON a.approver_id = u.id
        WHERE a.ticket_id = ? 
        ORDER BY a.level
    """, conn, params=(ticket_id,))
    conn.close()
    return df

def get_pending_approvals_for_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT t.*, a.id as approval_id, a.level, a.status as approval_status, u.name as submitter_name
        FROM approvals a
        JOIN tickets t ON a.ticket_id = t.id
        JOIN users u ON t.submitter_id = u.id
        WHERE a.approver_id = ? AND a.status = 'pending'
        ORDER BY t.id DESC
    """, conn, params=(user_id,))
    conn.close()
    return df

def get_approved_tickets_for_handling():
    # 所有审批通过且未处理的工单
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT t.*, u.name as submitter_name
        FROM tickets t
        JOIN users u ON t.submitter_id = u.id
        WHERE t.status = 'submitted'
          AND t.handle_status IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM approvals a WHERE a.ticket_id = t.id AND a.status != 'approved'
          )
    """, conn)
    conn.close()
    return df

def get_all_tickets_for_admin():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT t.*, u.name as submitter_name, h.name as handler_name
        FROM tickets t
        LEFT JOIN users u ON t.submitter_id = u.id
        LEFT JOIN users h ON t.handler_id = h.id
        ORDER BY t.id DESC
    """, conn)
    conn.close()
    return df

def get_cc_users_by_ticket(ticket_id):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT u.name FROM cc_users c
        JOIN users u ON c.user_id = u.id
        WHERE c.ticket_id = ?
    """, conn, params=(ticket_id,))
    conn.close()
    return df['name'].tolist()

def add_comment_to_db(ticket_id, user_id, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO comments (ticket_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
              (ticket_id, user_id, content, now))
    conn.commit()
    conn.close()

def get_comments_by_ticket(ticket_id):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT c.*, u.name as user_name, u.role as user_role
        FROM comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.ticket_id = ?
        ORDER BY c.created_at
    """, conn, params=(ticket_id,))
    conn.close()
    return df

def get_tickets_cc_to_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT t.*, u.name as submitter_name
        FROM tickets t
        JOIN cc_users c ON t.id = c.ticket_id
        JOIN users u ON t.submitter_id = u.id
        WHERE c.user_id = ?
        ORDER BY t.id DESC
    """, conn, params=(user_id,))
    conn.close()
    return df

def get_processed_approvals_for_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT t.*, a.id as approval_id, a.level, a.status as approval_status, 
               a.comment as approval_comment, a.approved_at, u.name as submitter_name
        FROM approvals a
        JOIN tickets t ON a.ticket_id = t.id
        JOIN users u ON t.submitter_id = u.id
        WHERE a.approver_id = ? AND a.status != 'pending'
        ORDER BY a.approved_at DESC
    """, conn, params=(user_id,))
    conn.close()
    return df

def get_last_approver_id(ticket_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT approver_id FROM approvals WHERE ticket_id = ? ORDER BY level DESC LIMIT 1", (ticket_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# ================== 辅助函数 ==================
def get_ticket_status_from_row(ticket_row):
    status = ticket_row['status']
    if status == 'draft':
        return '草稿'
    elif status == 'rejected':
        return '已拒绝'
    elif ticket_row['handle_status'] == 'completed':
        return '已完成'
    elif ticket_row['handle_status'] == 'processing':
        return '处理中'
    else:
        # 检查审批状态
        approvals = get_approvals_by_ticket(ticket_row['id'])
        if approvals.empty:
            return '待处理'
        any_rejected = (approvals['status'] == 'rejected').any()
        all_approved = (approvals['status'] == 'approved').all()
        if any_rejected:
            return '已拒绝'
        elif all_approved:
            return '待处理'
        else:
            pending_levels = approvals[approvals['status'] == 'pending']['level'].min()
            return f"审批中 (第{pending_levels}级)"

# ================== 页面逻辑 ==================
def show_comments_section(ticket_id):
    st.markdown("---")
    st.write("**💬 评论**")
    
    # Display existing comments
    comments = get_comments_by_ticket(ticket_id)
    if not comments.empty:
        for _, c in comments.iterrows():
            st.markdown(f"""
            <div style='background:#f0f2f6; padding:10px; border-radius:8px; margin-bottom:8px;'>
                <div style='display:flex; justify-content:space-between; margin-bottom:4px;'>
                    <b>{c['user_name']}</b>
                    <small style='color:#666;'>{c['created_at']}</small>
                </div>
                {c['content']}
            </div>
            """, unsafe_allow_html=True)
    
    # Add new comment
    with st.form(key=f"comment_form_{ticket_id}"):
        new_comment = st.text_area("发表评论", height=80, key=f"comment_text_{ticket_id}")
        if st.form_submit_button("发送"):
            if new_comment.strip():
                add_comment_to_db(ticket_id, st.session_state.current_user_id, new_comment)
                st.success("评论已发送")
                st.rerun()
            else:
                st.warning("评论内容不能为空")

def login_page():
    st.title("🎫 IT工单管理系统")
    st.subheader("用户登录")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        username = st.text_input("用户名")
        password = st.text_input("密码", type="password")

        if st.button("登录", use_container_width=True):
            user = get_user_by_username(username)
            if user and user[2] == password:
                st.session_state.current_user_id = user[0]
                st.session_state.current_username = user[1]
                st.session_state.user_role = user[3]
                st.session_state.user_name = user[4]
                st.success(f"欢迎, {user[4]}!")
                st.rerun()
            else:
                st.error("用户名或密码错误")

        st.divider()
        st.info("""
        **测试账号:**
        - 员工: user1 / 123456
        - 主管: manager1 / mgr123
        - 经理: manager2 / mgr123
        - CTO: cto / cto123
        - 管理员: admin / admin123
        """)

def reset_temp_data():
    keys_to_clear = ['temp_approvers', 'temp_cc_users']
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]

def create_ticket():
    st.subheader("📝 创建新工单")

    # 申请人信息
    st.write("**申请人**")
    col1, col2 = st.columns(2)
    with col1:
        submitter_name = st.text_input("申请人", value=st.session_state.user_name, disabled=True)
    with col2:
        submitter_dept = st.text_input("申请部门", placeholder="请输入部门")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        title = st.text_input("签呈标题*", placeholder="申请事项的标题")
    with col2:
        ticket_type = st.selectbox("工单类型*", TICKET_TYPES)

    description = st.text_area("签呈内容*", placeholder="对于申请事项的详细描述", height=150)

    st.divider()

    # 审批人
    if 'temp_approvers' not in st.session_state:
        st.session_state.temp_approvers = []

    all_users_df = get_all_users()
    managers_df = all_users_df[all_users_df['role'].isin(['manager', 'admin'])]

    st.write("**流程**")
    if st.session_state.temp_approvers:
        for idx, approver in enumerate(st.session_state.temp_approvers):
            col1, col2, col3 = st.columns([1, 4, 1])
            with col1:
                st.markdown(f"<div style='width:50px; height:50px; border-radius:50%; background:#4CAF50; display:flex; align-items:center; justify-content:center; color:white; font-weight:bold;'>{approver['name'][0]}</div>", unsafe_allow_html=True)
            with col2:
                st.markdown(f"<div><b>{approver['name']}</b><br/>审批人 - 第{idx+1}级</div>", unsafe_allow_html=True)
            with col3:
                if st.button("✖ 移除", key=f"remove_approver_{idx}"):
                    st.session_state.temp_approvers.pop(idx)
                    st.rerun()
    else:
        st.info("请添加至少一个审批人")

    with st.expander("➕ 添加审批人", expanded=len(st.session_state.temp_approvers) == 0):
        search = st.text_input("🔍 搜索审批人", key="approver_search")
        filtered = managers_df[
            managers_df['name'].str.contains(search, case=False, na=False) |
            managers_df['username'].str.contains(search, case=False, na=False)
        ] if search else managers_df

        for _, row in filtered.iterrows():
            col_a, col_b = st.columns([4, 1])
            with col_a:
                st.markdown(f"<div style='padding:12px; background:#f5f5f5; border-radius:8px; margin-bottom:8px;'><b>{row['name']}</b><br/>用户名: {row['username']} | 角色: {row['role']}</div>", unsafe_allow_html=True)
            with col_b:
                if st.button("➕ 添加", key=f"add_{row['id']}", use_container_width=True):
                    if not any(a['id'] == row['id'] for a in st.session_state.temp_approvers):
                        st.session_state.temp_approvers.append({"id": row['id'], "name": row['name']})
                        st.rerun()

    st.divider()

    # 抄送人
    if 'temp_cc_users' not in st.session_state:
        st.session_state.temp_cc_users = []

    st.write("**抄送人**")
    if st.session_state.temp_cc_users:
        cols = st.columns(min(len(st.session_state.temp_cc_users), 4))
        for idx, cc in enumerate(st.session_state.temp_cc_users):
            with cols[idx % 4]:
                st.markdown(f"<div style='text-align:center;'><div style='width:50px; height:50px; border-radius:50%; background:#2196F3; display:flex; align-items:center; justify-content:center; color:white; font-weight:bold; margin:0 auto 8px;'>{cc['name'][0]}</div><div>{cc['name']}</div></div>", unsafe_allow_html=True)
                if st.button("移除", key=f"rm_cc_{idx}", use_container_width=True):
                    st.session_state.temp_cc_users.pop(idx)
                    st.rerun()

    with st.expander("➕ 添加抄送人"):
        search_cc = st.text_input("🔍 搜索抄送人", key="cc_search")
        filtered_cc = all_users_df[
            all_users_df['name'].str.contains(search_cc, case=False, na=False) |
            all_users_df['username'].str.contains(search_cc, case=False, na=False)
        ] if search_cc else all_users_df

        for _, row in filtered_cc.iterrows():
            col_a, col_b = st.columns([4, 1])
            with col_a:
                st.markdown(f"<div style='padding:12px; background:#f5f5f5; border-radius:8px; margin-bottom:8px;'><b>{row['name']}</b><br/>用户名: {row['username']}</div>", unsafe_allow_html=True)
            with col_b:
                if st.button("➕ 添加", key=f"add_cc_{row['id']}", use_container_width=True):
                    if not any(c['id'] == row['id'] for c in st.session_state.temp_cc_users):
                        st.session_state.temp_cc_users.append({"id": row['id'], "name": row['name']})
                        st.rerun()

    st.divider()

    # 图片上传
    st.write("**图片**")
    uploaded_images = st.file_uploader(
        "添加图片", type=['png', 'jpg', 'jpeg'],
        accept_multiple_files=True, key="image_uploader", label_visibility="collapsed"
    )
    if uploaded_images:
        st.caption(f"✅ 已选择 {len(uploaded_images)} 张图片")
        cols = st.columns(min(len(uploaded_images), 4))
        for idx, img in enumerate(uploaded_images):
            with cols[idx % 4]:
                st.image(img, caption=img.name)

    st.divider()

    # 附件上传
    st.write("**附件**")
    uploaded_files = st.file_uploader(
        "添加附件", accept_multiple_files=True,
        key="file_uploader", label_visibility="collapsed"
    )
    if uploaded_files:
        st.caption(f"✅ 已选择 {len(uploaded_files)} 个附件")
        for f in uploaded_files:
            st.caption(f"📎 {f.name} ({f.size} bytes)")

    st.divider()

    col1, col2 = st.columns([3, 1])
    with col1:
        st.write("**发送到期天数**")
    with col2:
        send_days = st.number_input("天数", min_value=1, max_value=365, value=7, label_visibility="collapsed")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 保存草稿", use_container_width=True):
            if title and description:
                ticket_id = create_ticket_in_db(title, ticket_type, description, submitter_dept,
                                                st.session_state.current_user_id, send_days, "draft")
                # 保存文件
                if uploaded_images:
                    for img in uploaded_images:
                        path = save_file_to_disk(img, IMAGES_DIR)
                        add_file_to_db(ticket_id, "image", img.name, path, img.size)
                if uploaded_files:
                    for f in uploaded_files:
                        path = save_file_to_disk(f, ATTACHMENTS_DIR)
                        add_file_to_db(ticket_id, "attachment", f.name, path, f.size)
                st.success(f"✅ 工单 #{ticket_id} 已保存为草稿")
                reset_temp_data()
                st.rerun()
            else:
                st.error("请填写标题和内容")

    with col2:
        if st.button("📤 提交", use_container_width=True, type="primary"):
            if title and description and st.session_state.temp_approvers:
                ticket_id = create_ticket_in_db(title, ticket_type, description, submitter_dept,
                                                st.session_state.current_user_id, send_days, "submitted")
                # 添加审批人
                for idx, approver in enumerate(st.session_state.temp_approvers):
                    add_approval_to_db(ticket_id, idx + 1, approver['id'])
                # 添加抄送人
                for cc in st.session_state.temp_cc_users:
                    add_cc_to_db(ticket_id, cc['id'])
                # 保存文件
                if uploaded_images:
                    for img in uploaded_images:
                        path = save_file_to_disk(img, IMAGES_DIR)
                        add_file_to_db(ticket_id, "image", img.name, path, img.size)
                if uploaded_files:
                    for f in uploaded_files:
                        path = save_file_to_disk(f, ATTACHMENTS_DIR)
                        add_file_to_db(ticket_id, "attachment", f.name, path, f.size)
                st.success(f"✅ 工单 #{ticket_id} 提交成功！")
                reset_temp_data()
                st.rerun()
            else:
                st.error("请填写所有必填项并至少添加一个审批人")

def view_tickets():
    st.subheader("📋 我的工单")
    df = get_tickets_by_submitter(st.session_state.current_user_id)
    if df.empty:
        st.info("暂无工单记录")
        return

    for _, row in df.iterrows():
        status = get_ticket_status_from_row(row)
        color_map = {'草稿': '#9E9E9E', '已拒绝': '#F44336', '已完成': '#4CAF50', '处理中': '#2196F3', '待处理': '#FF9800'}
        color = color_map.get(status, '#FF9800') if '审批中' not in status else '#FF9800'

        with st.expander(f"工单 #{row['id']} - {row['title']}", expanded=False):
            st.markdown(f"<div style='background:{color}; color:white; padding:8px 16px; border-radius:4px; margin-bottom:16px; font-weight:500;'>{status}</div>", unsafe_allow_html=True)

            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**类型:** {row['type']}")
                st.write(f"**部门:** {row['department']}")
                st.write(f"**创建时间:** {row['created_at']}")
                st.write(f"**问题描述:**\n{row['description']}")

                # 显示图片
                img_files = get_files_by_ticket(row['id'], 'image')
                if not img_files.empty:
                    st.write(f"**📷 图片 ({len(img_files)} 张):**")
                    cols = st.columns(min(4, len(img_files)))
                    for idx, (_, img_row) in enumerate(img_files.iterrows()):
                        with cols[idx % 4]:
                            st.image(img_row['saved_path'], caption=img_row['original_name'])

                # 显示附件
                att_files = get_files_by_ticket(row['id'], 'attachment')
                if not att_files.empty:
                    st.write(f"**📎 附件 ({len(att_files)} 个):**")
                    for _, att_row in att_files.iterrows():
                        with open(att_row['saved_path'], "rb") as f:
                            st.download_button(
                                label=f"📥 {att_row['original_name']}",
                                data=f,
                                file_name=att_row['original_name'],
                                mime="application/octet-stream",
                                key=f"dl_{att_row['id']}"
                            )

                # 抄送人
                cc_list = get_cc_users_by_ticket(row['id'])
                if cc_list:
                    st.write(f"**抄送:** {', '.join(cc_list)}")

            with col2:
                st.metric("到期天数", f"{row['due_days']}天")

            # 审批流程
            if row['status'] != 'draft':
                approvals = get_approvals_by_ticket(row['id'])
                if not approvals.empty:
                    st.divider()
                    st.write("**审批流程:**")
                    for _, appr in approvals.iterrows():
                        icon_map = {'pending': '⏳ 待审批', 'approved': '✅ 已批准', 'rejected': '❌ 已拒绝'}
                        bg_map = {'pending': '#FFF3E0', 'approved': '#E8F5E9', 'rejected': '#FFEBEE'}
                        st.markdown(f"""
                        <div style='background:{bg_map[appr['status']]}; padding:12px; border-radius:8px; margin-bottom:8px;'>
                            <b>第{appr['level']}级 - {appr['approver_name']}</b><br/>
                            {icon_map[appr['status']]}
                        </div>
                        """, unsafe_allow_html=True)
                        if pd.notna(appr['comment']):
                            st.caption(f"💬 意见: {appr['comment']}")
                        if pd.notna(appr['approved_at']):
                            st.caption(f"🕐 时间: {appr['approved_at']}")

            # 解决方案
            if pd.notna(row['resolution']):
                st.divider()
                st.success(f"**✅ 解决方案:** {row['resolution']}")

            show_comments_section(row['id'])

def view_cc_tickets():
    st.subheader("📥 抄送我的")
    df = get_tickets_cc_to_user(st.session_state.current_user_id)
    if df.empty:
        st.info("暂无抄送工单")
        return

    for _, row in df.iterrows():
        status = get_ticket_status_from_row(row)
        color_map = {'草稿': '#9E9E9E', '已拒绝': '#F44336', '已完成': '#4CAF50', '处理中': '#2196F3', '待处理': '#FF9800'}
        color = color_map.get(status, '#FF9800') if '审批中' not in status else '#FF9800'

        with st.expander(f"工单 #{row['id']} - {row['title']}", expanded=False):
            st.markdown(f"<div style='background:{color}; color:white; padding:8px 16px; border-radius:4px; margin-bottom:16px; font-weight:500;'>{status}</div>", unsafe_allow_html=True)
            st.write(f"**提交人:** {row['submitter_name']}")

            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**类型:** {row['type']}")
                st.write(f"**部门:** {row['department']}")
                st.write(f"**创建时间:** {row['created_at']}")
                st.write(f"**问题描述:**\n{row['description']}")

                # 显示图片
                img_files = get_files_by_ticket(row['id'], 'image')
                if not img_files.empty:
                    st.write(f"**📷 图片 ({len(img_files)} 张):**")
                    cols = st.columns(min(4, len(img_files)))
                    for idx, (_, img_row) in enumerate(img_files.iterrows()):
                        with cols[idx % 4]:
                            st.image(img_row['saved_path'], caption=img_row['original_name'])

                # 显示附件
                att_files = get_files_by_ticket(row['id'], 'attachment')
                if not att_files.empty:
                    st.write(f"**📎 附件 ({len(att_files)} 个):**")
                    for _, att_row in att_files.iterrows():
                        with open(att_row['saved_path'], "rb") as f:
                            st.download_button(
                                label=f"📥 {att_row['original_name']}",
                                data=f,
                                file_name=att_row['original_name'],
                                mime="application/octet-stream",
                                key=f"dl_cc_{att_row['id']}"
                            )

            with col2:
                st.metric("到期天数", f"{row['due_days']}天")

            # 审批流程
            if row['status'] != 'draft':
                approvals = get_approvals_by_ticket(row['id'])
                if not approvals.empty:
                    st.divider()
                    st.write("**审批流程:**")
                    for _, appr in approvals.iterrows():
                        icon_map = {'pending': '⏳ 待审批', 'approved': '✅ 已批准', 'rejected': '❌ 已拒绝'}
                        bg_map = {'pending': '#FFF3E0', 'approved': '#E8F5E9', 'rejected': '#FFEBEE'}
                        st.markdown(f"""
                        <div style='background:{bg_map[appr['status']]}; padding:12px; border-radius:8px; margin-bottom:8px;'>
                            <b>第{appr['level']}级 - {appr['approver_name']}</b><br/>
                            {icon_map[appr['status']]}
                        </div>
                        """, unsafe_allow_html=True)
                        if pd.notna(appr['comment']):
                            st.caption(f"💬 意见: {appr['comment']}")
                        if pd.notna(appr['approved_at']):
                            st.caption(f"🕐 时间: {appr['approved_at']}")

            # 解决方案
            if pd.notna(row['resolution']):
                st.divider()
                st.success(f"**✅ 解决方案:** {row['resolution']}")

            show_comments_section(row['id'])

def my_approvals():
    st.subheader("✅ 审批管理")
    tab1, tab2 = st.tabs(["待我审批", "我已审批"])
    
    with tab1:
        df = get_pending_approvals_for_user(st.session_state.current_user_id)
        if df.empty:
            st.info("🎉 暂无待审批工单")
        else:
            for _, row in df.iterrows():
                with st.expander(f"🔔 工单 #{row['id']} - {row['title']}", expanded=True):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        st.markdown("<div style='background:#E3F2FD; padding:12px; border-radius:8px; margin-bottom:16px;'><b>等待您的审批</b></div>", unsafe_allow_html=True)
                        st.write(f"**提交人:** {row['submitter_name']}")
                        st.write(f"**部门:** {row['department']}")
                        st.write(f"**类型:** {row['type']}")
                        st.write(f"**内容:**\n{row['description']}")

                        img_files = get_files_by_ticket(row['id'], 'image')
                        if not img_files.empty:
                            st.write(f"**📷 图片 ({len(img_files)} 张)**")
                            cols = st.columns(min(4, len(img_files)))
                            for idx, (_, img_row) in enumerate(img_files.iterrows()):
                                with cols[idx % 4]:
                                    st.image(img_row['saved_path'], caption=img_row['original_name'])

                        att_files = get_files_by_ticket(row['id'], 'attachment')
                        if not att_files.empty:
                            st.write(f"**📎 附件 ({len(att_files)} 个)**")
                            for _, att_row in att_files.iterrows():
                                with open(att_row['saved_path'], "rb") as f:
                                    st.download_button(
                                        label=f"📥 {att_row['original_name']}",
                                        data=f,
                                        file_name=att_row['original_name'],
                                        mime="application/octet-stream",
                                        key=f"dl_approve_{att_row['id']}"
                                    )

                    with col2:
                        comment = st.text_area("审批意见", key=f"comm_{row['approval_id']}")
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("✅ 同意", key=f"ok_{row['approval_id']}", type="primary"):
                                update_approval_status(row['approval_id'], 'approved', comment or "同意")
                                st.success("✅ 审批通过")
                                st.rerun()
                        with col_b:
                            if st.button("❌ 拒绝", key=f"no_{row['approval_id']}"):
                                if comment:
                                    update_approval_status(row['approval_id'], 'rejected', comment)
                                    st.warning("❌ 已拒绝")
                                    st.rerun()
                                else:
                                    st.error("拒绝时必须填写意见")
                    
                    show_comments_section(row['id'])

    with tab2:
        df_processed = get_processed_approvals_for_user(st.session_state.current_user_id)
        if df_processed.empty:
            st.info("暂无已审批记录")
        else:
            for _, row in df_processed.iterrows():
                with st.expander(f"工单 #{row['id']} - {row['title']} [{row['approval_status']}]", expanded=False):
                    st.write(f"**提交人:** {row['submitter_name']}")
                    st.write(f"**我的审批:** {row['approval_status']}")
                    st.write(f"**我的意见:** {row['approval_comment']}")
                    st.write(f"**审批时间:** {row['approved_at']}")
                    st.divider()
                    
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**类型:** {row['type']}")
                        st.write(f"**部门:** {row['department']}")
                        st.write(f"**问题描述:**\n{row['description']}")
                        
                        img_files = get_files_by_ticket(row['id'], 'image')
                        if not img_files.empty:
                            st.write(f"**📷 图片 ({len(img_files)} 张):**")
                            cols = st.columns(min(4, len(img_files)))
                            for idx, (_, img_row) in enumerate(img_files.iterrows()):
                                with cols[idx % 4]:
                                    st.image(img_row['saved_path'], caption=img_row['original_name'])

                        att_files = get_files_by_ticket(row['id'], 'attachment')
                        if not att_files.empty:
                            st.write(f"**📎 附件 ({len(att_files)} 个):**")
                            for _, att_row in att_files.iterrows():
                                with open(att_row['saved_path'], "rb") as f:
                                    st.download_button(
                                        label=f"📥 {att_row['original_name']}",
                                        data=f,
                                        file_name=att_row['original_name'],
                                        mime="application/octet-stream",
                                        key=f"dl_appr_hist_{att_row['id']}"
                                    )
                    
                    show_comments_section(row['id'])

def handle_tickets():
    st.subheader("🔧 处理工单")
    df = get_approved_tickets_for_handling()
    
    # Filter for last approver
    filtered_rows = []
    if not df.empty:
        for _, row in df.iterrows():
            last_approver_id = get_last_approver_id(row['id'])
            if last_approver_id == st.session_state.current_user_id:
                filtered_rows.append(row)
    
    if not filtered_rows:
        st.info("暂无待处理工单 (需为最后一位审批人)")
        return

    for row in filtered_rows:
        status = get_ticket_status_from_row(row)
        with st.expander(f"工单 #{row['id']} - {row['title']} [{status}]"):
            col1, col2 = st.columns([2, 1])
            with col1:
                st.write(f"**提交人:** {row['submitter_name']}")
                st.write(f"**类型:** {row['type']}")
                st.write(f"**问题描述:**\n{row['description']}")

                img_files = get_files_by_ticket(row['id'], 'image')
                if not img_files.empty:
                    st.write(f"**📷 图片 ({len(img_files)} 张)**")
                    cols = st.columns(min(4, len(img_files)))
                    for idx, (_, img_row) in enumerate(img_files.iterrows()):
                        with cols[idx % 4]:
                            st.image(img_row['saved_path'], caption=img_row['original_name'])

                att_files = get_files_by_ticket(row['id'], 'attachment')
                if not att_files.empty:
                    st.write(f"**📎 附件 ({len(att_files)} 个)**")
                    for _, att_row in att_files.iterrows():
                        with open(att_row['saved_path'], "rb") as f:
                            st.download_button(
                                label=f"📥 {att_row['original_name']}",
                                data=f,
                                file_name=att_row['original_name'],
                                mime="application/octet-stream",
                                key=f"dl_handle_{att_row['id']}"
                            )

            with col2:
                # 无论是否点击开始处理，都直接显示完成工单的选项
                # 如果尚未开始处理，自动标记为处理中
                if pd.isna(row['handle_status']):
                     st.info("待处理")
                else:
                     st.info(f"**处理中**\n{st.session_state.user_name}")
                
                resolution = st.text_area("解决方案", key=f"res_{row['id']}", placeholder="选填，可直接点击完成")
                if st.button("✅ 完成工单", key=f"finish_{row['id']}", type="primary"):
                    # 只要点击完成，就更新状态。解决方案可以是空的。
                    res_text = resolution if resolution else "已完成"
                    update_ticket_status(row['id'], "submitted", handle_status="completed", resolution=res_text, handler_id=st.session_state.current_user_id)
                    st.success("工单已完成")
                    st.rerun()
            
            show_comments_section(row['id'])

def admin_dashboard():
    st.subheader("📊 管理仪表板")
    df = get_all_tickets_for_admin()
    if df.empty:
        st.info("暂无工单数据")
        return

    # 统计
    total = len(df)
    drafts = sum(df['status'] == 'draft')
    pending_approval = sum(df.apply(lambda r: '审批中' in get_ticket_status_from_row(r), axis=1))
    processing = sum(df['handle_status'] == 'processing')
    completed = sum(df['handle_status'] == 'completed')

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("总工单", total)
    col2.metric("草稿", drafts)
    col3.metric("审批中", pending_approval)
    col4.metric("处理中", processing)
    col5.metric("已完成", completed)

    st.divider()
    st.dataframe(df[['id', 'title', 'type', 'submitter_name', 'status', 'handle_status', 'created_at']], use_container_width=True)

def main():
    init_db()  # 初始化数据库

    if 'current_user_id' not in st.session_state:
        login_page()
        return

    with st.sidebar:
        st.title("🎫 IT工单系统")
        st.write(f"👤 {st.session_state.user_name}")
        st.write(f"角色: {st.session_state.user_role}")

        st.divider()

        if st.session_state.user_role == "employee":
            menu = st.radio("菜单", ["创建工单", "我的工单", "抄送我的"])
        elif st.session_state.user_role == "manager":
            menu = st.radio("菜单", ["我的审批", "处理工单", "创建工单", "我的工单", "抄送我的"])
        else:  # admin
            menu = st.radio("菜单", ["管理仪表板", "我的审批", "处理工单", "创建工单", "我的工单", "抄送我的"])

        st.divider()
        if st.button("退出登录", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    if menu == "创建工单":
        create_ticket()
    elif menu == "我的工单":
        view_tickets()
    elif menu == "抄送我的":
        view_cc_tickets()
    elif menu == "我的审批":
        my_approvals()
    elif menu == "处理工单":
        handle_tickets()
    elif menu == "管理仪表板":
        admin_dashboard()

if __name__ == "__main__":
    main()