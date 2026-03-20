def highlight_reading_text(self, start_pos, end_pos):
        """高亮正在朗读的文本"""
        try:
            # 清除之前的高亮
            clear_reading_highlight(self)
            
            # 设置新的高亮
            self.text.tag_add("reading_highlight", start_pos, end_pos)
            self.current_highlight_start = start_pos
            self.current_highlight_end = end_pos
            
            # 确保高亮区域可见
            self.text.see(start_pos)
            
        except tk.TclError as e:
            print(f"高亮文本出错: {e}")

def clear_reading_highlight(self):
    """清除朗读高亮"""
    try:
        if self.current_highlight_start and self.current_highlight_end:
            self.text.tag_remove("reading_highlight", self.current_highlight_start, self.current_highlight_end)
        else:
                # 清除所有高亮
            self.text.tag_remove("reading_highlight", "1.0", tk.END)
            
        self.current_highlight_start = None
        self.current_highlight_end = None
            
    except tk.TclError:
        pass


def speak_text(text, voice_id=0, rate=200, volume=1.0, save_to_file=None):
    """播放单条语音文本或保存到文件
    
    Args:
        text: 要播放的文本
        voice_id: 语音ID (默认为0)
        rate: 语速 (默认为200)
        volume: 音量 (0.0-1.0, 默认为1.0)
        save_to_file: 保存语音到文件的路径 (默认为None，不保存)
    
    Returns:
        bool: 操作是否成功
    """
    try:
        # 初始化引擎
        engine = pyttsx3.init()
        
        # 设置语音属性
        engine.setProperty('rate', rate)  # 设置语速
        engine.setProperty('volume', volume)  # 设置音量
        
        # 如果有可用语音且指定了语音ID，则设置
        voices = engine.getProperty('voices')
        if voices and len(voices) > voice_id:
            engine.setProperty('voice', voices[voice_id].id)
        
        if save_to_file:
            try:
                # 保存到文件
                engine.save_to_file(text, save_to_file)
                engine.runAndWait()
                print(f"语音已保存到文件: {save_to_file}")
            except Exception as save_error:
                print(f"保存语音到文件时出错: {save_error}", file=sys.stderr)
                return False
        else:
            # 播放语音
            engine.say(text)
            engine.runAndWait()
        
        # 清理资源
        engine.stop()
        return True
    except Exception as e:
        print(f"语音处理错误: {e}", file=sys.stderr)
        return False

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import re
import json
import time
import threading
try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False
    print("警告: pyttsx3 未安装，语音功能不可用。请运行: pip install pyttsx3")

CONFIG_FILE = "novel_reader_config.json"

class NovelReaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("小说阅读器")
        # self.root.iconbitmap("novel_reader_icon.ico")
        self.text_font_size = 14
        self.bg_color = "white"
        self.fg_color = "black"
        self.chapter_positions = []
        self.all_chapters = []  # 存储所有章节，用于搜索
        self.filtered_chapters = []  # 存储过滤后的章节
        self.current_file = None
        self.scroll_timer = None
        self.recent_paths = {}  # 用于存储最近文件的路径
        self.current_chapter_index = -1  # 跟踪当前章节索引
        
        # 语音阅读相关
        self.tts_engine = None
        self.is_reading = False
        self.reading_thread = None
        self.reading_position = "1.0"
        self.reading_speed = 200  # 语音速度
        self.reading_volume = 0.8  # 语音音量
        self.playback_speed = 1.4  # 播放速度倍率
        self.auto_scroll = True  # 是否自动滚动
        self.current_highlight_start = None  # 当前高亮开始位置
        self.current_highlight_end = None    # 当前高亮结束位置
        
        # 定时停止相关
        self.timer_stop_enabled = False  # 是否启用定时停止
        self.timer_stop_minutes = 20     # 定时停止时间（分钟），默认20分钟
        self.timer_stop_after_id = None  # 定时器ID
        
        self.init_tts()
        self.load_config()
        self.setup_ui()

        if self.config.get("recent_files"):
            self.load_recent_listbox()

    def init_tts(self):
        """初始化语音引擎"""
        if TTS_AVAILABLE:
            try:
                # 使用driverName='sapi5'参数可以在Windows上获得更好的性能
                self.tts_engine = pyttsx3.init(driverName='sapi5')
                self.tts_engine.setProperty('rate', self.reading_speed)
                self.tts_engine.setProperty('volume', self.reading_volume)
                
                # 尝试设置中文语音
                voices = self.tts_engine.getProperty('voices')
                for voice in voices:
                    if 'chinese' in voice.name.lower() or 'mandarin' in voice.name.lower() or 'zh' in voice.id.lower():
                        self.tts_engine.setProperty('voice', voice.id)
                        break
                
                # 添加窗口关闭事件处理，确保释放TTS资源
                self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
                        
            except Exception as e:
                print(f"语音引擎初始化失败: {e}")
                self.tts_engine = None

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
                
                # 兼容旧版本配置格式
                for filepath, data in self.config.get("recent_files", {}).items():
                    if isinstance(data.get("last_position"), str):
                        # 旧格式，保持不变，会在恢复时自动处理
                        continue
            except (json.JSONDecodeError, UnicodeDecodeError):
                # 配置文件损坏，使用默认配置
                self.config = {"recent_files": {}}
        else:
            self.config = {"recent_files": {}}

    def save_config(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
            
    def on_closing(self):
        """窗口关闭时的处理"""
        # 停止语音朗读
        if self.is_reading:
            self.stop_voice_reading()
            
        # 释放TTS引擎资源
        if self.tts_engine:
            try:
                self.tts_engine.stop()
            except:
                pass
            
        # 保存配置
        self.save_config()
        
        # 关闭窗口
        self.root.destroy()

    def setup_ui(self):
        # 上方菜单
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="打开小说", command=self.open_file)
        file_menu.add_command(label="删除当前记录", command=self.delete_current_record)
        menubar.add_cascade(label="文件", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="夜间模式", command=self.toggle_night_mode)
        view_menu.add_command(label="放大字体", command=self.increase_font)
        view_menu.add_command(label="缩小字体", command=self.decrease_font)
        menubar.add_cascade(label="视图", menu=view_menu)

        # 语音菜单
        if TTS_AVAILABLE and self.tts_engine:
            voice_menu = tk.Menu(menubar, tearoff=0)
            voice_menu.add_command(label="开始语音阅读", command=self.start_voice_reading)
            voice_menu.add_command(label="停止语音阅读", command=self.stop_voice_reading)
            voice_menu.add_separator()
            voice_menu.add_command(label="语音设置", command=self.show_voice_settings)
            menubar.add_cascade(label="语音", menu=voice_menu)

        self.root.config(menu=menubar)

        # 左边列表：最近阅读小说
        left_frame = tk.Frame(self.root)
        left_frame.pack(side=tk.LEFT, fill=tk.Y)

        tk.Label(left_frame, text="最近阅读").pack()
        
        # 最近阅读列表框和滚动条
        recent_list_frame = tk.Frame(left_frame)
        recent_list_frame.pack(fill=tk.BOTH, expand=True)
        
        # 添加滚动条
        recent_scrollbar = tk.Scrollbar(recent_list_frame)
        recent_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 创建列表框并关联滚动条
        self.recent_listbox = tk.Listbox(recent_list_frame, width=35, yscrollcommand=recent_scrollbar.set)
        self.recent_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        recent_scrollbar.config(command=self.recent_listbox.yview)
        
        self.recent_listbox.bind("<Double-Button-1>", self.open_recent_file)

        # 章节目录区域
        chapter_frame = tk.Frame(left_frame)
        chapter_frame.pack(fill=tk.BOTH, expand=True)
        
        # 章节搜索功能
        search_frame = tk.Frame(chapter_frame)
        search_frame.pack(fill=tk.X, padx=2, pady=2)
        
        tk.Label(search_frame, text="章节目录").pack(anchor=tk.W)
        
        # 搜索输入框
        search_input_frame = tk.Frame(search_frame)
        search_input_frame.pack(fill=tk.X, pady=(2, 0))
        
        tk.Label(search_input_frame, text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_input_frame, textvariable=self.search_var, width=20)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 2))
        
        # 清除搜索按钮
        self.clear_btn = tk.Button(search_input_frame, text="×", width=2, 
                                  command=self.clear_search)
        self.clear_btn.pack(side=tk.RIGHT)
        
        # 绑定搜索事件
        self.search_var.trace('w', self.on_search_change)
        self.search_entry.bind('<Return>', self.on_search_enter)
        self.search_entry.bind('<Escape>', self.clear_search)
        
        # 搜索结果统计标签
        self.search_info_label = tk.Label(search_frame, text="", fg="gray", font=("Arial", 8))
        self.search_info_label.pack(anchor=tk.W)

        # 目录列表框和滚动条
        chapter_list_frame = tk.Frame(chapter_frame)
        chapter_list_frame.pack(fill=tk.BOTH, expand=True)
        
        # 添加滚动条
        chapter_scrollbar = tk.Scrollbar(chapter_list_frame)
        chapter_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 创建列表框并关联滚动条
        self.chapter_listbox = tk.Listbox(chapter_list_frame, width=35, selectbackground="#4CAF50", 
                                        selectforeground="white", yscrollcommand=chapter_scrollbar.set)
        self.chapter_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        chapter_scrollbar.config(command=self.chapter_listbox.yview)
        
        self.chapter_listbox.bind("<<ListboxSelect>>", self.jump_to_chapter)
        
        # 添加章节列表的右键菜单
        self.chapter_menu = tk.Menu(self.chapter_listbox, tearoff=0)
        self.chapter_menu.add_command(label="跳转到此章节", command=self.jump_to_selected_chapter)
        self.chapter_menu.add_separator()
        self.chapter_menu.add_command(label="复制章节名", command=self.copy_chapter_name)
        self.chapter_listbox.bind("<Button-3>", self.show_chapter_menu)  # 右键菜单
        self.chapter_listbox.bind("<Double-Button-1>", self.jump_to_selected_chapter)  # 双击跳转

        # 右边区域
        right_frame = tk.Frame(self.root)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 语音控制栏（如果语音可用）
        if TTS_AVAILABLE and self.tts_engine:
            voice_frame = tk.Frame(right_frame, height=50)
            voice_frame.pack(fill=tk.X, padx=5, pady=2)
            voice_frame.pack_propagate(False)
            
            # 语音控制按钮
            self.play_btn = tk.Button(voice_frame, text="▶ 播放", command=self.start_voice_reading, 
                                    bg="#4CAF50", fg="white", width=8)
            self.play_btn.pack(side=tk.LEFT, padx=2)
            
            self.stop_btn = tk.Button(voice_frame, text="⏹ 停止", command=self.stop_voice_reading, 
                                    bg="#F44336", fg="white", width=8, state=tk.DISABLED)
            self.stop_btn.pack(side=tk.LEFT, padx=2)
            
            # 语音状态显示
            self.voice_status_label = tk.Label(voice_frame, text="就绪", fg="green")
            self.voice_status_label.pack(side=tk.LEFT, padx=10)
            
            # 语音设置按钮
            self.settings_btn = tk.Button(voice_frame, text="⚙ 设置", command=self.show_voice_settings, 
                                        width=8)
            self.settings_btn.pack(side=tk.RIGHT, padx=2)
            
            # 自动滚动开关
            self.auto_scroll_var = tk.BooleanVar(value=self.auto_scroll)
            self.auto_scroll_check = tk.Checkbutton(voice_frame, text="自动滚动", 
                                                  variable=self.auto_scroll_var,
                                                  command=self.toggle_auto_scroll)
            self.auto_scroll_check.pack(side=tk.RIGHT, padx=5)
            
            # 播放速度控制
            speed_frame = tk.Frame(voice_frame)
            speed_frame.pack(side=tk.RIGHT, padx=10)
            
            tk.Label(speed_frame, text="速度:").pack(side=tk.LEFT)
            self.speed_var = tk.DoubleVar(value=self.playback_speed)
            self.speed_scale = tk.Scale(speed_frame, from_=1.0, to=3.0, resolution=0.1,
                                      orient=tk.HORIZONTAL, variable=self.speed_var,
                                      length=80, command=self.update_playback_speed)
            self.speed_scale.pack(side=tk.LEFT, padx=2)
            
            self.speed_label = tk.Label(speed_frame, text=f"{self.playback_speed:.1f}x", width=4)
            self.speed_label.pack(side=tk.LEFT)
            
            # 定时停止设置
            timer_frame = tk.Frame(voice_frame)
            timer_frame.pack(side=tk.RIGHT, padx=10)
            
            self.timer_stop_var = tk.BooleanVar(value=self.timer_stop_enabled)
            self.timer_stop_check = tk.Checkbutton(timer_frame, text="定时停止", 
                                                   variable=self.timer_stop_var,
                                                   command=self.toggle_timer_stop)
            self.timer_stop_check.pack(side=tk.LEFT)
            
            # 定时时间输入框（分钟）
            self.timer_minutes_var = tk.StringVar(value=str(self.timer_stop_minutes))
            self.timer_entry = tk.Entry(timer_frame, textvariable=self.timer_minutes_var, 
                                        width=4, justify=tk.CENTER)
            self.timer_entry.pack(side=tk.LEFT, padx=(2, 0))
            tk.Label(timer_frame, text="分钟").pack(side=tk.LEFT)
            
            # 绑定输入框事件，限制只能输入数字
            self.timer_entry.bind('<KeyRelease>', self.validate_timer_input)
            
            # 定时状态标签
            self.timer_status_label = tk.Label(timer_frame, text="", fg="orange", font=("Arial", 8))
            self.timer_status_label.pack(side=tk.LEFT, padx=(5, 0))

        # 文本框
        self.text = tk.Text(right_frame, wrap=tk.WORD, font=("Arial", self.text_font_size),
                            bg=self.bg_color, fg=self.fg_color)
        self.text.pack(fill=tk.BOTH, expand=True)
        
        # 绑定滚动事件
        self.text.bind("<ButtonRelease-1>", self.on_text_event)
        self.text.bind("<KeyRelease>", self.on_text_event)
        self.text.bind("<MouseWheel>", self.on_text_event)
        self.text.bind("<Button-4>", self.on_text_event)  # Linux 滚轮上
        self.text.bind("<Button-5>", self.on_text_event)  # Linux 滚轮下
        
        # 为文本框添加右键菜单
        self.text_menu = tk.Menu(self.text, tearoff=0)
        if TTS_AVAILABLE and self.tts_engine:
            self.text_menu.add_command(label="从此处开始朗读", command=self.read_from_cursor)
            self.text_menu.add_separator()
        self.text_menu.add_command(label="复制", command=lambda: self.text.event_generate("<<Copy>>"))
        self.text_menu.add_command(label="全选", command=lambda: self.text.tag_add(tk.SEL, "1.0", tk.END))
        self.text.bind("<Button-3>", self.show_text_menu)

    def on_search_change(self, *args):
        """搜索框内容变化时的处理"""
        search_text = self.search_var.get().strip().lower()
        if not search_text:
            self.show_all_chapters()
        else:
            self.filter_chapters(search_text)

    def on_search_enter(self, event):
        """按下回车键时跳转到第一个搜索结果"""
        if self.chapter_listbox.size() > 0:
            self.chapter_listbox.selection_clear(0, tk.END)
            self.chapter_listbox.selection_set(0)
            self.chapter_listbox.activate(0)
            self.jump_to_chapter(None)

    def clear_search(self, event=None):
        """清除搜索"""
        self.search_var.set("")
        self.show_all_chapters()
        self.search_entry.focus()

    def filter_chapters(self, search_text):
        """根据搜索文本过滤章节"""
        if not self.all_chapters:
            return
            
        # 清空当前列表
        self.chapter_listbox.delete(0, tk.END)
        self.filtered_chapters.clear()
        
        # 搜索匹配的章节
        matches = []
        for i, (line_num, chapter_title) in enumerate(self.all_chapters):
            if search_text in chapter_title.lower():
                matches.append((i, line_num, chapter_title))
                self.filtered_chapters.append((line_num, chapter_title))
                self.chapter_listbox.insert(tk.END, chapter_title)
        
        # 更新搜索信息
        total_chapters = len(self.all_chapters)
        found_chapters = len(matches)
        if found_chapters == 0:
            self.search_info_label.config(text=f"未找到匹配的章节", fg="red")
        else:
            self.search_info_label.config(text=f"找到 {found_chapters}/{total_chapters} 个章节", fg="green")
        
        # 如果有匹配结果，选中第一个
        if matches:
            self.chapter_listbox.selection_set(0)
            self.chapter_listbox.activate(0)

    def show_all_chapters(self):
        """显示所有章节"""
        self.chapter_listbox.delete(0, tk.END)
        self.filtered_chapters = self.all_chapters.copy()
        
        for line_num, chapter_title in self.all_chapters:
            self.chapter_listbox.insert(tk.END, chapter_title)
        
        # 清除搜索信息
        self.search_info_label.config(text="")
        
        # 恢复当前章节的高亮
        if self.current_chapter_index >= 0 and self.current_chapter_index < len(self.all_chapters):
            self.chapter_listbox.selection_set(self.current_chapter_index)
            self.chapter_listbox.activate(self.current_chapter_index)
            self.chapter_listbox.see(self.current_chapter_index)

    def show_chapter_menu(self, event):
        """显示章节右键菜单"""
        try:
            self.chapter_menu.post(event.x_root, event.y_root)
        except tk.TclError:
            pass

    def jump_to_selected_chapter(self):
        """跳转到选中的章节"""
        selection = self.chapter_listbox.curselection()
        if selection:
            self.jump_to_chapter(None)

    def copy_chapter_name(self):
        """复制章节名到剪贴板"""
        selection = self.chapter_listbox.curselection()
        if selection:
            index = selection[0]
            if index < len(self.filtered_chapters):
                chapter_title = self.filtered_chapters[index][1]
                self.root.clipboard_clear()
                self.root.clipboard_append(chapter_title)
                messagebox.showinfo("提示", f"已复制章节名：{chapter_title}")

    def on_text_event(self, event=None):
        """统一处理文本事件"""
        print("m")
        self.schedule_scroll_check()
        self.save_scroll_position()

    def schedule_scroll_check(self, event=None):
        """延迟检查当前章节，避免频繁更新"""
        if self.scroll_timer:
            self.root.after_cancel(self.scroll_timer)
        self.scroll_timer = self.root.after(200, self.highlight_current_chapter)

    def highlight_current_chapter(self):
        """高亮当前阅读位置对应的章节"""
        if not self.all_chapters:
            return
            
        try:
            # 获取当前可见区域的第一行
            current_index = self.text.index("@0,10")  # 稍微向下偏移避免边界问题
            line = int(current_index.split(".")[0])
            
            # 找到当前行对应的章节（在所有章节中查找）
            current_chapter = -1
            for i, (chapter_line, _) in enumerate(self.all_chapters):
                if chapter_line <= line:
                    current_chapter = i
                else:
                    break
            
            # 只有当章节发生变化时才更新高亮
            if current_chapter != -1:
                self.current_chapter_index = current_chapter
                
                # 如果没有搜索过滤，正常高亮
                if not self.search_var.get().strip():
                    self.chapter_listbox.selection_clear(0, tk.END)
                    self.chapter_listbox.selection_set(current_chapter)
                    self.chapter_listbox.activate(current_chapter)
                    self.chapter_listbox.see(current_chapter)
                else:
                    # 如果有搜索过滤，检查当前章节是否在过滤结果中
                    current_chapter_info = self.all_chapters[current_chapter]
                    for i, filtered_chapter in enumerate(self.filtered_chapters):
                        if filtered_chapter == current_chapter_info:
                            self.chapter_listbox.selection_clear(0, tk.END)
                            self.chapter_listbox.selection_set(i)
                            self.chapter_listbox.activate(i)
                            self.chapter_listbox.see(i)
                            break
                
                # 更新窗口标题显示当前章节
                chapter_title = self.all_chapters[current_chapter][1]
                self.root.title(f"小说阅读器 - {chapter_title}")
                
        except (ValueError, IndexError, tk.TclError):
            # 处理可能的异常
            pass

    def open_file(self):
        filepath = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if filepath:
            self.load_novel(filepath)

    def open_recent_file(self, event):
        selection = self.recent_listbox.curselection()
        if selection:
            index = selection[0]
            # 从字典中获取文件路径
            file_path = self.recent_paths.get(index)
            if not file_path:
                # 如果字典中没有，使用旧方法（兼容性考虑）
                try:
                    file_path = list(self.config["recent_files"].keys())[index]
                except:
                    messagebox.showerror("错误", "无法获取文件路径")
                    return
                
            self.load_novel(file_path)

    def load_novel(self, filepath):
        if not os.path.exists(filepath):
            messagebox.showerror("错误", f"文件不存在：{filepath}")
            return

        self.current_file = filepath
        self.chapter_positions.clear()
        self.all_chapters.clear()
        self.filtered_chapters.clear()
        self.current_chapter_index = -1
        self.text.delete(1.0, tk.END)
        self.chapter_listbox.delete(0, tk.END)
        
        # 清除搜索
        self.search_var.set("")
        self.search_info_label.config(text="")

        # 尝试多种编码格式
        encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5', 'latin-1']
        content = None
        
        for encoding in encodings:
            try:
                with open(filepath, "r", encoding=encoding) as f:
                    content = f.read()
                print(f"成功使用 {encoding} 编码打开文件")
                break
            except UnicodeDecodeError:
                continue
        
        if content is None:
            messagebox.showerror("错误", "无法解码文件，请尝试其他编码格式")
            return
        lines = content.splitlines()
        
        # 改进的章节识别正则表达式
        chapter_patterns = [
            r"第[零一二三四五六七八九十百千万\d]+章.*",
            r"第[0-9]+章.*",
            r"Chapter\s*\d+.*",
            r"章节\s*\d+.*",
            r"[第]*\d+[章回节].*",
            r"(?:\s*第[一二三四五六七八九十百千万0-9]+[篇章节集卷部][\s:：]?[\s\S]*?){1,}"
        ]
        
        for i, line in enumerate(lines):
            line = line.strip()
            if line:  # 忽略空行
                for pattern in chapter_patterns:
                    if re.match(pattern, line, re.IGNORECASE):
                        chapter_info = (i + 1, line)
                        self.chapter_positions.append(chapter_info)
                        self.all_chapters.append(chapter_info)
                        self.chapter_listbox.insert(tk.END, line)
                        break

        # 初始化过滤章节列表
        self.filtered_chapters = self.all_chapters.copy()

        # 插入文本并加粗章节标题
        for i, line in enumerate(lines):
            self.text.insert(tk.END, line + "\n")
            line = line.strip()
            if line:
                for pattern in chapter_patterns:
                    if re.match(pattern, line, re.IGNORECASE):
                        start = f"{i + 1}.0"
                        end = f"{i + 1}.end"
                        self.text.tag_add("chapter_title", start, end)
                        break
        
        # 配置章节标题样式
        self.text.tag_config("chapter_title", 
                           font=("Arial", self.text_font_size + 2, "bold"),
                           foreground="blue" if self.bg_color == "white" else "lightblue",
                           spacing1=10, spacing3=10)
        
        # 配置朗读高亮样式
        self.text.tag_config("reading_highlight", 
                           background="yellow" if self.bg_color == "white" else "darkblue",
                           foreground="black" if self.bg_color == "white" else "white")

        # 更新阅读记录
        default_position = {
            "line_number": 1,
            "char_position": 0,
            "scroll_fraction": 0.0,
            "tkinter_index": "1.0",
            "window_height": 400
        }
        
        self.config["recent_files"][filepath] = {
            "last_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_position": self.config["recent_files"].get(filepath, {}).get("last_position", default_position)
        }
        self.save_config()
        self.load_recent_listbox()

        # 自动跳转到上次位置
        self.restore_reading_position(filepath)
        self.schedule_scroll_check()
        
    def restore_reading_position(self, filepath):
        """智能恢复阅读位置"""
        try:
            position_data = self.config["recent_files"][filepath]["last_position"]
            
            # 如果是旧格式的位置数据（字符串），转换为新格式
            if isinstance(position_data, str):
                try:
                    self.text.see(position_data)
                    self.text.mark_set(tk.INSERT, position_data)
                    return
                except tk.TclError:
                    position_data = {
                        "line_number": 1,
                        "char_position": 0,
                        "scroll_fraction": 0.0,
                        "tkinter_index": "1.0"
                    }
            
            # 获取文本总行数
            total_lines = int(self.text.index(tk.END).split(".")[0]) - 1
            
            # 方法1：优先使用行号定位（最稳定）
            target_line = position_data.get("line_number", 1)
            if 1 <= target_line <= total_lines:
                target_index = f"{target_line}.0"
                self.text.see(target_index)
                self.text.mark_set(tk.INSERT, target_index)
                print(f"使用行号定位到第 {target_line} 行")
                return

            # 计算目标行的相对位置
            fraction = (target_line - 1) / total_lines
            self.text.yview_moveto(fraction)
            
            # 方法2：使用字符位置定位
            # char_pos = position_data.get("char_position", 0)
            # if char_pos > 0:
            #     try:
            #         # 将字符位置转换为行列位置
            #         text_content = self.text.get("1.0", tk.END)
            #         if char_pos < len(text_content):
            #             # 计算对应的行列位置
            #             lines_before = text_content[:char_pos].count('\n')
            #             line_start = text_content.rfind('\n', 0, char_pos) + 1
            #             col = char_pos - line_start
            #             target_index = f"{lines_before + 1}.{col}"
                        
            #             self.text.see(target_index)
            #             self.text.mark_set(tk.INSERT, target_index)
            #             print(f"使用字符位置定位到 {target_index}")
            #             return
            #     except (ValueError, tk.TclError):
            #         pass
            
            # 方法3：使用滚动条比例定位
            # scroll_fraction = position_data.get("scroll_fraction", 0.0)
            # if 0.0 <= scroll_fraction <= 1.0:
            #     try:
            #         self.text.yview_moveto(scroll_fraction)
            #         print(f"使用滚动比例定位到 {scroll_fraction:.2%}")
            #         return
            #     except tk.TclError:
            #         pass
            
            # 方法4：尝试使用原始tkinter索引
            tkinter_index = position_data.get("tkinter_index", "1.0")
            try:
                self.text.see(tkinter_index)
                self.text.mark_set(tk.INSERT, tkinter_index)
                print(f"使用tkinter索引定位到 {tkinter_index}")
                return
            except tk.TclError:
                pass
            
            # 最后fallback：定位到开头
            self.text.see("1.0")
            self.text.mark_set(tk.INSERT, "1.0")
            print("所有定位方法失败，定位到文件开头")
            
        except (KeyError, TypeError):
            # 没有保存的位置数据，定位到开头
            self.text.see("1.0")
            self.text.mark_set(tk.INSERT, "1.0")

    def save_scroll_position(self, current_line=None):
        if self.current_file:
            try:
                # 获取多个位置信息以提高准确性
                visible_top = self.text.index("@0,0")  # 可见区域顶部
                visible_middle = self.text.index("@0,50")  # 可见区域中间偏上
                
                # 获取当前行号（更稳定的位置标记）
                top_line = int(visible_top.split(".")[0])
                middle_line = int(visible_middle.split(".")[0])
                
                # 获取滚动条位置（百分比，0-1之间）
                scroll_top, scroll_bottom = self.text.yview()
                
                # 计算字符偏移量（从文件开头的绝对位置）
                char_index = self.text.index(visible_middle)
                absolute_char_pos = len(self.text.get("1.0", char_index))

                print("current_line:",current_line)
                print("top_line:",top_line)
                print("middle_line:",middle_line)
                
                if current_line is None:
                    current_line = middle_line
                # 保存多种位置信息
                position_data = {
                    "line_number": current_line,  # 主要使用的行号
                    "char_position": absolute_char_pos,  # 字符位置作为备用
                    "scroll_fraction": scroll_top,  # 滚动条位置作为参考
                    "tkinter_index": visible_middle,  # tkinter索引作为最后备用
                    "window_height": self.text.winfo_height(),  # 窗口高度信息
                }
                
                self.config["recent_files"][self.current_file]["last_position"] = position_data
                self.config["recent_files"][self.current_file]["last_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                
                # 减少保存频率，避免频繁IO
                if hasattr(self, '_save_timer'):
                    self.root.after_cancel(self._save_timer)
                self._save_timer = self.root.after(1000, self.save_config)
                
            except (tk.TclError, ValueError, AttributeError):
                pass

    def jump_to_chapter(self, event):
        selection = self.chapter_listbox.curselection()
        if selection:
            index = selection[0]
            
            # 从当前显示的章节列表中获取章节信息
            if index < len(self.filtered_chapters):
                line_number, chapter_title = self.filtered_chapters[index]
                target_index = f"{line_number}.0"
                
                self.text.see(target_index)
                self.text.mark_set(tk.INSERT, target_index)
                
                # 找到在所有章节中的索引位置
                for i, (line_num, title) in enumerate(self.all_chapters):
                    if line_num == line_number and title == chapter_title:
                        self.current_chapter_index = i
                        break
                
                # 更新窗口标题
                self.root.title(f"小说阅读器 - {chapter_title}")
                
                # 立即保存新位置
                self.save_scroll_position()
                
                print(f"跳转到章节: {chapter_title} (第{line_number}行)")

    def load_recent_listbox(self):
        self.recent_listbox.delete(0, tk.END)
        self.recent_paths = {}  # 清空路径字典
        sorted_items = sorted(self.config["recent_files"].items(), 
                            key=lambda x: x[1]["last_time"], reverse=True)
        for i, (path, info) in enumerate(sorted_items):
            name = os.path.basename(path)
            display = f"{name} - {info['last_time']}"
            self.recent_listbox.insert(tk.END, display)
            # 存储完整路径到字典中
            self.recent_paths[i] = path

    def delete_current_record(self):
        if self.current_file and self.current_file in self.config["recent_files"]:
            del self.config["recent_files"][self.current_file]
            self.save_config()
            self.load_recent_listbox()
            self.root.title("小说阅读器")
            messagebox.showinfo("提示", "已删除当前小说的阅读记录")

    def toggle_night_mode(self):
        if self.bg_color == "white":
            self.bg_color = "black"
            self.fg_color = "white"
            chapter_color = "lightblue"
        else:
            self.bg_color = "white"
            self.fg_color = "black"
            chapter_color = "blue"
            
        self.text.config(bg=self.bg_color, fg=self.fg_color)
        self.text.tag_config("chapter_title", foreground=chapter_color)
        
        # 更新朗读高亮样式
        self.text.tag_config("reading_highlight", 
                           background="yellow" if self.bg_color == "white" else "darkblue",
                           foreground="black" if self.bg_color == "white" else "white")

    def increase_font(self):
        self.text_font_size += 2
        self.text.config(font=("Arial", self.text_font_size))
        self.text.tag_config("chapter_title", 
                           font=("Arial", self.text_font_size + 2, "bold"))

    def decrease_font(self):
        if self.text_font_size > 8:
            self.text_font_size -= 2
            self.text.config(font=("Arial", self.text_font_size))
            self.text.tag_config("chapter_title", 
                               font=("Arial", self.text_font_size + 2, "bold"))

    # 语音阅读相关方法
    def show_text_menu(self, event):
        """显示文本框右键菜单"""
        try:
            self.text_menu.post(event.x_root, event.y_root)
        except tk.TclError:
            pass

    def toggle_auto_scroll(self):
        """切换自动滚动"""
        self.auto_scroll = self.auto_scroll_var.get()

    def validate_timer_input(self, event=None):
        """验证定时输入，只允许数字"""
        value = self.timer_minutes_var.get()
        # 过滤非数字字符
        filtered = ''.join(c for c in value if c.isdigit())
        if filtered != value:
            self.timer_minutes_var.set(filtered)
        
        # 更新定时时间
        if filtered:
            try:
                minutes = int(filtered)
                if minutes > 0:
                    self.timer_stop_minutes = minutes
            except ValueError:
                pass

    def toggle_timer_stop(self):
        """切换定时停止开关"""
        self.timer_stop_enabled = self.timer_stop_var.get()
        
        if self.is_reading:
            if self.timer_stop_enabled:
                self.start_timer_stop()
            else:
                self.cancel_timer_stop()

    def start_timer_stop(self):
        """启动定时停止计时器"""
        # 取消之前的定时器
        self.cancel_timer_stop()
        
        if not self.timer_stop_enabled or not self.is_reading:
            return
        
        try:
            minutes = int(self.timer_minutes_var.get())
            if minutes <= 0:
                minutes = 20
                self.timer_minutes_var.set("20")
        except ValueError:
            minutes = 20
            self.timer_minutes_var.set("20")
        
        self.timer_stop_minutes = minutes
        milliseconds = minutes * 60 * 1000
        
        # 设置定时器
        self.timer_stop_after_id = self.root.after(milliseconds, self.on_timer_stop)
        
        # 更新状态显示
        self.timer_status_label.config(text=f"还剩{minutes}分钟")
        print(f"定时停止已启动：{minutes}分钟后自动停止")

    def cancel_timer_stop(self):
        """取消定时停止"""
        if self.timer_stop_after_id:
            self.root.after_cancel(self.timer_stop_after_id)
            self.timer_stop_after_id = None
        self.timer_status_label.config(text="")

    def on_timer_stop(self):
        """定时停止回调"""
        print("定时停止触发")
        self.timer_stop_after_id = None
        self.timer_status_label.config(text="已停止")
        
        if self.is_reading:
            # 在主线程中停止朗读
            self.root.after(0, self.stop_voice_reading)

    def update_playback_speed(self, value):
        """更新播放速度"""
        self.playback_speed = float(value)
        self.speed_label.config(text=f"{self.playback_speed:.1f}x")
        
        # 如果正在朗读，更新TTS引擎的速度
        if self.tts_engine and self.is_reading:
            adjusted_speed = int(self.reading_speed * self.playback_speed)
            self.tts_engine.setProperty('rate', adjusted_speed)

    def start_voice_reading(self):
        """开始语音阅读"""
        if not TTS_AVAILABLE or not self.tts_engine:
            messagebox.showerror("错误", "语音功能不可用，请安装 pyttsx3 库")
            return
            
        if not self.current_file:
            messagebox.showwarning("提示", "请先打开一个小说文件")
            return
            
        
        # 获取阅读起始位置
        try:
            cursor_pos = self.text.index(tk.INSERT)
            cursor_pos = str(self.config["recent_files"][self.current_file]["last_position"]["line_number"])+".0"
            self.reading_position = cursor_pos
        except tk.TclError:
            self.reading_position = "1.0"
        
        self.is_reading = True
        self.update_voice_buttons()
        
        # 设置播放速度
        adjusted_speed = int(self.reading_speed * self.playback_speed)
        self.tts_engine.setProperty('rate', adjusted_speed)
        
        # 如果启用了定时停止，启动定时器
        if self.timer_stop_enabled:
            self.start_timer_stop()
        
        # 在新线程中开始阅读
        # self._voice_reading_worker()
        reading_thread = threading.Thread(target=self._voice_reading_worker, daemon=False)
        reading_thread.start()

    def stop_voice_reading(self):
        """停止语音阅读并保存进度"""
        # 先设置状态标志，确保线程能够正确退出
        self.is_reading = False
        
        # 取消定时停止
        self.cancel_timer_stop()
        
        # 尝试停止TTS引擎
        if self.reading_thread:
            try:
                self.reading_thread = None
            except Exception as e:
                print(f"停止TTS引擎出错: {e}")
                
        
        # 保存当前阅读进度
        # self.save_scroll_position()
        
        # 在UI线程中更新状态
        def update_ui_state():
            clear_reading_highlight(self)
            self.update_voice_buttons()
            self.voice_status_label.config(text="已停止，进度已保存", fg="red")
        
        # 使用单一的after调用来更新UI，避免多个调用之间的竞争条件
        self.root.after(0, update_ui_state)

    def read_from_cursor(self):
        """从光标位置开始朗读"""
        try:
            cursor_pos = self.text.index(tk.INSERT)
            self.reading_position = cursor_pos
            if self.is_reading:
                self.stop_voice_reading()
                self.root.after(500, self.start_voice_reading)  # 延迟重新开始
            else:
                self.start_voice_reading()
        except tk.TclError:
            pass

    def _voice_reading_worker(self):
        """语音阅读工作线程"""
        try:
            while self.is_reading:
                
                # 获取当前段落的文本和位置
                paragraph_text, start_pos, end_pos,current_line = self._get_current_paragraph_with_position()
                print("_voice_reading_worker current_line:",current_line)
                self.save_scroll_position(current_line)
                if not paragraph_text.strip():
                    # 如果当前段落为空，移动到下一段
                    if not self._move_to_next_paragraph():
                        break
                    continue
                
                # 更新状态和高亮
                self.root.after(0, lambda: self.voice_status_label.config(text="朗读中...", fg="blue"))
                self.root.after(0, lambda s=start_pos, e=end_pos: highlight_reading_text(self,s, e))
                
                # 不需要额外的滚动代码，因为highlight_reading_text已经包含了滚动功能
                
                # 朗读段落
                if self.is_reading :
                    try:
                        # 为每个段落创建新的TTS实例，避免多线程问题
                        adjusted_speed = int(self.reading_speed * self.playback_speed)
                        speak_text(paragraph_text,0,adjusted_speed,self.reading_volume)
                        self.schedule_scroll_check()
                        
                        # paragraph_engine = pyttsx3.init(driverName='sapi5')
                        
                        # 设置当前播放速度
                        # adjusted_speed = int(self.reading_speed * self.playback_speed)
                        # paragraph_engine.setProperty('rate', adjusted_speed)
                        # paragraph_engine.setProperty('volume', self.reading_volume)
                        
                        # # 尝试设置与主引擎相同的语音
                        # if self.tts_engine:
                        #     try:
                        #         voice_id = self.tts_engine.getProperty('voice')
                        #         paragraph_engine.setProperty('voice', voice_id)
                        #     except:
                        #         pass
                        
                        # # 播放当前段落
                        # paragraph_engine.say(paragraph_text)
                        # paragraph_engine.runAndWait()
                        # paragraph_engine.stop()
                    except Exception as e:
                        print(f"TTS朗读出错: {e}")
                        break
                
                # 清除当前段落的高亮显示
                self.root.after(0, lambda: clear_reading_highlight(self))
                
                
                # 移动到下一段
                if not self._move_to_next_paragraph():
                    break
                    
                # 段落之间的停顿，给UI更新和用户感知留出时间
                # 根据播放速度调整停顿时间
                pause_time = 0.3 / self.playback_speed
                time.sleep(pause_time)
                
        except Exception as e:
            print(f"语音阅读出错: {e}")
        finally:
            # 确保在朗读结束时更新状态
            self.is_reading = False
            
            # 取消定时停止
            self.cancel_timer_stop()
                
            # 在UI线程中更新状态
            def update_ui_state():
                clear_reading_highlight(self)
                self.update_voice_buttons()
                self.voice_status_label.config(text="完成，进度已保存", fg="green")
                    
            # 使用单一的after调用来更新UI，避免多个调用之间的竞争条件
            self.root.after(0, update_ui_state)

    def _get_current_paragraph_with_position(self):
        """获取当前段落的文本和位置信息"""
        try:
            # 获取当前行
            current_line = int(self.reading_position.split('.')[0])
            line_start = f"{current_line}.0"
            line_end = f"{current_line}.end"
            
            paragraph_text = self.text.get(line_start, line_end).strip()
            
            # 如果当前行为空，查找下一个非空行
            max_lines = int(self.text.index(tk.END).split('.')[0])
            while not paragraph_text and current_line < max_lines:
                current_line += 1
                line_start = f"{current_line}.0"
                line_end = f"{current_line}.end"
                paragraph_text = self.text.get(line_start, line_end).strip()
                self.reading_position = line_start
            print("_get_current_paragraph_with_position current_line:",current_line)
            
            return paragraph_text, line_start, line_end,current_line
            
        except Exception as e:
            print(f"获取段落文本出错: {e}")
            return "", "1.0", "1.0"

    def _get_current_paragraph(self):
        """获取当前段落的文本"""
        try:
            # 获取当前行
            current_line = int(self.reading_position.split('.')[0])
            line_start = f"{current_line}.0"
            line_end = f"{current_line}.end"
            
            paragraph_text = self.text.get(line_start, line_end).strip()
            
            # 如果当前行为空，查找下一个非空行
            max_lines = int(self.text.index(tk.END).split('.')[0])
            while not paragraph_text and current_line < max_lines:
                current_line += 1
                line_start = f"{current_line}.0"
                line_end = f"{current_line}.end"
                paragraph_text = self.text.get(line_start, line_end).strip()
                self.reading_position = line_start
            
            return paragraph_text
            
        except Exception as e:
            print(f"获取段落文本出错: {e}")
            return ""

    def _move_to_next_paragraph(self):
        """移动到下一段落，并确保找到非空段落"""
        try:
            current_line = int(self.reading_position.split('.')[0])
            max_lines = int(self.text.index(tk.END).split('.')[0])
            
            if current_line >= max_lines - 1:
                return False  # 已到文件末尾
            
            # 移动到下一行
            next_line = current_line + 1
            self.reading_position = f"{next_line}.0"
            
            # 检查是否找到了有内容的段落
            paragraph_text = self._get_current_paragraph()
            if not paragraph_text and next_line < max_lines - 1:
                # 如果当前段落为空且未到文件末尾，递归调用继续查找
                return self._move_to_next_paragraph()
            
            # 找到了有内容的段落，或者已经到达文件末尾
            return bool(paragraph_text)
            
        except Exception as e:
            print(f"移动到下一段落出错: {e}")
            return False

    def update_voice_buttons(self):
        """更新语音控制按钮状态"""
        if not (TTS_AVAILABLE and self.tts_engine):
            return
            
        if self.is_reading:
            self.play_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
        else:
            self.play_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    def show_voice_settings(self):
        """显示语音设置对话框"""
        if not TTS_AVAILABLE or not self.tts_engine:
            messagebox.showerror("错误", "语音功能不可用")
            return
            
        settings_window = tk.Toplevel(self.root)
        settings_window.title("语音设置")
        settings_window.geometry("400x300")
        settings_window.resizable(False, False)
        
        # 语音速度设置
        tk.Label(settings_window, text="语音速度:").pack(pady=5)
        speed_frame = tk.Frame(settings_window)
        speed_frame.pack(pady=5)
        
        speed_var = tk.IntVar(value=self.reading_speed)
        speed_scale = tk.Scale(speed_frame, from_=50, to=300, orient=tk.HORIZONTAL, 
                              variable=speed_var, length=250)
        speed_scale.pack(side=tk.LEFT)
        tk.Label(speed_frame, textvariable=speed_var).pack(side=tk.LEFT, padx=10)
        
        # 播放速度设置
        tk.Label(settings_window, text="播放速度倍率:").pack(pady=5)
        playback_speed_frame = tk.Frame(settings_window)
        playback_speed_frame.pack(pady=5)
        
        playback_speed_var = tk.DoubleVar(value=self.playback_speed)
        playback_speed_scale = tk.Scale(playback_speed_frame, from_=1.0, to=3.0, resolution=0.1,
                                      orient=tk.HORIZONTAL, variable=playback_speed_var, length=250)
        playback_speed_scale.pack(side=tk.LEFT)
        playback_speed_label = tk.Label(playback_speed_frame, text="")
        playback_speed_label.pack(side=tk.LEFT, padx=10)
        
        def update_playback_speed_label(*args):
            playback_speed_label.config(text=f"{playback_speed_var.get():.1f}x")
        playback_speed_var.trace('w', update_playback_speed_label)
        update_playback_speed_label()
        
        # 语音音量设置
        tk.Label(settings_window, text="语音音量:").pack(pady=5)
        volume_frame = tk.Frame(settings_window)
        volume_frame.pack(pady=5)
        
        volume_var = tk.DoubleVar(value=self.reading_volume)
        volume_scale = tk.Scale(volume_frame, from_=0.0, to=1.0, orient=tk.HORIZONTAL, 
                               variable=volume_var, resolution=0.1, length=250)
        volume_scale.pack(side=tk.LEFT)
        volume_label = tk.Label(volume_frame, text="")
        volume_label.pack(side=tk.LEFT, padx=10)
        
        def update_volume_label(*args):
            volume_label.config(text=f"{volume_var.get():.1f}")
        volume_var.trace('w', update_volume_label)
        update_volume_label()
        
        # 语音选择
        tk.Label(settings_window, text="语音选择:").pack(pady=5)
        voice_frame = tk.Frame(settings_window)
        voice_frame.pack(pady=5, fill=tk.X, padx=20)
        
        voice_var = tk.StringVar()
        voice_combo = ttk.Combobox(voice_frame, textvariable=voice_var, state="readonly", width=40)
        
        voices = self.tts_engine.getProperty('voices')
        voice_names = []
        current_voice = self.tts_engine.getProperty('voice')
        
        for i, voice in enumerate(voices):
            name = f"{voice.name} ({voice.id})"
            voice_names.append(name)
            if voice.id == current_voice:
                voice_var.set(name)
        
        voice_combo['values'] = voice_names
        voice_combo.pack(fill=tk.X)
        
        # 测试按钮
        def test_voice():
            self.apply_voice_settings(speed_var.get(), volume_var.get(), voice_combo.current(), playback_speed_var.get())
            if self.tts_engine:
                self.tts_engine.say("这是语音测试")
                self.tts_engine.runAndWait()
        
        tk.Button(settings_window, text="测试语音", command=test_voice).pack(pady=10)
        
        # 按钮框架
        button_frame = tk.Frame(settings_window)
        button_frame.pack(pady=10)
        
        def apply_settings():
            self.apply_voice_settings(speed_var.get(), volume_var.get(), voice_combo.current(), playback_speed_var.get())
            settings_window.destroy()
        
        def cancel_settings():
            settings_window.destroy()
        
        tk.Button(button_frame, text="应用", command=apply_settings).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="取消", command=cancel_settings).pack(side=tk.LEFT, padx=5)

    def apply_voice_settings(self, speed, volume, voice_index, playback_speed=None):
        """应用语音设置"""
        if not self.tts_engine:
            return
            
        try:
            self.reading_speed = speed
            self.reading_volume = volume
            
            if playback_speed is not None:
                self.playback_speed = playback_speed
                self.speed_var.set(playback_speed)
                self.speed_label.config(text=f"{playback_speed:.1f}x")
            
            # 应用实际的TTS速度（基础速度 × 播放倍率）
            actual_speed = int(speed * self.playback_speed)
            self.tts_engine.setProperty('rate', actual_speed)
            self.tts_engine.setProperty('volume', volume)
            
            if voice_index >= 0:
                voices = self.tts_engine.getProperty('voices')
                if voice_index < len(voices):
                    self.tts_engine.setProperty('voice', voices[voice_index].id)
                    
        except Exception as e:
            print(f"应用语音设置时出错: {e}")

    def on_closing(self):
        """窗口关闭时的处理函数"""
        # 停止语音朗读
        if self.is_reading:
            self.stop_voice_reading()
        
        # 释放TTS引擎资源
        if self.reading_thread:
            try:
                self.reading_thread = None
            except:
                pass
        
        # 保存配置
        self.save_config()
        
        # 销毁窗口
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = NovelReaderApp(root)
    root.geometry("1200x700")  # 调整默认窗口大小以适应新功能
    root.mainloop()