import os
import json
import threading
import queue
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import pyttsx3
import re
import time
import subprocess

BASE_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(BASE_DIR, "reader_config.json")
HISTORY_FILE = os.path.join(BASE_DIR, "reader_history.json")


# ============================================================
#                   工具函数：配置与文件操作
# ============================================================

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default
    return default


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass


# ============================================================
#                     语音引擎（精简 + 稳定）
#  MacOS pyttsx3 的正确方式：必须单线程运行 engine.runAndWait()
# ============================================================

class TTSWorker:
    def __init__(self, on_speaking_callback=None, on_done_callback=None):
        """
        on_speaking_callback(text) → 开始朗读某段时触发
        on_done_callback(text) → 朗读完毕某段后触发
        """
        self.tts_queue = queue.Queue()
        self.running = True

        self.on_speaking = on_speaking_callback
        self.on_done = on_done_callback

        # 初始化 pyttsx3
        try:
            self.engine = pyttsx3.init(driverName='nsss')
            # self.engine.setProperty('voice', 'com.apple.speech.synthesis.voice.Alex')
        except:
            self.engine = None
            print("⚠ 无法初始化 pyttsx3 引擎")

        # 默认参数
        self.rate = 180
        self.volume = 1.0
        self._proc = None
        self._is_darwin = sys.platform == 'darwin'

        self.set_rate(self.rate)
        self.set_volume(self.volume)

        # 后台线程
        self.thread = threading.Thread(target=self.worker_loop, daemon=True)
        self.thread.start()

    # -----------------------
    #     参数设置
    # -----------------------
    def set_rate(self, v):
        self.rate = v
        try:
            self.engine.setProperty('rate', v)
        except:
            pass

    def set_volume(self, v):
        self.volume = v
        try:
            self.engine.setProperty('volume', v)
        except:
            pass

    # -----------------------
    #     队列操作
    # -----------------------
    def speak(self, text):
        """加入朗读队列"""
        self.tts_queue.put(("speak", text))

    def stop(self):
        """停止朗读"""
        # 发送停止信号并清空后续朗读任务
        try:
            self.tts_queue.put(("stop", None))
        except Exception:
            pass
        self._flush_queue()

    def close(self):
        # 尝试终止当前系统语音进程
        try:
            if hasattr(self, "_proc") and self._proc and self._proc.poll() is None:
                self._proc.terminate()
        except Exception:
            pass

        # 标记线程退出并清空队列
        self.running = False
        try:
            self.tts_queue.put(("quit", None))
        except Exception:
            pass
        self._flush_queue()

    def _flush_queue(self):
        try:
            while True:
                self.tts_queue.get_nowait()
        except Exception:
            pass

    # -----------------------
    #     主循环（唯一操作 runAndWait）
    # -----------------------
    def worker_loop(self):
        while self.running:
            try:
                cmd, text = self.tts_queue.get()
            except:
                continue

            if cmd == "quit":
                # 退出前尽力终止语音进程
                try:
                    if hasattr(self, "_proc") and self._proc and self._proc.poll() is None:
                        self._proc.terminate()
                except Exception:
                    pass
                break

            if cmd == "stop":
                if self._is_darwin:
                    try:
                        if self._proc and self._proc.poll() is None:
                            self._proc.terminate()
                    except:
                        pass
                else:
                    try:
                        if self.engine:
                            self.engine.stop()
                    except:
                        pass
                continue

            if cmd == "speak":
                if text.strip() == "":
                    continue

                if self.on_speaking:
                    self.on_speaking(text)

                if self._is_darwin:
                    try:
                        args = ["say", "-r", str(self.rate), text]
                        self._proc = subprocess.Popen(args)
                        self._proc.wait()
                    except Exception:
                        pass
                else:
                    try:
                        if self.engine:
                            self.engine.say(text)
                            self.engine.runAndWait()
                    except Exception:
                        pass

                if self.on_done:
                    self.on_done(text)


# ============================================================
#                       主应用（UI + 逻辑）
# ============================================================

class NovelReaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("精简小说阅读器")
        self.root.geometry("1100x700")

        # 状态与配置
        self.config = load_json(CONFIG_FILE, {"font_size": 14, "theme": "light"})
        self.history = load_json(HISTORY_FILE, {"recent": []})  # 最近文件列表（路径）
        self.current_file = None
        self.lines = []          # 文件行列表
        self.chapters = []       # 列表 of (line_no, title)
        self.filtered_chapters = []  # used for search view
        self.current_chapter_index = -1
        self.reading = False
        self.reading_thread = None
        self.stop_flag = threading.Event()

        # 初始化主线程语音引擎（macOS 使用 nsss）
        try:
            if sys.platform == 'darwin':
                self.tts_engine = pyttsx3.init(driverName='nsss')
                # self.tts_engine.setProperty('voice', 'com.apple.speech.synthesis.voice.Alex')
                
            else:
                self.tts_engine = pyttsx3.init()
        except Exception:
            self.tts_engine = None

        # TTS worker（单线程安全）
        self.tts_worker = TTSWorker(on_speaking_callback=self._on_tts_speaking,
                                    on_done_callback=self._on_tts_done)
        # 用于等待每段朗读完成
        self._tts_done_event = threading.Event()

        # UI components
        self._build_ui()

        # 如果有历史，加载到列表
        self._refresh_history_listbox()

    # -----------------------
    #      UI 构建
    # -----------------------
    def _build_ui(self):
        # 左侧：历史 + 搜索 + 章节列表
        left_frame = tk.Frame(self.root, width=320)
        left_frame.pack(side=tk.LEFT, fill=tk.Y)

        # 最近阅读（History）
        history_label = tk.Label(left_frame, text="最近阅读", anchor="w")
        history_label.pack(fill=tk.X, padx=6, pady=(6, 0))

        history_frame = tk.Frame(left_frame)
        history_frame.pack(fill=tk.X, padx=6)
        self.history_listbox = tk.Listbox(history_frame, height=4)
        self.history_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        hist_scroll = tk.Scrollbar(history_frame, command=self.history_listbox.yview)
        hist_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.history_listbox.config(yscrollcommand=hist_scroll.set)
        self.history_listbox.bind("<Double-Button-1>", self._on_history_open)

        # 文件操作按钮
        btn_frame = tk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, padx=6, pady=6)
        tk.Button(btn_frame, text="打开文件", command=self.open_file).pack(side=tk.LEFT)
        tk.Button(btn_frame, text="移除选中历史", command=self._remove_selected_history).pack(side=tk.RIGHT)

        # 搜索栏
        search_label = tk.Label(left_frame, text="章节目录", anchor="w")
        search_label.pack(fill=tk.X, padx=6, pady=(8, 0))

        search_box = tk.Frame(left_frame)
        search_box.pack(fill=tk.X, padx=6)
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_box, textvariable=self.search_var)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.search_entry.bind("<KeyRelease>", lambda e: self.filter_chapters(self.search_var.get().strip()))
        tk.Button(search_box, text="清空", command=self._clear_search).pack(side=tk.RIGHT, padx=(4,0))

        # 章节列表
        chapter_frame = tk.Frame(left_frame)
        chapter_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6,6))
        self.chapter_listbox = tk.Listbox(chapter_frame)
        self.chapter_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        chapter_scroll = tk.Scrollbar(chapter_frame, command=self.chapter_listbox.yview)
        chapter_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.chapter_listbox.config(yscrollcommand=chapter_scroll.set)
        self.chapter_listbox.bind("<<ListboxSelect>>", self._on_chapter_select)
        self.chapter_listbox.bind("<Double-Button-1>", self._on_chapter_double)

        # 右侧：文本与语音控制
        right_frame = tk.Frame(self.root)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 顶部工具栏
        top_toolbar = tk.Frame(right_frame)
        top_toolbar.pack(fill=tk.X, pady=4)

        self.btn_play = tk.Button(top_toolbar, text="▶ 播放", command=self.start_reading)
        self.btn_play.pack(side=tk.LEFT, padx=6)
        self.btn_stop = tk.Button(top_toolbar, text="⏹ 停止", command=self.stop_reading, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT)

        tk.Button(top_toolbar, text="从光标处读", command=self.read_from_cursor).pack(side=tk.LEFT, padx=6)

        tk.Label(top_toolbar, text="字体:").pack(side=tk.LEFT, padx=(12,0))
        self.font_size_var = tk.IntVar(value=self.config.get("font_size", 14))
        tk.Spinbox(top_toolbar, from_=8, to=40, width=4, textvariable=self.font_size_var, command=self._apply_font).pack(side=tk.LEFT)

        self.theme_var = tk.StringVar(value=self.config.get("theme","light"))
        tk.Button(top_toolbar, text="切换夜间/日间", command=self._toggle_theme).pack(side=tk.RIGHT, padx=6)

        # 语音参数
        tts_frame = tk.Frame(top_toolbar)
        tts_frame.pack(side=tk.RIGHT, padx=6)
        tk.Label(tts_frame, text="速度").pack(side=tk.LEFT)
        self.tts_rate_var = tk.IntVar(value=self.config.get("tts_rate", self.tts_worker.rate))
        tk.Spinbox(tts_frame, from_=80, to=300, width=4, textvariable=self.tts_rate_var, command=self._apply_tts_rate).pack(side=tk.LEFT)
        try:
            self.tts_rate_var.trace_add('write', lambda *args: self._apply_tts_rate())
        except Exception:
            pass
        tk.Label(tts_frame, text="音量").pack(side=tk.LEFT, padx=(6,0))
        self.tts_vol_var = tk.DoubleVar(value=self.config.get("tts_volume", self.tts_worker.volume))
        tk.Spinbox(tts_frame, from_=0.0, to=1.0, increment=0.1, width=4, textvariable=self.tts_vol_var, command=self._apply_tts_vol).pack(side=tk.LEFT)
        try:
            self.tts_vol_var.trace_add('write', lambda *args: self._apply_tts_vol())
        except Exception:
            pass

        # 文本区域
        text_frame = tk.Frame(right_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0,6))
        self.text = tk.Text(text_frame, wrap=tk.WORD, font=("Arial", self.font_size_var.get()))
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.text.config(state=tk.DISABLED)
        text_scroll = tk.Scrollbar(text_frame, command=self.text.yview)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_scroll = text_scroll
        self.text.config(yscrollcommand=text_scroll.set)
        self.text.bind('<ButtonRelease-1>', self._on_text_click)
        self.text.bind('<KeyRelease>', self._on_text_key)
        self.text.tag_configure("chapter", font=("Arial", self.font_size_var.get()+2, "bold"), foreground="blue")
        self.text.tag_configure("reading_highlight", background="yellow")

        # 状态栏
        self.status_var = tk.StringVar(value="")
        status_bar = tk.Label(self.root, textvariable=self.status_var, anchor="w")
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        try:
            self._apply_theme(self.theme_var.get())
        except Exception:
            pass
        try:
            self.tts_worker.set_rate(int(self.tts_rate_var.get()))
            self.tts_worker.set_volume(float(self.tts_vol_var.get()))
        except Exception:
            pass

    # -----------------------
    #    UI 回调与工具
    # -----------------------
    def _refresh_history_listbox(self):
        self.history_listbox.delete(0, tk.END)
        for p in self.history.get("recent", []):
            self.history_listbox.insert(tk.END, os.path.basename(p))

    def _add_to_history(self, path):
        recent = self.history.get("recent", [])
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        # 保留最近 10 条
        recent = recent[:10]
        self.history["recent"] = recent
        save_json(HISTORY_FILE, self.history)
        self._refresh_history_listbox()

    def _save_scroll_position(self, line=None):
        if not self.current_file:
            return
        try:
            if line is None:
                top_index = self.text.index('@0,0')
                line = int(top_index.split('.')[0])
            frac = 0.0
            try:
                y0, _ = self.text.yview()
                frac = float(y0)
            except Exception:
                pass
            pos = self.history.get("positions", {})
            pos[self.current_file] = {"line": line, "fraction": frac}
            self.history["positions"] = pos
            save_json(HISTORY_FILE, self.history)
        except Exception:
            pass

    def _restore_last_position(self):
        try:
            pos = self.history.get("positions", {})
            info = pos.get(self.current_file)
            if not info:
                return
            line = int(info.get("line", 1))
            frac = float(info.get("fraction", 0.0))
            self.text.see(f"{line}.0")
            try:
                self.text.yview_moveto(frac)
            except Exception:
                pass
            try:
                self._scroll_line_to_top(line)
            except Exception:
                pass
        except Exception:
            pass

    def _on_text_scroll(self, first, last):
        try:
            if hasattr(self, 'text_scroll') and self.text_scroll:
                self.text_scroll.set(first, last)
            top_index = self.text.index('@0,0')
            line = int(top_index.split('.')[0])
            self._sync_chapter_selection(line)
        except Exception:
            pass

    def _on_text_click(self, event):
        try:
            idx = self.text.index(f'@{event.x},{event.y}')
            line = int(idx.split('.')[0])
            self.last_clicked_line = line
            try:
                self._save_scroll_position(line)
            except Exception:
                pass
            self._sync_chapter_selection(line)
        except Exception:
            pass

    def _on_text_key(self, event):
        try:
            top_index = self.text.index('@0,0')
            line = int(top_index.split('.')[0])
            self._sync_chapter_selection(line)
        except Exception:
            pass

    def _remove_selected_history(self):
        sel = self.history_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        recent = self.history.get("recent", [])
        if idx < len(recent):
            recent.pop(idx)
            self.history["recent"] = recent
            save_json(HISTORY_FILE, self.history)
            self._refresh_history_listbox()

    def _on_history_open(self, event):
        sel = self.history_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        recent = self.history.get("recent", [])
        if idx < len(recent):
            self.load_file(recent[idx])

    def _clear_search(self):
        self.search_var.set("")
        self.filter_chapters("")

    def _apply_font(self):
        size = self.font_size_var.get()
        self.text.config(font=("Arial", size))
        self.text.tag_configure("chapter", font=("Arial", size+2, "bold"))

        self.config["font_size"] = size
        save_json(CONFIG_FILE, self.config)

    def _toggle_theme(self):
        if self.theme_var.get() == "light":
            self.theme_var.set("dark")
            self._apply_theme("dark")
        else:
            self.theme_var.set("light")
            self._apply_theme("light")
        self.config["theme"] = self.theme_var.get()
        save_json(CONFIG_FILE, self.config)

    def _apply_theme(self, theme):
        try:
            if theme == "dark":
                bg = "#111111"
                fg = "#efefef"
                accent_bg = "#1a1a1a"
                select_bg = "#eaeaea"
                select_fg = fg
                btn_bg = "#000000"
                btn_fg = "#000000"
                btn_active_bg = "#000000"
                btn_active_fg = "#000000"
            else:
                bg = "white"
                fg = "black"
                accent_bg = "#f4f4f4"
                select_bg = "#cce5ff"
                select_fg = "black"
                btn_bg = accent_bg
                btn_fg = fg
                btn_active_bg = select_bg
                btn_active_fg = select_fg

            def style_widget(w):
                try:
                    # common
                    w.configure(bg=bg)
                except Exception:
                    pass
                try:
                    w.configure(fg=fg)
                except Exception:
                    pass
                # specific tweaks
                import tkinter as tkmod
                if isinstance(w, tk.Text):
                    try:
                        w.configure(bg=bg, fg=fg, insertbackground=fg, selectbackground=select_bg, selectforeground=select_fg)
                    except Exception:
                        pass
                if isinstance(w, tk.Listbox):
                    try:
                        w.configure(bg=bg, fg=fg, selectbackground=select_bg, selectforeground=select_fg)
                    except Exception:
                        pass
                if isinstance(w, (tk.Entry, tk.Spinbox)):
                    try:
                        w.configure(bg=accent_bg, fg=fg, insertbackground=fg)
                    except Exception:
                        pass
                if isinstance(w, tk.Label):
                    try:
                        w.configure(bg=accent_bg, fg=fg)
                    except Exception:
                        pass
                if isinstance(w, tk.Button):
                    try:
                        w.configure(bg=btn_bg, fg=btn_fg, activebackground=btn_active_bg, activeforeground=btn_active_fg, highlightbackground=btn_bg)
                    except Exception:
                        pass
                if isinstance(w, tk.Frame):
                    try:
                        w.configure(bg=bg)
                    except Exception:
                        pass

            def walk(w):
                style_widget(w)
                for c in w.winfo_children():
                    walk(c)

            try:
                self.root.configure(bg=bg)
            except Exception:
                pass
            walk(self.root)
        except Exception:
            pass

    def _apply_tts_rate(self):
        val = int(self.tts_rate_var.get())
        try:
            self.tts_worker.set_rate(val)
        except Exception:
            pass
        try:
            if self.tts_engine:
                self.tts_engine.setProperty('rate', val)
        except Exception:
            pass
        self.config["tts_rate"] = val
        save_json(CONFIG_FILE, self.config)

    def _apply_tts_vol(self):
        try:
            val = float(self.tts_vol_var.get())
        except Exception:
            return
        try:
            self.tts_worker.set_volume(val)
        except Exception:
            pass
        try:
            if self.tts_engine:
                self.tts_engine.setProperty('volume', val)
        except Exception:
            pass
        self.config["tts_volume"] = val
        save_json(CONFIG_FILE, self.config)

    # -----------------------
    #    打开与加载文件
    # -----------------------
    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            self.load_file(path)

    def load_file(self, path):
        if not os.path.exists(path):
            messagebox.showerror("错误", "文件不存在")
            return
        try:
            # 尝试多种编码
            encs = ["utf-8", "gbk", "gb2312", "gb18030", "latin-1"]
            content = None
            for e in encs:
                try:
                    with open(path, "r", encoding=e) as f:
                        content = f.read()
                    print(f"使用编码: {e}")
                    break
                except Exception:
                    print(f"编码 {e} 失败")
                    continue
            if content is None:
                messagebox.showerror("错误", "无法读取文件（编码问题）")
                return
            self.current_file = path
            self._add_to_history(path)
            self._load_content_to_text(content)
            self._auto_parse_chapters()
            # self.status_var.set(f"已加载: {os.path.basename(path)}")
            try:
                self._restore_last_position()
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("错误", f"加载文件失败: {e}")

    def _load_content_to_text(self, content):
        # 将文本切行并显示到 Text
        self.lines = content.splitlines()
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        for i, line in enumerate(self.lines):
            self.text.insert(tk.END, line + "\n")
        self.text.config(state=tk.DISABLED)

    # -----------------------
    #    分章与目录
    # -----------------------
    def _auto_parse_chapters(self):
        self.chapters.clear()
        patterns = [
            r"第[零一二三四五六七八九十百千万\d]+章.*",
            r"第[0-9]+章.*",
            r"Chapter\s*\d+.*",
            r"章节\s*\d+.*",
            r"[第]*\d+[章回节].*",
            r"(?:\s*第[一二三四五六七八九十百千万0-9]+[篇章节集卷部][\s:：]?[\s\S]*?){1,}"
        ]
        compiled = [re.compile(p) for p in patterns]
        for i, line in enumerate(self.lines):
            s = line.strip()
            if not s:
                continue
            matched = False
            for c in compiled:
                if c.match(s):
                    self.chapters.append((i+1, s))
                    matched = True
                    break
            # optionally custom heuristics
        # fallback: treat start as chapter if none found
        if not self.chapters:
            # create pseudo-chapters every 200 lines
            step = max(200, len(self.lines)//10)
            for i in range(0, len(self.lines), step):
                title = f"第{(i//step)+1}部分"
                self.chapters.append((i+1, title))

        # populate chapter listbox
        self.filtered_chapters = self.chapters.copy()
        self.chapter_listbox.delete(0, tk.END)
        for _, title in self.filtered_chapters:
            self.chapter_listbox.insert(tk.END, title)

        # mark chapter tags in text
        self.text.tag_remove("chapter", "1.0", tk.END)
        for line_no, _title in self.chapters:
            start = f"{line_no}.0"
            # tag only that line
            self.text.tag_add("chapter", start, f"{line_no}.end")

    def filter_chapters(self, keyword):
        if not keyword:
            self.filtered_chapters = self.chapters.copy()
        else:
            kw = keyword.lower()
            self.filtered_chapters = [(ln, t) for ln, t in self.chapters if kw in t.lower()]
        self.chapter_listbox.delete(0, tk.END)
        for _, title in self.filtered_chapters:
            self.chapter_listbox.insert(tk.END, title)

    def _on_chapter_select(self, event):
        sel = self.chapter_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self.filtered_chapters):
            line_no, title = self.filtered_chapters[idx]
            # scroll text to that line
            self.text.see(f"{line_no}.0")
            self._scroll_line_to_top(line_no)
            self.current_chapter_index = self.chapters.index((line_no, title))

    def _on_chapter_double(self, event):
        self._on_chapter_select(event)

    # -----------------------
    #    朗读控制（播放 / 停止 / worker）
    # -----------------------
    def start_reading(self):
        if not self.current_file:
            messagebox.showwarning("警告", "请先打开文件")
            return
        if self.reading:
            return

        # 获取起始行
        sel = self.chapter_listbox.curselection()
        if sel:
            idx = sel[0]
            if idx < len(self.filtered_chapters):
                line_no, _ = self.filtered_chapters[idx]
                start_line = line_no
            else:
                start_line = 1
        else:
            try:
                idx = int(self.text.index(tk.INSERT).split(".")[0])
                start_line = idx
            except:
                start_line = 1

        try:
            self.tts_worker.set_rate(int(self.tts_rate_var.get()))
            self.tts_worker.set_volume(float(self.tts_vol_var.get()))
        except Exception:
            pass

        self.reading = True
        self.stop_flag.clear()
        self.btn_play.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.status_var.set("朗读中...")

        self.root.after(0, lambda: self._read_paragraphs_from(start_line))

    def stop_reading(self):
        if not self.reading:
            return
        self.stop_flag.set()
        try:
            self.tts_worker.stop()
        except Exception:
            pass
        # 注意：pyttsx3 在 macOS 无法真正“停止”正在朗读的内容
        # 所以我们只能跳过后续段落
        self.reading = False
        self.btn_play.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.status_var.set("已停止")
        try:
            self.text.tag_remove("reading_highlight", "1.0", tk.END)
        except:
            pass

    def _read_paragraphs_from(self, start_line):
        if not self.reading or self.stop_flag.is_set():
            self._reading_finished_ui()
            return

        # 提取下一个段落（同你原来的逻辑）
        total_lines = len(self.lines)
        line = start_line
        para_lines = []
        while line <= total_lines:
            txt = self.lines[line-1].strip()
            line += 1
            if txt == "":
                if para_lines:
                    break
                else:
                    continue
            para_lines.append(txt)
            
            if len(" ".join(para_lines)) > len(para_lines):
                break

        if not para_lines:
            self._reading_finished_ui()
            return

        paragraph = "，".join(para_lines).strip()
        if not paragraph:
            # 跳到下一段
            self.root.after(100, lambda: self._read_paragraphs_from(line))
            return

        # 高亮
        start_idx = f"{line - len(para_lines)}.0"
        end_idx = f"{line-1}.end"
        self._highlight_and_see(start_idx, end_idx)
        self._sync_chapter_selection(line)

        self._tts_done_event.clear()
        try:
            self.tts_worker.speak(paragraph)
        except Exception:
            pass

        # 如果用户中途点了停止，不再继续
        if self.stop_flag.is_set():
            self._reading_finished_ui()
            return

        self.root.after(50, lambda: self._wait_tts_then_continue(line))

    def _wait_tts_then_continue(self, next_line):
        if self.stop_flag.is_set() or not self.reading:
            self._reading_finished_ui()
            return
        if self._tts_done_event.is_set():
            self._read_paragraphs_from(next_line)
            return
        self.root.after(50, lambda: self._wait_tts_then_continue(next_line))

    def _sync_chapter_selection(self, line):
        try:
            chap_idx = 0
            for i, (ln, _) in enumerate(self.chapters):
                if ln <= line:
                    chap_idx = i
                else:
                    break
            title = self.chapters[chap_idx][1]
            for i, (ln, t) in enumerate(self.filtered_chapters):
                if t == title:
                    self.chapter_listbox.selection_clear(0, tk.END)
                    self.chapter_listbox.selection_set(i)
                    self.chapter_listbox.activate(i)
                    self.chapter_listbox.see(i)
                    break
        except Exception:
            pass

    def _scroll_line_to_top(self, line):
        try:
            target = f"{line}.0"
            self.text.see(target)
            top_index = self.text.index('@0,0')
            top = int(top_index.split('.')[0])
            diff = line - top
            if diff != 0:
                self.text.yview_scroll(diff, 'units')
        except Exception:
            pass

    def read_from_cursor(self):
        try:
            line = None
            try:
                if self.text.tag_ranges(tk.SEL):
                    i = self.text.index(tk.SEL_FIRST)
                    line = int(str(i).split(".")[0])
            except Exception:
                pass
            if line is None:
                try:
                    line = int(self.text.index(tk.INSERT).split(".")[0])
                except Exception:
                    pass
            if line is None:
                line = getattr(self, "last_clicked_line", None) or 1
            try:
                self.tts_worker.set_rate(int(self.tts_rate_var.get()))
                self.tts_worker.set_volume(float(self.tts_vol_var.get()))
            except Exception:
                pass
            self.reading = True
            self.stop_flag.clear()
            self.btn_play.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.status_var.set("朗读中...")
            self.root.after(0, lambda: self._read_paragraphs_from(line))
        except Exception:
            pass

    def _reading_loop(self, start_line):
        """
        从 start_line 开始逐行读取，遇到空行为一段断点；
        对于每一段，用 tts_worker.speak() 发给 TTS，并等待 on_done 回调设置事件。
        """
        total_lines = len(self.lines)
        line = start_line
        while line <= total_lines and not self.stop_flag.is_set():
            # gather a paragraph (连续非空行)
            para_lines = []
            while line <= total_lines:
                txt = self.lines[line-1].strip()
                line += 1
                if txt == "":
                    if para_lines:
                        break
                    else:
                        continue
                para_lines.append(txt)
                # cap paragraph length to avoid too long single chunk
                if len(" ".join(para_lines)) > 800:
                    break
            paragraph = "，".join(para_lines).strip()
            if not paragraph:
                continue

            # scroll/highlight in main thread
            start_idx = f"{line - len(para_lines)}.0"
            end_idx = f"{line-1}.end"
            try:
                self.root.after(0, lambda s=start_idx, e=end_idx: self._highlight_and_see(s, e))
            except:
                pass

            # prepare to wait for tts done
            self._tts_done_event.clear()

            # send to tts worker (it will run runAndWait in its own thread)
            try:
                self.tts_worker.speak(paragraph)
            except Exception as e:
                print("发送到 TTS 失败:", e)
                break

            # wait for done or stop
            # timeout to avoid stuck (estimate by length)
            timeout = max(5, len(paragraph) / 5)
            waited = self._tts_done_event.wait(timeout=timeout)
            if not waited:
                # 超时，仍然继续或重试一次
                print("TTS 等待超时，继续下一个段落")
            if self.stop_flag.is_set():
                break

            # small pause
            time.sleep(0.2)

        # reading finished / stopped
        self.reading = False
        self.root.after(0, self._reading_finished_ui)

    def _highlight_and_see(self, start, end):
        # clear previous highlight
        try:
            self.text.tag_remove("reading_highlight", "1.0", tk.END)
            self.text.tag_add("reading_highlight", start, end)
            self.text.see(start)
        except tk.TclError:
            pass

    def _reading_finished_ui(self):
        # clear highlight, reset buttons
        try:
            self.text.tag_remove("reading_highlight", "1.0", tk.END)
        except:
            pass
        self.btn_play.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.status_var.set("完成")
        try:
            top_index = self.text.index('@0,0')
            ln = int(top_index.split('.')[0])
            self._save_scroll_position(ln)
        except Exception:
            pass

    # -----------------------
    #    TTS 回调（由 TTSWorker 在其线程中触发）
    # -----------------------
    def _on_tts_speaking(self, text):
        # called when TTSWorker 开始朗读（在 TTS 线程）
        # 如果要更新 UI（主线程），请通过 self.root.after 调用
        self.root.after(0, lambda: self.status_var.set("朗读中..."))

    def _on_tts_done(self, text):
        # called when TTSWorker 朗读完毕一段（在 TTS 线程）
        # set event to notify reading thread
        self._tts_done_event.set()

    # -----------------------
    #    退出与清理
    # -----------------------
    def close(self):
        # stop reading
        self.stop_flag.set()
        try:
            # 先停止当前朗读，再关闭工作线程
            self.tts_worker.stop()
        except:
            pass
        try:
            print("退出时")
            self.tts_worker.close()
        except:
            pass
        save_json(CONFIG_FILE, self.config)
        save_json(HISTORY_FILE, self.history)


# ============================================================
#                       主程序入口
# ============================================================
def main():
    root = tk.Tk()
    app = NovelReaderApp(root)

    def on_closing():
        if app.reading:
            if not messagebox.askyesno("退出确认", "当前正在朗读，确认退出？"):
                return
        app.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
