from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import tkinter as tk
import sys
import webbrowser
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from logging.handlers import RotatingFileHandler
from tkinter import filedialog, messagebox, ttk, simpledialog
from zoneinfo import ZoneInfo

try:
    from core import BeatItem, calculate_publish_times, export_manifest, pair_audio_and_covers, render_video, resolve_title
    from quota import APP_DAILY_UPLOAD_LIMIT, record_attempt, remaining as quota_remaining
except ImportError:
    from .core import BeatItem, calculate_publish_times, export_manifest, pair_audio_and_covers, render_video, resolve_title
    from .quota import APP_DAILY_UPLOAD_LIMIT, record_attempt, remaining as quota_remaining

def _app_home() -> Path:
    override = os.environ.get("ABEATS_HOME")
    if override:
        home = Path(override).expanduser()
    elif os.environ.get("LOCALAPPDATA"):
        home = Path(os.environ["LOCALAPPDATA"]) / "A-BEATS"
    else:
        home = Path.home() / ".a-beats"
    home.mkdir(parents=True, exist_ok=True)
    return home


APP_DIR = _app_home()
DATA_DIR = APP_DIR
CONFIG_FILE = DATA_DIR / "settings.json"
QUEUE_FILE = DATA_DIR / "queue.json"
LOG_FILE = DATA_DIR / "a_beats.log"
QUOTA_FILE = DATA_DIR / "youtube_upload_usage.json"

BG = "#100b18"
PANEL = "#1b1426"
PANEL_2 = "#241a33"
PURPLE = "#9b6cff"
PURPLE_DARK = "#6f42c1"
TEXT = "#f5f0ff"
MUTED = "#b8abc9"
GREEN = "#79d9a5"
RED = "#ff8585"


class ABeatsApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("A-BEATS — YouTube Beat Publisher")
        self.root.geometry("1200x790")
        self.root.minsize(1040, 700)
        self.root.configure(bg=BG)
        self.logger = logging.getLogger("a_beats")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            self.logger.addHandler(handler)
        icon_path = Path(__file__).resolve().parent.parent / "assets" / "a_beats.ico"
        if icon_path.is_file():
            try:
                self.root.iconbitmap(str(icon_path))
            except tk.TclError:
                pass
        self.items: list[BeatItem] = []
        self.track_names: list[str] = []
        self.events: queue.Queue = queue.Queue()
        self.worker_active = False
        self._queue_lock = threading.Lock()
        self.audio_dir = tk.StringVar()
        self.cover_dir = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(APP_DIR / "output"))
        bundle_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        ffmpeg_candidates = [APP_DIR / "ffmpeg" / "bin" / "ffmpeg.exe", bundle_dir / "ffmpeg" / "bin" / "ffmpeg.exe"]
        bundled_ffmpeg = next((path for path in ffmpeg_candidates if path.is_file()), None)
        self.ffmpeg_path = tk.StringVar(value=str(bundled_ffmpeg) if bundled_ffmpeg else "")
        self.resolution = tk.StringVar(value="1920x1080")
        self.artist = tk.StringVar()
        self.title_template = tk.StringVar(value='{artist} Type Beat - "{track_name}"')
        self.start_time = tk.StringVar(value=self._default_start())
        self.interval = tk.StringVar(value="24")
        self.timezone_name = tk.StringVar(value="America/New_York")
        self.description = tk.StringVar(value="🎧 Produced by {artist}\n\nFor leasing / business inquiries: add your contact here.")
        self.tags = tk.StringVar(value="type beat, hip hop instrumental, rap instrumental")
        self.notify_subscribers = tk.BooleanVar(value=True)
        self.channel_selection = tk.StringVar()
        self.channels: list[dict] = []
        self._load_settings()
        self._load_queue()
        self._setup_style()
        self._build_ui()
        if self.items:
            self._refresh_table()
        self._reload_channels()
        self.root.after(150, self._poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _default_start(self) -> str:
        try:
            now = datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            now = datetime.now()
        next_day = now + timedelta(days=1)
        return next_day.replace(hour=18, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")

    def _load_settings(self) -> None:
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                for key, variable in [
                    ("audio_dir", self.audio_dir), ("cover_dir", self.cover_dir), ("output_dir", self.output_dir),
                    ("ffmpeg_path", self.ffmpeg_path), ("resolution", self.resolution), ("artist", self.artist),
                    ("title_template", self.title_template), ("start_time", self.start_time),
                    ("interval", self.interval), ("timezone_name", self.timezone_name),
                    ("description", self.description), ("tags", self.tags), ("notify_subscribers", self.notify_subscribers),
                ]:
                    if key in data:
                        if key == "ffmpeg_path" and (not data[key] or not Path(data[key]).is_file()):
                            continue
                        variable.set(data[key])
            except (OSError, json.JSONDecodeError, tk.TclError):
                pass

    def _save_settings(self) -> None:
        if hasattr(self, "description_box"):
            self.description.set(self.description_box.get("1.0", "end-1c"))
        data = {
            "audio_dir": self.audio_dir.get(), "cover_dir": self.cover_dir.get(),
            "output_dir": self.output_dir.get(), "ffmpeg_path": self.ffmpeg_path.get(),
            "resolution": self.resolution.get(), "artist": self.artist.get(),
            "title_template": self.title_template.get(), "start_time": self.start_time.get(),
            "interval": self.interval.get(), "timezone_name": self.timezone_name.get(),
            "description": self.description.get(), "tags": self.tags.get(),
            "notify_subscribers": self.notify_subscribers.get(),
        }
        temporary = CONFIG_FILE.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(CONFIG_FILE)

    def _setup_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=PANEL, foreground=TEXT, fieldbackground=PANEL,
                        rowheight=31, borderwidth=0, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background=PANEL_2, foreground=TEXT,
                        relief="flat", font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", PURPLE_DARK)], foreground=[("selected", "white")])
        style.configure("TCombobox", fieldbackground=PANEL_2, background=PANEL_2, foreground=TEXT,
                        arrowcolor=TEXT, bordercolor=PANEL_2, lightcolor=PANEL_2, darkcolor=PANEL_2)
        style.configure("Vertical.TScrollbar", background=PANEL_2, troughcolor=BG, arrowcolor=TEXT)

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=24, pady=(20, 12))
        tk.Label(header, text="A-BEATS", bg=BG, fg=TEXT, font=("Segoe UI Black", 25)).pack(side="left")
        tk.Label(header, text="v1.2.0", bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(side="left", padx=(8, 0), pady=(10, 0))
        tk.Label(header, text="BATCH TYPE BEAT PUBLISHER", bg=BG, fg=PURPLE,
                 font=("Segoe UI Semibold", 9)).pack(side="left", padx=(15, 0), pady=(8, 0))
        tk.Label(header, text="DESKTOP EDITION • WINDOWS", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="right", pady=(10, 0))

        top = tk.Frame(self.root, bg=PANEL, highlightbackground="#302440", highlightthickness=1)
        top.pack(fill="x", padx=24, pady=7)
        self._path_row(top, "БИТЫ", self.audio_dir, self._choose_audio, 0)
        self._path_row(top, "ОБЛОЖКИ", self.cover_dir, self._choose_covers, 1)
        self._path_row(top, "ВЫХОДНЫЕ MP4", self.output_dir, self._choose_output, 2)

        settings = tk.Frame(self.root, bg=BG)
        settings.pack(fill="x", padx=24, pady=7)
        left = tk.Frame(settings, bg=PANEL, highlightbackground="#302440", highlightthickness=1)
        left.pack(side="left", fill="both", expand=True, padx=(0, 7))
        right = tk.Frame(settings, bg=PANEL, highlightbackground="#302440", highlightthickness=1)
        right.pack(side="left", fill="both", expand=True, padx=(7, 0))
        self._build_render_settings(left)
        self._build_schedule_settings(right)

        meta = tk.Frame(self.root, bg=PANEL, highlightbackground="#302440", highlightthickness=1)
        meta.pack(fill="x", padx=24, pady=7)
        self._build_metadata(meta)

        table_wrap = tk.Frame(self.root, bg=BG)
        table_wrap.pack(fill="both", expand=True, padx=24, pady=(7, 4))
        table_head = tk.Frame(table_wrap, bg=BG)
        table_head.pack(fill="x", pady=(0, 7))
        tk.Label(table_head, text="ОЧЕРЕДЬ БИТОВ", bg=BG, fg=TEXT,
                 font=("Segoe UI Semibold", 11)).pack(side="left")
        self.counter_label = tk.Label(table_head, text="0 файлов", bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self.counter_label.pack(side="right")
        columns = ("beat", "track", "youtube_title", "cover", "video", "schedule", "status")
        self.tree = ttk.Treeview(table_wrap, columns=columns, show="headings", selectmode="extended")
        self.tree.bind("<Double-1>", self._edit_selected_track_name)
        for key, label in [("beat", "БИТ / ФАЙЛ"), ("track", "НАЗВАНИЕ ТРЕКА"),
                           ("youtube_title", "НАЗВАНИЕ YOUTUBE"), ("cover", "ОБЛОЖКА"),
                           ("video", "MP4"), ("schedule", "ПУБЛИКАЦИЯ"), ("status", "СТАТУС")]:
            self.tree.heading(key, text=label)
        self.tree.column("beat", width=210, minwidth=150, anchor="w")
        self.tree.column("track", width=180, minwidth=130, anchor="w")
        self.tree.column("youtube_title", width=290, minwidth=180, anchor="w")
        self.tree.column("cover", width=170, minwidth=120, anchor="w")
        self.tree.column("video", width=210, minwidth=140, anchor="w")
        self.tree.column("schedule", width=170, minwidth=130, anchor="center")
        self.tree.column("status", width=160, minwidth=130, anchor="center")
        scrollbar = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        xscrollbar = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=xscrollbar.set)
        self.tree.pack(side="top", fill="both", expand=True)
        xscrollbar.pack(side="bottom", fill="x")
        scrollbar.pack(side="right", fill="y")

        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(fill="x", padx=24, pady=(8, 14))
        self._button(bottom, "＋ ДОБАВИТЬ ПАПКИ", self._scan_folders, outline=True).pack(side="left", padx=(0, 8))
        self._button(bottom, "НАЗНАЧИТЬ ОБЛОЖКУ", self._assign_cover, outline=True).pack(side="left", padx=4)
        self._button(bottom, "УДАЛИТЬ ВЫБРАННОЕ", self._remove_selected, outline=True).pack(side="left", padx=4)
        self._button(bottom, "ОЧИСТИТЬ ОЧЕРЕДЬ", self._clear_queue, outline=True).pack(side="left", padx=4)
        self._button(bottom, "① СОЗДАТЬ MP4", self._render_all).pack(side="left", padx=4)
        self._button(bottom, "② ЗАЛИТЬ ЧЕРЕЗ API", self._upload_api).pack(side="left", padx=4)
        self._button(bottom, "ПРОВЕРИТЬ СБОЙ", self._resolve_uncertain_upload, outline=True, small=True).pack(side="left", padx=4)
        self._button(bottom, "ЭКСПОРТ ДЛЯ STUDIO", self._export_manual, outline=True).pack(side="left", padx=4)
        self._button(bottom, "ПОДКЛЮЧИТЬ КАНАЛ", self._connect_channel, outline=True).pack(side="right", padx=(8, 0))
        self._button(bottom, "ОТКРЫТЬ STUDIO", self._open_studio, outline=True).pack(side="right")

        log_frame = tk.Frame(self.root, bg=PANEL, highlightbackground="#302440", highlightthickness=1)
        log_frame.pack(fill="x", padx=24, pady=(0, 16))
        tk.Label(log_frame, text="ЖУРНАЛ", bg=PANEL, fg=PURPLE, font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=12, pady=(7, 0))
        self.log_text = tk.Text(log_frame, height=3, bg=PANEL, fg=MUTED, insertbackground=TEXT,
                                relief="flat", wrap="word", font=("Consolas", 8), state="disabled")
        self.log_text.pack(fill="x", padx=12, pady=(3, 8))
        self._log("A-BEATS запущен. Добавьте папки с аудио и обложками.")

    def _path_row(self, parent, label, variable, command, row):
        frame = tk.Frame(parent, bg=PANEL)
        frame.pack(fill="x", padx=12, pady=(10 if row == 0 else 4, 4 if row < 2 else 10))
        tk.Label(frame, text=label, width=16, anchor="w", bg=PANEL, fg=PURPLE,
                 font=("Segoe UI Semibold", 8)).pack(side="left")
        entry = tk.Entry(frame, textvariable=variable, bg=PANEL_2, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=("Segoe UI", 9))
        entry.pack(side="left", fill="x", expand=True, ipady=6, padx=8)
        self._button(frame, "ВЫБРАТЬ", command, outline=True, small=True).pack(side="right")

    def _section_title(self, parent, title):
        tk.Label(parent, text=title, bg=PANEL, fg=PURPLE, font=("Segoe UI Semibold", 9)).pack(anchor="w", padx=14, pady=(10, 6))

    def _field(self, parent, label, variable, width=20):
        frame = tk.Frame(parent, bg=PANEL)
        frame.pack(side="left", padx=(14, 0), pady=(0, 11))
        tk.Label(frame, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        entry = tk.Entry(frame, textvariable=variable, width=width, bg=PANEL_2, fg=TEXT,
                         insertbackground=TEXT, relief="flat", font=("Segoe UI", 9))
        entry.pack(ipady=5, pady=(3, 0))
        return entry

    def _build_render_settings(self, parent):
        self._section_title(parent, "РЕНДЕР И НАЗВАНИЯ")
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x")
        frame = tk.Frame(row, bg=PANEL)
        frame.pack(side="left", padx=14, pady=(0, 11))
        tk.Label(frame, text="РАЗРЕШЕНИЕ", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        ttk.Combobox(frame, textvariable=self.resolution, values=["1920x1080", "3840x2160"],
                     state="readonly", width=13).pack(pady=(3, 0), ipady=3)
        self._field(row, "АРТИСТ", self.artist, 17)
        self._field(row, "ШАБЛОН НАЗВАНИЯ", self.title_template, 33)
        ff = tk.Frame(row, bg=PANEL)
        ff.pack(side="left", padx=14, pady=(0, 11))
        tk.Label(ff, text="FFMPEG.EXE (НЕОБЯЗАТЕЛЬНО)", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        inner = tk.Frame(ff, bg=PANEL)
        inner.pack(pady=(3, 0))
        tk.Entry(inner, textvariable=self.ffmpeg_path, width=20, bg=PANEL_2, fg=TEXT,
                 insertbackground=TEXT, relief="flat").pack(side="left", ipady=5)
        self._button(inner, "…", self._choose_ffmpeg, outline=True, small=True).pack(side="left", padx=4)
        track_row = tk.Frame(parent, bg=PANEL)
        track_row.pack(fill="x", padx=14, pady=(0, 8))
        self._button(track_row, "НАЙТИ ТРЕКИ АРТИСТА", self._find_artist_tracks, outline=True, small=True).pack(side="left")
        tk.Label(track_row, text="До 200 названий из музыкального каталога Apple распределяются по очереди.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(side="left", padx=9)

    def _build_schedule_settings(self, parent):
        self._section_title(parent, "РАСПИСАНИЕ ПУБЛИКАЦИЙ")
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x")
        self._field(row, "ПЕРВАЯ ПУБЛИКАЦИЯ", self.start_time, 19)
        self._field(row, "ИНТЕРВАЛ, ЧАСЫ", self.interval, 10)
        frame = tk.Frame(row, bg=PANEL)
        frame.pack(side="left", padx=14, pady=(0, 11))
        tk.Label(frame, text="ЧАСОВОЙ ПОЯС", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        box = ttk.Combobox(frame, textvariable=self.timezone_name, width=23,
                           values=["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "Europe/London", "Europe/Berlin", "Europe/Moscow", "Asia/Dubai"],
                           state="normal")
        box.pack(pady=(3, 0), ipady=3)
        hint = tk.Label(parent, text="Дата: YYYY-MM-DD HH:MM  •  Например, 2026-11-08 18:00", bg=PANEL, fg=MUTED,
                        font=("Segoe UI", 8))
        hint.pack(anchor="w", padx=14, pady=(0, 8))

    def _build_metadata(self, parent):
        self._section_title(parent, "ОПИСАНИЕ И ТЕГИ")
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=14, pady=(0, 11))
        desc_frame = tk.Frame(row, bg=PANEL)
        desc_frame.pack(side="left", fill="x", expand=True, padx=(0, 12))
        tk.Label(desc_frame, text="ОПИСАНИЕ (ПОДДЕРЖИВАЕТ {artist} И {beat_name})", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w")
        self.description_box = tk.Text(desc_frame, height=3, bg=PANEL_2, fg=TEXT, insertbackground=TEXT,
                                       relief="flat", wrap="word", font=("Segoe UI", 9))
        self.description_box.pack(fill="x", pady=(3, 0))
        self.description_box.insert("1.0", self.description.get())
        tag_frame = tk.Frame(row, bg=PANEL)
        tag_frame.pack(side="left")
        tk.Label(tag_frame, text="ТЕГИ ЧЕРЕЗ ЗАПЯТУЮ", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        tag_entry = tk.Entry(tag_frame, textvariable=self.tags, width=42, bg=PANEL_2, fg=TEXT,
                             insertbackground=TEXT, relief="flat", font=("Segoe UI", 9))
        tag_entry.pack(pady=(3, 0), ipady=6)
        self._section_title(parent, "YOUTUBE-КАНАЛ")
        channel_row = tk.Frame(parent, bg=PANEL)
        channel_row.pack(fill="x", padx=14, pady=(0, 10))
        self.channel_box = ttk.Combobox(channel_row, textvariable=self.channel_selection, state="readonly", width=46)
        self.channel_box.pack(side="left")
        self._button(channel_row, "ОБНОВИТЬ СПИСОК", self._reload_channels, outline=True, small=True).pack(side="left", padx=8)
        self._button(channel_row, "ОТКЛЮЧИТЬ", self._disconnect_channel, outline=True, small=True).pack(side="left", padx=(0, 8))
        tk.Checkbutton(channel_row, text="Уведомлять подписчиков", variable=self.notify_subscribers,
                       bg=PANEL, fg=TEXT, selectcolor=PANEL_2, activebackground=PANEL,
                       activeforeground=TEXT, font=("Segoe UI", 8)).pack(side="left", padx=4)
        tk.Label(channel_row, text="Подключайте каждый свой канал отдельной OAuth-авторизацией.", bg=PANEL,
                 fg=MUTED, font=("Segoe UI", 8)).pack(side="left", padx=8)

    def _button(self, parent, label, command, outline=False, small=False):
        bg = PANEL_2 if outline else PURPLE_DARK
        fg = TEXT
        button = tk.Button(parent, text=label, command=command, bg=bg, fg=fg,
                           activebackground=PURPLE, activeforeground="white", relief="flat",
                           bd=0, cursor="hand2", font=("Segoe UI Semibold", 8 if small else 9),
                           padx=9 if small else 13, pady=6 if small else 10)
        return button

    def _log(self, message: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        try:
            self.logger.info("%s", message)
        except Exception:
            pass
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _assign_cover(self):
        if self.worker_active:
            messagebox.showinfo("Идёт обработка", "Дождитесь завершения текущей операции.")
            return
        selected = self.tree.selection()
        if len(selected) != 1:
            messagebox.showinfo("Выберите один бит", "Выберите одну строку, которой нужно назначить обложку.")
            return
        index = int(selected[0])
        path = filedialog.askopenfilename(
            title="Выберите обложку для выбранного бита",
            filetypes=[("Изображения", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Все файлы", "*.*")],
        )
        if path and 0 <= index < len(self.items):
            self.items[index].cover_path = path
            self.items[index].status = "Обложка назначена"
            self._save_queue()
            self._refresh_table()
            self._log(f"Для «{self.items[index].beat_name}» назначена обложка {Path(path).name}.")

    def _edit_selected_track_name(self, event=None):
        if self.worker_active:
            return
        selected = self.tree.selection()
        if len(selected) != 1:
            return
        index = int(selected[0])
        if not 0 <= index < len(self.items):
            return
        item = self.items[index]
        value = simpledialog.askstring(
            "Название для Type Beat",
            "Название трека (оно будет использовано в шаблоне):",
            initialvalue=item.track_name or item.beat_name,
            parent=self.root,
        )
        if value is not None and value.strip():
            item.track_name = value.strip()
            item.title = resolve_title(self.title_template.get(), item, self.artist.get())
            item.description = self._expand_description(item)
            self._save_queue()
            self._refresh_table()
            self._log(f"Обновлено название для «{item.beat_name}».")

    def _remove_selected(self):
        if self.worker_active:
            messagebox.showinfo("Идёт обработка", "Дождитесь завершения текущей операции, затем изменяйте очередь.")
            return
        selected = self.tree.selection() if hasattr(self, "tree") else ()
        if not selected:
            messagebox.showinfo("Выбор не сделан", "Выберите одну или несколько строк в очереди.")
            return
        indexes = sorted((int(value) for value in selected), reverse=True)
        has_uploaded = any(self.items[index].uploaded_to for index in indexes if 0 <= index < len(self.items))
        if has_uploaded and not messagebox.askyesno("Удалить задания", "Некоторые задания уже загружены на YouTube. Удаление уберёт только локальные записи; видео на каналах останутся. Продолжить?"):
            return
        for index in indexes:
            if 0 <= index < len(self.items):
                self.items.pop(index)
        self._save_queue()
        self._refresh_table()
        self._log(f"Удалено из очереди: {len(indexes)}.")

    def _clear_queue(self):
        if self.worker_active:
            messagebox.showinfo("Идёт обработка", "Дождитесь завершения текущей операции, затем изменяйте очередь.")
            return
        if not self.items:
            return
        if not messagebox.askyesno("Очистить очередь", "Удалить все локальные задания? Готовые MP4 останутся на диске, а ранее загруженные видео останутся на YouTube."):
            return
        count = len(self.items)
        self.items.clear()
        self._save_queue()
        self._refresh_table()
        self._log(f"Очередь очищена: {count} заданий. Готовые MP4 не удалялись.")

    def _choose_audio(self):
        folder = filedialog.askdirectory(title="Выберите папку с битами")
        if folder:
            self.audio_dir.set(folder)
            if self.cover_dir.get():
                self._scan_folders()

    def _choose_covers(self):
        folder = filedialog.askdirectory(title="Выберите папку с обложками")
        if folder:
            self.cover_dir.set(folder)
            if self.audio_dir.get():
                self._scan_folders()

    def _choose_output(self):
        folder = filedialog.askdirectory(title="Выберите папку для MP4")
        if folder:
            self.output_dir.set(folder)
            self._save_settings()

    def _choose_ffmpeg(self):
        path = filedialog.askopenfilename(title="Выберите ffmpeg.exe", filetypes=[("FFmpeg", "ffmpeg.exe"), ("Все файлы", "*.*")])
        if path:
            self.ffmpeg_path.set(path)
            self._save_settings()

    def _scan_folders(self):
        if self.worker_active:
            messagebox.showinfo("Идёт обработка", "Дождитесь завершения текущей операции, затем импортируйте новые файлы.")
            return
        if not self.audio_dir.get() or not self.cover_dir.get():
            messagebox.showinfo("Папки", "Сначала выберите папку с битами и папку с обложками.")
            return
        try:
            discovered = pair_audio_and_covers(self.audio_dir.get(), self.cover_dir.get())
            existing = {str(Path(item.audio_path).resolve()).casefold(): item for item in self.items}
            added = 0
            for item in discovered:
                key = str(Path(item.audio_path).resolve()).casefold()
                if key in existing:
                    old_item = existing[key]
                    if (not old_item.cover_path or not Path(old_item.cover_path).is_file()) and item.cover_path:
                        old_item.cover_path = item.cover_path
                    continue
                if self.track_names:
                    item.track_name = self.track_names[(len(self.items) + added) % len(self.track_names)]
                item.title = resolve_title(self.title_template.get(), item, self.artist.get())
                item.description = self._expand_description(item)
                item.tags = self.tags.get()
                self.items.append(item)
                existing[key] = item
                added += 1
            self._save_queue()
            self._refresh_table()
            missing = sum(1 for item in self.items if not item.cover_path)
            self._log(f"Найдено файлов: {len(discovered)}; добавлено новых: {added}; всего в очереди: {len(self.items)}. Без однозначной обложки: {missing}.")
            if not discovered:
                messagebox.showwarning("Ничего не найдено", "В выбранной папке не нашлись аудиофайлы поддерживаемых форматов.")
            elif missing:
                messagebox.showwarning("Не все обложки найдены", f"У {missing} битов нет однозначной пары. Проверьте совпадение имён файлов.")
        except Exception as exc:
            messagebox.showerror("Ошибка импорта", str(exc))

    def _expand_description(self, item: BeatItem) -> str:
        template = self.description_box.get("1.0", "end-1c") if hasattr(self, "description_box") else self.description.get()
        return (template.replace("{artist}", self.artist.get().strip())
                .replace("{beat_name}", item.beat_name)
                .replace("{track_name}", item.track_name or item.beat_name))

    def _refresh_table(self):
        for child in self.tree.get_children():
            self.tree.delete(child)
        for idx, item in enumerate(self.items):
            cover = Path(item.cover_path).name if item.cover_path else "НЕ НАЙДЕНА"
            video = Path(item.video_path).name if item.video_path else "—"
            status = item.status
            if item.uncertain_uploads:
                status = "Нужна проверка YouTube"
            elif item.uploaded_to and not status.startswith("Ошибка"):
                status = f"Загружено: {len(item.uploaded_to)} канал(а)"
            schedule = item.scheduled_at or "—"
            self.tree.insert("", "end", iid=str(idx), values=(item.beat_name, item.track_name or "—",
                             item.title or "—", cover, video, schedule, status))
        self.counter_label.configure(text=f"{len(self.items)} файлов • {sum(bool(i.video_path) for i in self.items)} MP4 готово")

    def _save_queue(self) -> bool:
        try:
            with self._queue_lock:
                payload = {"items": [asdict(item) for item in self.items], "track_names": self.track_names}
                temporary = QUEUE_FILE.with_suffix(".json.tmp")
                temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                if QUEUE_FILE.exists():
                    backup = QUEUE_FILE.with_suffix(".json.bak")
                    try:
                        backup.write_bytes(QUEUE_FILE.read_bytes())
                    except OSError:
                        pass
                temporary.replace(QUEUE_FILE)
            return True
        except (OSError, TypeError) as exc:
            if hasattr(self, "events"):
                self.events.put(("log", f"Не удалось сохранить очередь: {exc}"))
            return False

    def _load_queue(self):
        if not QUEUE_FILE.is_file():
            return
        try:
            data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            records = data.get("items", [])
            self.items = [BeatItem(**row) for row in records if isinstance(row, dict) and row.get("audio_path")]
            for item in self.items:
                if item.uncertain_uploads:
                    item.status = "Нужна проверка YouTube"
                elif item.uploaded_to:
                    item.status = f"Загружено: {len(item.uploaded_to)} канал(а)"
                elif item.status in {"Рендеринг", "Загрузка 0%", "Загрузка"}:
                    item.status = "Ожидает проверки рендера"
            self.track_names = [str(name) for name in data.get("track_names", []) if str(name).strip()]
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.items = []
            self.track_names = []
            try:
                damaged = QUEUE_FILE.with_name(f"queue.corrupt.{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
                QUEUE_FILE.replace(damaged)
                self.events.put(("log", f"Файл очереди повреждён; исходник сохранён как {damaged.name}. Причина: {exc}"))
            except OSError:
                self.events.put(("log", f"Не удалось прочитать очередь: {exc}"))

    def _find_artist_tracks(self):
        artist = self.artist.get().strip()
        if not artist:
            messagebox.showinfo("Артист не указан", "Сначала впишите имя артиста.")
            return
        self._log(f"Ищу названия треков артиста «{artist}»…")

        def work():
            try:
                try:
                    from itunes_discography import find_artist_tracks
                except ImportError:
                    from .itunes_discography import find_artist_tracks
                names = find_artist_tracks(artist)
                self.events.put(("track_names", artist, names))
            except Exception as exc:
                self.events.put(("log", f"Не удалось найти дискографию: {exc}"))
                self.events.put(("error_dialog", "Поиск треков", str(exc)))

        self._start_worker(work)

    def _apply_track_names(self, artist: str, names: list[str]):
        self.track_names = list(names)
        for index, item in enumerate(self.items):
            if self.track_names:
                item.track_name = self.track_names[index % len(self.track_names)]
            item.title = resolve_title(self.title_template.get(), item, artist)
        for item in self.items:
            item.description = self._expand_description(item)
        self._save_queue()
        self._refresh_table()
        self._log(f"Найдено {len(names)} уникальных названий. Распределено по битам: {min(len(self.items), len(names))} без повторов до исчерпания списка.")

    def _start_worker(self, task):
        if self.worker_active:
            messagebox.showinfo("Задача уже выполняется", "Дождитесь завершения текущей операции.")
            return False
        self.worker_active = True

        def runner():
            try:
                task()
            except Exception as exc:
                self.events.put(("log", f"Непредвиденная ошибка фоновой задачи: {exc}"))
                self.events.put(("error_dialog", "Ошибка фоновой задачи", str(exc)))
            finally:
                self.events.put(("worker_done",))

        threading.Thread(target=runner, daemon=True, name="ABeatsWorker").start()
        return True

    def _render_all(self):
        if not self.items:
            messagebox.showinfo("Очередь пуста", "Сначала выберите папки и добавьте биты.")
            return
        if any(not item.cover_path for item in self.items):
            messagebox.showerror("Не хватает обложек", "Сначала исправьте пары аудио/обложка. Рендер с пустыми обложками не запускается.")
            return
        self._save_settings()
        resolution = self.resolution.get()
        output_dir = self.output_dir.get()
        ffmpeg_path = self.ffmpeg_path.get()
        items = list(self.items)

        def work():
            success = 0
            for index, item in enumerate(items):
                try:
                    self.events.put(("status", index, "Рендеринг"))
                    output = render_video(item, output_dir, resolution, ffmpeg_path,
                                          progress=lambda msg: self.events.put(("log", msg)))
                    self.events.put(("rendered", index, output))
                    success += 1
                except Exception as exc:
                    self.events.put(("status", index, "Ошибка рендера"))
                    self.events.put(("log", f"Ошибка: {exc}"))
            self.events.put(("log", f"Рендер завершён: {success}/{len(items)}."))
            self.events.put(("finished", "render"))

        self._log("Начинаю рендер очереди…")
        self._start_worker(work)

    def _update_metadata(self):
        for item in self.items:
            item.title = resolve_title(self.title_template.get(), item, self.artist.get())
            item.description = self._expand_description(item)
            item.tags = self.tags.get()
        self._save_queue()

    def _schedule_values(self, *, allow_past_start: bool = False):
        try:
            interval = float(self.interval.get().replace(",", "."))
        except ValueError as exc:
            raise ValueError("Интервал должен быть числом часов, например 24 или 12.") from exc
        return calculate_publish_times(
            self.start_time.get(), interval, len(self.items), self.timezone_name.get().strip(),
            allow_past_start=allow_past_start,
        )

    def _upload_api(self):
        if not self.items:
            messagebox.showinfo("Очередь пуста", "Сначала добавьте биты.")
            return
        if any(not item.video_path or not Path(item.video_path).is_file() for item in self.items):
            messagebox.showwarning("Сначала создайте MP4", "Перед загрузкой нужно успешно отрендерить все видео.")
            return
        self._update_metadata()
        selected = self.channel_selection.get().strip()
        channel = next((c for c in self.channels if f"{c.get('name')} ({c.get('id')})" == selected), None)
        if not channel:
            messagebox.showwarning("Нет канала", "Сначала подключите и выберите YouTube-канал.")
            return
        try:
            selected_channel_id = channel["id"]
            has_prior_uploads = any(selected_channel_id in item.uploaded_to for item in self.items)
            schedules = self._schedule_values(allow_past_start=has_prior_uploads)
        except Exception as exc:
            messagebox.showerror("Ошибка расписания", str(exc))
            return
        uncertain = [item.beat_name for item in self.items if selected_channel_id in item.uncertain_uploads]
        if uncertain:
            preview = "\n".join(f"• {name}" for name in uncertain[:8])
            more = f"\n…и ещё {len(uncertain) - 8}" if len(uncertain) > 8 else ""
            messagebox.showwarning(
                "Нужна проверка YouTube",
                "Для некоторых заданий соединение оборвалось после начала загрузки. Чтобы не создать дубликаты, A-BEATS блокирует повтор.\n\n"
                f"{preview}{more}\n\nОткройте YouTube Studio, проверьте, появились ли видео, выберите задание и нажмите «ПРОВЕРИТЬ СБОЙ»."
            )
            return
        pending_indices = [index for index, item in enumerate(self.items) if selected_channel_id not in item.uploaded_to]
        pending_count = len(pending_indices)
        if pending_count == 0:
            messagebox.showinfo("Очередь уже опубликована", "Все задания из текущей очереди уже отправлены на выбранный канал.")
            return
        now_local = datetime.now(schedules[0].tzinfo)
        if any(schedules[index] <= now_local for index in pending_indices):
            messagebox.showerror("Дата публикации прошла", "У одного или нескольких незагруженных битов время публикации уже прошло. Измени дату первой публикации так, чтобы все оставшиеся даты были в будущем. Уже загруженные видео не изменятся.")
            return
        available_today = quota_remaining(QUOTA_FILE)
        if available_today <= 0:
            messagebox.showwarning("Дневной лимит A-BEATS", f"Локальный защитный лимит {APP_DAILY_UPLOAD_LIMIT} загрузок на сегодня исчерпан. Очередь сохранена; попробуйте после сброса квоты YouTube в полночь по тихоокеанскому времени.")
            return
        first_when = schedules[pending_indices[0]]
        last_when = schedules[pending_indices[-1]]
        quota_note = f"Сегодня доступно не более {available_today} попыток; остаток очереди сохранится." if pending_count > available_today else f"Сегодня доступно {available_today} попыток."
        notify_note = "Уведомления подписчикам включены." if self.notify_subscribers.get() else "Уведомления подписчикам отключены."
        if not messagebox.askyesno(
            "Подтвердить загрузку",
            f"Канал: {channel.get('name')}\nНовых видео: {pending_count}\nПервое: {first_when.strftime('%Y-%m-%d %H:%M %Z')}\nПоследнее: {last_when.strftime('%Y-%m-%d %H:%M %Z')}\n\n{quota_note}\n{notify_note}\n\nВидео загрузятся как приватные с отложенной публикацией. Продолжить?",
        ):
            return
        try:
            try:
                from youtube_api import YouTubeAPI
            except ImportError:
                from .youtube_api import YouTubeAPI
        except ImportError:
            messagebox.showerror("Не установлены библиотеки", "Запустите START_A-BEATS.bat для установки компонентов и перезапустите приложение.")
            return
        self._save_settings()
        items = list(self.items)
        channel_id = channel["id"]
        notify_subscribers = bool(self.notify_subscribers.get())
        youtube = YouTubeAPI(APP_DIR)

        def work():
            completed = 0
            already_done = sum(1 for item in items if channel_id in item.uploaded_to)
            deferred = 0
            for index, (item, when) in enumerate(zip(items, schedules)):
                if channel_id in item.uploaded_to:
                    record = item.uploaded_to[channel_id]
                    self.events.put(("log", f"Пропуск {item.beat_name}: уже загружено на выбранный канал (ID {record.get('video_id', '')})."))
                    continue
                if when <= datetime.now(when.tzinfo):
                    deferred = len(items) - index
                    self.events.put(("log", f"Задание «{item.beat_name}» имеет прошедшее время публикации. Обновите дату первой публикации; видео не отправлено, чтобы оно не вышло немедленно."))
                    break
                if quota_remaining(QUOTA_FILE) <= 0:
                    deferred = len(items) - index
                    self.events.put(("log", f"Достигнут внутренний дневной предел {APP_DAILY_UPLOAD_LIMIT} загрузок. Остальные задания оставлены в очереди до следующего дня."))
                    break
                try:
                    utc_time = when.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
                    self.events.put(("status", index, "Загрузка 0%"))
                    def persist_attempt(beat=item, publish_time=when):
                        # If the process or network fails after this point, never blindly retry:
                        # YouTube may already have accepted the resumable upload.
                        record_attempt(QUOTA_FILE)
                        beat.uncertain_uploads[channel_id] = publish_time.isoformat()
                        beat.status = "Нужна проверка YouTube"
                        if not self._save_queue():
                            raise RuntimeError("Не удалось надёжно сохранить контрольную точку загрузки. Сетевая отправка отменена.")

                    def persist_uploaded(video_id: str, beat=item, row=index, publish_time=when):
                        beat.video_id = video_id
                        beat.channel_id = channel_id
                        beat.scheduled_at = publish_time.isoformat()
                        beat.uploaded_to[channel_id] = {"video_id": video_id, "scheduled_at": publish_time.isoformat()}
                        beat.uncertain_uploads.pop(channel_id, None)
                        beat.status = f"Запланировано • {video_id}"
                        # Persist immediately after YouTube accepts the video, before thumbnail work.
                        self._save_queue()
                        self.events.put(("uploaded", row, channel_id, video_id, publish_time.isoformat()))

                    video_id, thumbnail_note = youtube.upload_scheduled_video(
                        channel_id=channel_id, video_path=item.video_path,
                        title=item.title or item.beat_name, description=item.description,
                        tags=[t.strip() for t in item.tags.split(",") if t.strip()],
                        publish_at_utc=utc_time, thumbnail_path=item.cover_path,
                        notify_subscribers=notify_subscribers,
                        progress=lambda msg, i=index: self.events.put(("log", msg)),
                        on_uploaded=persist_uploaded,
                        before_insert=persist_attempt,
                    )
                    completed += 1
                    self.events.put(("status", index, f"Запланировано • {video_id}"))
                    self.events.put(("log", f"Загружено {item.beat_name}; публикация: {when.strftime('%Y-%m-%d %H:%M %Z')}."))
                    if thumbnail_note:
                        self.events.put(("log", thumbnail_note))
                except Exception as exc:
                    self.events.put(("upload_error", index, str(exc)))
                    self.events.put(("status", index, "Ошибка загрузки"))
                    self.events.put(("log", f"Не удалось загрузить {item.beat_name}: {exc}"))
                    if "quota" in str(exc).lower():
                        self.events.put(("log", "YouTube сообщил об исчерпании квоты. Оставшиеся задания сохранены."))
                        break
            self.events.put(("log", f"Загрузка завершена: новых {completed}; уже на этом канале {already_done}; отложено до следующего дня: {deferred}."))
            self.events.put(("finished", "upload"))

        self._log(f"Запускаю загрузку на канал {channel.get('name')}…")
        self._start_worker(work)

    def _resolve_uncertain_upload(self):
        if self.worker_active:
            messagebox.showinfo("Идёт обработка", "Дождитесь завершения текущей операции.")
            return
        selected = self.tree.selection()
        if len(selected) != 1:
            messagebox.showinfo("Выберите один бит", "Выберите одну строку со статусом «Нужна проверка YouTube».")
            return
        index = int(selected[0])
        if not 0 <= index < len(self.items):
            return
        item = self.items[index]
        channel_label = self.channel_selection.get().strip()
        channel = next((c for c in self.channels if f"{c.get('name')} ({c.get('id')})" == channel_label), None)
        if not channel:
            messagebox.showwarning("Нет канала", "Выберите канал, на котором выполнялась загрузка.")
            return
        channel_id = channel["id"]
        scheduled_at = item.uncertain_uploads.get(channel_id)
        if not scheduled_at:
            messagebox.showinfo("Проверка не требуется", "Для выбранного бита нет незавершённой загрузки на выбранный канал.")
            return
        choice = messagebox.askyesnocancel(
            "Проверка незавершённой загрузки",
            f"Откройте YouTube Studio и проверьте канал «{channel.get('name')}».\n\n"
            f"Бит: {item.beat_name}\nПланировалось: {scheduled_at}\n\n"
            "Да — видео уже появилось в Studio; сохранить его Video ID.\n"
            "Нет — вы проверили Studio и видео точно отсутствует; разрешить повторную загрузку.\n"
            "Отмена — ничего не менять.",
        )
        if choice is None:
            return
        if choice is True:
            video_id = simpledialog.askstring("YouTube Video ID", "Введите ID найденного видео (из URL YouTube):", parent=self.root)
            if not video_id:
                return
            video_id = video_id.strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", video_id):
                messagebox.showerror("Некорректный Video ID", "ID должен содержать 6–64 латинских букв, цифр, дефисов или подчёркиваний.")
                return
            item.video_id = video_id
            item.channel_id = channel_id
            item.scheduled_at = scheduled_at
            item.uploaded_to[channel_id] = {"video_id": video_id, "scheduled_at": scheduled_at}
            item.status = f"Запланировано • {video_id}"
            self._log(f"Загрузка {item.beat_name} подтверждена вручную по Video ID {video_id}.")
        else:
            item.uncertain_uploads.pop(channel_id, None)
            item.status = "Готово к повторной загрузке"
            self._log(f"Повторная загрузка {item.beat_name} разрешена после ручной проверки YouTube Studio.")
        self._save_queue()
        self._refresh_table()

    def _export_manual(self):
        if not self.items:
            messagebox.showinfo("Очередь пуста", "Сначала добавьте биты.")
            return
        self._update_metadata()
        missing = [i.beat_name for i in self.items if not i.video_path or not Path(i.video_path).is_file()]
        if missing:
            messagebox.showwarning("Не все видео готовы", "Сначала создайте MP4 для всех битов.")
            return
        try:
            schedules = self._schedule_values()
        except Exception as exc:
            messagebox.showerror("Ошибка расписания", str(exc))
            return
        path = filedialog.asksaveasfilename(title="Сохранить CSV-манифест", defaultextension=".csv",
                                            initialfile="a_beats_upload_manifest.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            export_manifest(self.items, path, schedules, self.timezone_name.get().strip())
            self._log(f"CSV-манифест сохранён: {path}")
            messagebox.showinfo("Готово", "Манифест сохранён. Откройте YouTube Studio и вручную загрузите подготовленные MP4, используя CSV как список метаданных и дат.")
        except Exception as exc:
            messagebox.showerror("Ошибка экспорта", str(exc))

    def _connect_channel(self):
        path = filedialog.askopenfilename(title="Выберите OAuth client_secret JSON",
                                          filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            try:
                from youtube_api import YouTubeAPI
            except ImportError:
                from .youtube_api import YouTubeAPI
        except ImportError:
            messagebox.showerror("Не установлены библиотеки", "Запустите START_A-BEATS.bat для установки компонентов и перезапустите приложение.")
            return
        youtube = YouTubeAPI(APP_DIR)

        def work():
            try:
                channel = youtube.connect_channel(path, progress=lambda msg: self.events.put(("log", msg)))
                self.events.put(("log", f"Подключён канал: {channel['name']} ({channel['id']})."))
                self.events.put(("channels", None))
            except Exception as exc:
                self.events.put(("log", f"Ошибка подключения канала: {exc}"))
                self.events.put(("error_dialog", "Ошибка OAuth", str(exc)))

        self._log("Подключение YouTube-канала. В браузере войдите в нужный Google-аккаунт…")
        self._start_worker(work)

    def _reload_channels(self):
        try:
            try:
                from youtube_api import YouTubeAPI
            except ImportError:
                from .youtube_api import YouTubeAPI
            self.channels = YouTubeAPI(APP_DIR).list_channels()
        except ImportError:
            self.channels = []
        values = [f"{c.get('name')} ({c.get('id')})" for c in self.channels]
        self.channel_box.configure(values=values)
        if values and self.channel_selection.get() not in values:
            self.channel_selection.set(values[0])
        elif not values:
            self.channel_selection.set("")

    def _disconnect_channel(self):
        selected = self.channel_selection.get().strip()
        channel = next((c for c in self.channels if f"{c.get('name')} ({c.get('id')})" == selected), None)
        if not channel:
            messagebox.showinfo("Канал не выбран", "Выберите подключённый канал в списке.")
            return
        if self.worker_active:
            messagebox.showinfo("Идёт обработка", "Дождитесь завершения текущей операции.")
            return
        if not messagebox.askyesno("Отключить канал", f"Удалить локальную OAuth-сессию канала «{channel.get('name')}»? Уже загруженные видео останутся на YouTube."):
            return
        try:
            from youtube_api import YouTubeAPI
        except ImportError:
            from .youtube_api import YouTubeAPI
        YouTubeAPI(APP_DIR).remove_channel(channel["id"])
        self._reload_channels()
        self._log(f"Отключён канал: {channel.get('name')}.")

    def _open_studio(self):
        webbrowser.open("https://studio.youtube.com/")
        self._log("Открыл YouTube Studio в браузере. Дальнейшие действия выполняются вручную.")

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._log(event[1])
                elif kind == "status":
                    _, index, status = event
                    if 0 <= index < len(self.items):
                        self.items[index].status = status
                        self._refresh_table()
                        self._save_queue()
                elif kind == "rendered":
                    _, index, output = event
                    if 0 <= index < len(self.items):
                        self.items[index].video_path = output
                        self.items[index].status = "MP4 готов"
                        self._refresh_table()
                        self._save_queue()
                elif kind == "uploaded":
                    _, index, channel_id, video_id, scheduled_at = event
                    if 0 <= index < len(self.items):
                        item = self.items[index]
                        item.video_id = video_id
                        item.channel_id = channel_id
                        item.scheduled_at = scheduled_at
                        item.uploaded_to[channel_id] = {"video_id": video_id, "scheduled_at": scheduled_at}
                        item.uncertain_uploads.pop(channel_id, None)
                        item.upload_error = ""
                        self._save_queue()
                elif kind == "upload_error":
                    _, index, error = event
                    if 0 <= index < len(self.items):
                        self.items[index].upload_error = error
                        self._save_queue()
                elif kind == "channels":
                    self._reload_channels()
                elif kind == "track_names":
                    _, artist, names = event
                    self._apply_track_names(artist, names)
                elif kind == "error_dialog":
                    messagebox.showerror(event[1], event[2])
                elif kind == "finished":
                    self._refresh_table()
                elif kind == "worker_done":
                    self.worker_active = False
                    self._refresh_table()
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    def _on_close(self):
        if self.worker_active:
            messagebox.showwarning("Выполняется задача", "Сейчас выполняется рендер или загрузка. Дождитесь завершения, чтобы не потерять состояние очереди и результат загрузки.")
            return
        try:
            self.description.set(self.description_box.get("1.0", "end-1c"))
            self._save_settings()
            self._save_queue()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    ABeatsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
