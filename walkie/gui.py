import logging
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import scrolledtext

import pystray
from PIL import Image, ImageDraw

from .config import get_room_names, get_rooms, get_config

log = logging.getLogger(__name__)

BG_DARK = "#0f0f13"
BG_PANEL = "#1a1a24"
BG_INPUT = "#252535"
BG_SIDEBAR = "#14141e"
BG_HEADER = "#1e1e2e"
FG_TEXT = "#e0e0f0"
FG_DIM = "#6e6e8a"
FG_ACCENT = "#7c6af6"
FG_ACCENT_LIGHT = "#a89aff"
FG_GREEN = "#4ade80"
FG_RED = "#f87171"
FG_ORANGE = "#fbbf24"
BORDER_COLOR = "#2a2a3d"
PTT_IDLE_BG = "#1c2a1c"
PTT_ACTIVE_BG = "#3a1515"
PEER_DOT_ONLINE = "#4ade80"
TAB_ACTIVE_BG = "#252535"
TAB_IDLE_BG = "#16161f"

FONT_FAMILY = "DejaVu Sans"

ROOM_NAMES = get_room_names()


def _font(name="body", size=11, weight="normal"):
    sizes = {"title": 13, "body": 11, "small": 9, "chat": 11, "input": 12, "ptt": 12, "tab": 11, "peer": 11}
    return tkfont.Font(family=FONT_FAMILY, size=sizes.get(name, size), weight=weight)


class StartupDialog(tk.Tk):
    def __init__(self):
        try:
            super().__init__()
            self.title("Walkie-Talkie")
            self.configure(bg=BG_DARK)
            self.resizable(False, False)
            self.result = None

            self.lift()
            self.attributes("-topmost", True)
            self.after(100, lambda: self.attributes("-topmost", False))

            title_font = _font("title", weight="bold")
            label_font = _font("body")
            entry_font = _font("input")

            header = tk.Frame(self, bg=BG_DARK)
            header.pack(fill="x", padx=30, pady=(25, 5))
            tk.Label(header, text="Walkie-Talkie", font=title_font,
                     fg=FG_ACCENT_LIGHT, bg=BG_DARK).pack()

            form = tk.Frame(self, bg=BG_DARK)
            form.pack(fill="x", padx=40, pady=(5, 10))

            tk.Label(form, text="Your Name", font=label_font, fg=FG_DIM,
                     bg=BG_DARK, anchor="w").pack(fill="x")
            self.name_entry = tk.Entry(form, font=entry_font, bg=BG_INPUT, fg=FG_TEXT,
                                       insertbackground=FG_TEXT, relief="flat", bd=0)
            self.name_entry.pack(fill="x", ipady=8, pady=(2, 12))
            self.name_entry.focus_set()

            tk.Label(form, text="Room Selection", font=label_font, fg=FG_DIM,
                     bg=BG_DARK, anchor="w").pack(fill="x", pady=(10, 5))

            rooms = get_rooms()
            cfg = get_config()
            room_passwords = {r["id"]: r.get("password", "") for r in cfg["rooms"]}
            self.room_vars = {}
            self.room_checkbuttons = {}

            for room in rooms:
                rid = room["id"]
                name = room["name"]
                var = tk.BooleanVar(value=True)
                self.room_vars[rid] = var

                cb = tk.Checkbutton(form, text=name, variable=var,
                                    bg=BG_DARK, fg=FG_TEXT, selectcolor=BG_INPUT,
                                    font=label_font, activebackground=BG_DARK,
                                    activeforeground=FG_TEXT)
                cb.pack(anchor="w", pady=2)
                self.room_checkbuttons[rid] = cb

            tk.Frame(form, bg=BG_DARK, height=10).pack()

            self.join_btn = tk.Button(form, text="Join Channel", font=label_font,
                                      bg=FG_ACCENT, fg="white", activebackground=FG_ACCENT_LIGHT,
                                      activeforeground="white", relief="flat", bd=0, cursor="hand2",
                                      command=self._on_join)
            self.join_btn.pack(fill="x", ipady=8, pady=(10, 0))

            self.bind("<Return>", lambda e: self._on_join())
            self.protocol("WM_DELETE_WINDOW", self._on_close)

            self.update_idletasks()
            w = self.winfo_reqwidth()
            h = self.winfo_reqheight()
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 2
            self.geometry(f"{w}x{h}+{x}+{y}")

            log.info("Login dialog shown")
        except Exception as e:
            log.error(f"Login dialog error: {e}", exc_info=True)
            self.result = None

    def _on_join(self):
        try:
            name = self.name_entry.get().strip()
            if not name:
                self.name_entry.config(bg="#3a1515")
                self.after(800, lambda: self.name_entry.config(bg=BG_INPUT))
                return

            rooms = {}
            cfg = get_config()
            room_passwords = {r["id"]: r.get("password", "") for r in cfg["rooms"]}

            for rid, var in self.room_vars.items():
                if var.get():
                    rooms[rid] = room_passwords.get(rid, "")

            if not rooms:
                return

            self.result = (name, rooms)
            log.info(f"User '{name}' joined rooms {list(rooms.keys())}")
            self.quit()
            self.destroy()
        except Exception as e:
            log.error(f"_on_join error: {e}", exc_info=True)

    def _on_close(self):
        self.result = None
        self.quit()
        self.destroy()


class RoomTabBar:
    def __init__(self, parent, rooms, fonts, on_tab_changed):
        self._rooms = rooms
        self._on_tab_changed = on_tab_changed
        self._selected_id = None
        self._tabs = {}

        self.frame = tk.Frame(parent, bg=BG_HEADER, height=40)
        self.frame.pack(fill="x")
        self.frame.pack_propagate(False)

        for room in rooms:
            rid = room["id"]
            name = room["name"]
            btn = tk.Label(self.frame, text=name, font=fonts["tab"],
                           bg=TAB_IDLE_BG, fg=FG_DIM, padx=16, pady=6,
                           cursor="hand2")
            btn.pack(side="left", padx=(1, 0), pady=8)
            btn.bind("<Button-1>", lambda e, r=rid: self.select_room(r))
            btn.bind("<Enter>", lambda e, b=btn: b.configure(fg=FG_TEXT) if b.cget("bg") == TAB_IDLE_BG else None)
            btn.bind("<Leave>", lambda e, b=btn: b.configure(fg=FG_DIM) if b.cget("bg") == TAB_IDLE_BG else None)
            self._tabs[rid] = btn

        if rooms:
            self._selected_id = rooms[0]["id"]
            btn = self._tabs[self._selected_id]
            btn.configure(bg=TAB_ACTIVE_BG, fg=FG_ACCENT_LIGHT)

    def select_room(self, room_id):
        if self._selected_id is not None and self._selected_id in self._tabs:
            old = self._tabs[self._selected_id]
            old.configure(bg=TAB_IDLE_BG, fg=FG_DIM)

        self._selected_id = room_id
        if room_id in self._tabs:
            btn = self._tabs[room_id]
            btn.configure(bg=TAB_ACTIVE_BG, fg=FG_ACCENT_LIGHT)

        if self._on_tab_changed:
            self._on_tab_changed(room_id)

    @property
    def selected_room(self):
        return self._selected_id


class PeerListWidget:
    def __init__(self, parent, username, fonts, on_play_beep=None):
        self.on_play_beep = on_play_beep
        self._root = parent
        self._fonts = fonts
        self._peers_by_ip = {}

        self.frame = tk.Frame(parent, bg=BG_SIDEBAR, width=220)
        self.frame.pack(side="left", fill="y")
        self.frame.pack_propagate(False)

        header = tk.Frame(self.frame, bg=BG_HEADER, height=44)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="Online Peers", font=fonts["title"],
                 fg=FG_ACCENT_LIGHT, bg=BG_HEADER).pack(side="left", padx=15, pady=8)

        tk.Frame(self.frame, bg=BORDER_COLOR, height=1).pack(fill="x")

        scrollable = tk.Frame(self.frame, bg=BG_SIDEBAR)
        scrollable.pack(fill="both", expand=True, padx=10, pady=10)

        you_frame = tk.Frame(scrollable, bg=BG_SIDEBAR)
        you_frame.pack(fill="x", pady=(0, 8))
        tk.Label(you_frame, text="+", font=("DejaVu Sans", 8), fg=FG_GREEN, bg=BG_SIDEBAR).pack(side="left", padx=(5, 8))
        tk.Label(you_frame, text=f"{username} (You)", font=fonts["peer"], fg=FG_TEXT, bg=BG_SIDEBAR).pack(side="left")

        tk.Frame(scrollable, bg=BORDER_COLOR, height=1).pack(fill="x", pady=5)

        self.widgets_frame = tk.Frame(scrollable, bg=BG_SIDEBAR)
        self.widgets_frame.pack(fill="both", expand=True)

        self.no_peers_label = tk.Label(self.widgets_frame, text="Searching for peers...",
                                       font=fonts["small"], fg=FG_DIM, bg=BG_SIDEBAR)
        self.no_peers_label.pack(pady=20)

    def update(self, peers):
        new_ips = {ip for _, ip in peers}

        for ip in set(self._peers_by_ip) - new_ips:
            self._peers_by_ip[ip].destroy()
            del self._peers_by_ip[ip]

        for name, ip in peers:
            if ip in self._peers_by_ip:
                continue
            row = tk.Frame(self.widgets_frame, bg=BG_SIDEBAR)
            row.pack(fill="x", pady=2)
            tk.Label(row, text="+", font=("DejaVu Sans", 8), fg=PEER_DOT_ONLINE, bg=BG_SIDEBAR).pack(side="left", padx=(5, 8))
            tk.Label(row, text=name, font=self._fonts["peer"], fg=FG_TEXT, bg=BG_SIDEBAR).pack(side="left")
            tk.Label(row, text=ip, font=self._fonts["small"], fg=FG_DIM, bg=BG_SIDEBAR).pack(side="right", padx=5)
            self._peers_by_ip[ip] = row

            if self.on_play_beep:
                self.on_play_beep(880, 50)
                self._root.after(100, lambda: self.on_play_beep(1046, 50))

        if not peers and not self._peers_by_ip:
            tk.Label(self.widgets_frame, text="No peers found yet...",
                     font=self._fonts["small"], fg=FG_DIM, bg=BG_SIDEBAR).pack(pady=20)

        log.debug(f"Peer list: {len(peers)} peers")


class ChatWidget:
    def __init__(self, parent, fonts, on_send=None):
        self.on_send = on_send
        self._fonts = fonts
        self._is_closing = False
        self._messages = {}
        self._selected_room = None

        self.frame = tk.Frame(parent, bg=BG_DARK)
        self.frame.pack(side="left", fill="both", expand=True)

        header = tk.Frame(self.frame, bg=BG_HEADER, height=44)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="Chat", font=fonts["title"],
                 fg=FG_ACCENT_LIGHT, bg=BG_HEADER).pack(side="left", padx=15, pady=8)

        self._room_label = tk.Label(header, text="", font=fonts["small"],
                                    fg=FG_DIM, bg=BG_HEADER)
        self._room_label.pack(side="right", padx=15, pady=8)

        tk.Frame(self.frame, bg=BORDER_COLOR, height=1).pack(fill="x")

        self.chat_area = scrolledtext.ScrolledText(
            self.frame, font=fonts["chat"], bg=BG_PANEL, fg=FG_TEXT,
            relief="flat", bd=0, wrap="word", state="disabled",
            insertbackground=FG_TEXT, selectbackground=FG_ACCENT,
            padx=15, pady=10, spacing1=4
        )
        self.chat_area.pack(fill="both", expand=True)

        self.chat_area.tag_configure("time", foreground=FG_DIM, font=(FONT_FAMILY, 9))
        self.chat_area.tag_configure("channel", foreground=FG_ACCENT, font=(FONT_FAMILY, 9, "bold"))
        self.chat_area.tag_configure("self", foreground=FG_ACCENT_LIGHT, font=(FONT_FAMILY, 10, "bold"))
        self.chat_area.tag_configure("other", foreground=FG_GREEN, font=(FONT_FAMILY, 10, "bold"))
        self.chat_area.tag_configure("text", foreground=FG_TEXT, font=(FONT_FAMILY, 11))
        self.chat_area.tag_configure("system", foreground=FG_ORANGE, font=(FONT_FAMILY, 10, "italic"))

        tk.Frame(self.frame, bg=BORDER_COLOR, height=1).pack(fill="x")

        input_frame = tk.Frame(self.frame, bg=BG_INPUT, height=80)
        input_frame.pack(fill="x")
        input_frame.pack_propagate(False)

        self.chat_input = tk.Text(input_frame, font=fonts["input"], bg=BG_INPUT, fg=FG_TEXT,
                                  insertbackground=FG_TEXT, relief="flat", bd=0,
                                  height=1, wrap="word", undo=True)
        self.chat_input.pack(side="left", fill="both", expand=True, padx=15, pady=8)
        self.chat_input.bind("<Return>", self._on_enter)
        self.chat_input.bind("<Shift-Return>", lambda e: None)

        send_btn = tk.Button(input_frame, text="Send", font=fonts["body"],
                             bg=FG_ACCENT, fg="white", activebackground=FG_ACCENT_LIGHT,
                             relief="flat", bd=0, cursor="hand2", padx=20,
                             command=self._do_send)
        send_btn.pack(side="right", padx=(0, 10), pady=8)

    def set_selected_room(self, room_id):
        self._selected_room = room_id
        r_name = ROOM_NAMES.get(room_id, str(room_id))
        self._room_label.configure(text=r_name)
        self._redraw()

    def _on_enter(self, event):
        if event.state & 0x1:
            return
        self._do_send()
        return "break"

    def _do_send(self):
        text = self.chat_input.get("1.0", "end").strip()
        if not text:
            return
        self.chat_input.delete("1.0", "end")
        if self.on_send:
            self.on_send(text)

    def add_message(self, sender, message, is_self=False, room_id=0):
        if self._is_closing:
            return
        t_str = time.strftime("%H:%M")
        if room_id not in self._messages:
            self._messages[room_id] = []
        self._messages[room_id].append((t_str, sender, message, is_self))

        if room_id == self._selected_room:
            self._append_line(t_str, sender, message, is_self, room_id)

    def _append_line(self, t_str, sender, message, is_self, room_id):
        area = self.chat_area

        def _update():
            try:
                if self._is_closing or not area.winfo_exists():
                    return
                area.config(state="normal")
                area.insert("end", f"[{t_str}] ", "time")
                r_name = ROOM_NAMES.get(room_id, str(room_id))
                area.insert("end", f"[{r_name}] ", "channel")
                name_tag = "self" if is_self else "other"
                area.insert("end", f"{sender}: ", name_tag)
                area.insert("end", f"{message}\n", "text")
                area.config(state="disabled")
                area.see("end")
            except tk.TclError:
                pass

        self._root.after(0, _update)

    def _redraw(self):
        area = self.chat_area

        def _update():
            try:
                if self._is_closing or not area.winfo_exists():
                    return
                area.config(state="normal")
                area.delete("1.0", "end")
                messages = self._messages.get(self._selected_room, [])
                for t_str, sender, message, is_self in messages:
                    area.insert("end", f"[{t_str}] ", "time")
                    r_name = ROOM_NAMES.get(self._selected_room, str(self._selected_room))
                    area.insert("end", f"[{r_name}] ", "channel")
                    name_tag = "self" if is_self else "other"
                    area.insert("end", f"{sender}: ", name_tag)
                    area.insert("end", f"{message}\n", "text")
                area.config(state="disabled")
                area.see("end")
            except tk.TclError:
                pass

        self._root.after(0, _update)

    def add_system(self, message):
        if self._is_closing:
            return
        area = self.chat_area

        def _update():
            try:
                if self._is_closing or not area.winfo_exists():
                    return
                area.config(state="normal")
                area.insert("end", f"\n[SYSTEM] {message}\n", "system")
                area.config(state="disabled")
                area.see("end")
            except tk.TclError:
                pass

        self._root.after(0, _update)

    @property
    def _root(self):
        return self.frame.winfo_toplevel()


class PTTManager:
    def __init__(self, parent, fonts, rooms,
                 on_ptt_start=None, on_ptt_stop=None,
                 on_vad_toggled=None, on_play_beep=None):
        self._fonts = fonts
        self._rooms = rooms
        self._enabled_rooms = set(rooms)
        self.on_ptt_start = on_ptt_start
        self.on_ptt_stop = on_ptt_stop
        self.on_vad_toggled = on_vad_toggled
        self.on_play_beep = on_play_beep

        self._ptt_active = False
        self._shift_held = False
        self.vad_state = False
        self.on_rooms_toggled = None

        self.frame = tk.Frame(parent, bg=PTT_IDLE_BG, height=44)
        self.frame.pack(fill="x")
        self.frame.pack_propagate(False)

        self.indicator = tk.Label(self.frame, text="+", font=(FONT_FAMILY, 14),
                                  fg=FG_GREEN, bg=PTT_IDLE_BG)
        self.indicator.pack(side="left", padx=(15, 5), pady=6)

        self.label = tk.Label(self.frame,
                              text="Hold Shift + V to talk",
                              font=fonts["ptt"], fg=FG_GREEN, bg=PTT_IDLE_BG)
        self.label.pack(side="left", padx=5, pady=6)

        self._room_toggles = {}
        sep = tk.Frame(self.frame, bg=BORDER_COLOR, width=1)
        sep.pack(side="left", fill="y", padx=10, pady=6)
        for rid in rooms:
            name = ROOM_NAMES.get(rid, str(rid))
            var = tk.BooleanVar(value=True)
            cb = tk.Checkbutton(self.frame, text=name, variable=var,
                                font=fonts["small"], bg=PTT_IDLE_BG, fg=FG_DIM,
                                selectcolor=BG_INPUT, activebackground=PTT_IDLE_BG,
                                activeforeground=FG_TEXT, cursor="hand2",
                                command=lambda r=rid, v=var: self._on_toggle(r, v.get()))
            cb.pack(side="left", padx=4, pady=6)
            self._room_toggles[rid] = (cb, var)

        self.vad_btn = tk.Button(self.frame, text="VAD", font=fonts["small"],
                                 fg=FG_DIM, bg=BG_DARK, activebackground=BG_INPUT,
                                 activeforeground=FG_TEXT, relief="flat", cursor="hand2",
                                 command=self._on_vad_toggle, padx=10, pady=4)
        self.vad_btn.pack(side="right", padx=(5, 15), pady=6)

    def bind_keys(self, root):
        root.bind("<KeyPress>", self._on_key_press)
        root.bind("<KeyRelease>", self._on_key_release)

    def _on_key_press(self, event):
        try:
            if event.keysym in ("Shift_L", "Shift_R"):
                self._shift_held = True
            if event.keysym.lower() == "v" and self._shift_held:
                if not self._ptt_active:
                    self._ptt_active = True
                    self._set_active(True)
                    if self.on_play_beep:
                        self.on_play_beep(880, 50)
                    if self.on_ptt_start:
                        self.on_ptt_start(self._enabled_rooms)
        except Exception as e:
            log.error(f"key_press: {e}", exc_info=True)

    def _on_key_release(self, event):
        try:
            if event.keysym in ("Shift_L", "Shift_R"):
                self._shift_held = False
                if self._ptt_active:
                    self._ptt_active = False
                    self._set_active(False)
                    if self.on_play_beep:
                        self.on_play_beep(659, 50)
                    if self.on_ptt_stop:
                        self.on_ptt_stop()
            if event.keysym.lower() == "v":
                if self._ptt_active:
                    self._ptt_active = False
                    self._set_active(False)
                    if self.on_play_beep:
                        self.on_play_beep(659, 50)
                    if self.on_ptt_stop:
                        self.on_ptt_stop()
        except Exception as e:
            log.error(f"key_release: {e}", exc_info=True)

    def _set_active(self, active, override_text=None):
        try:
            bg = PTT_ACTIVE_BG if active else PTT_IDLE_BG
            fg = FG_RED if active else FG_GREEN
            indicator_text = "*" if active else "+"

            self.frame.configure(bg=bg)
            self.indicator.configure(fg=fg, bg=bg, text=indicator_text)
            txt = override_text or f"Speaking to {', '.join(ROOM_NAMES.get(r, str(r)) for r in sorted(self._enabled_rooms))}" if active else "Hold  Shift + V  to talk"
            self.label.configure(text=txt, fg=fg, bg=bg)

            for rid, (cb, var) in self._room_toggles.items():
                cb.configure(bg=bg)

            self.vad_btn.configure(bg=BG_DARK if not active else PTT_ACTIVE_BG)
        except Exception as e:
            log.error(f"ptt_state: {e}", exc_info=True)

    def _on_vad_toggle(self):
        self.vad_state = not self.vad_state
        if self.vad_state:
            self.vad_btn.config(text="VAD On", fg=FG_GREEN, bg=BG_SIDEBAR)
            self._set_active(True, override_text="Voice activation active...")
        else:
            self.vad_btn.config(text="VAD", fg=FG_DIM, bg=BG_DARK)
            self._set_active(False)
        if self.on_vad_toggled:
            self.on_vad_toggled(self.vad_state, self._enabled_rooms)

    def _on_toggle(self, room_id, enabled):
        if enabled:
            self._enabled_rooms.add(room_id)
        else:
            self._enabled_rooms.discard(room_id)
        log.info(f"Room {ROOM_NAMES.get(room_id)} {'enabled' if enabled else 'disabled'}")
        if self.on_rooms_toggled:
            self.on_rooms_toggled(self._enabled_rooms)

    def toggle_room(self, rid, enabled):
        if enabled:
            self._enabled_rooms.add(rid)
        else:
            self._enabled_rooms.discard(rid)
        if rid in self._room_toggles:
            cb, var = self._room_toggles[rid]
            var.set(enabled)
        if self.on_rooms_toggled:
            self.on_rooms_toggled(self._enabled_rooms)

    @property
    def enabled_rooms(self):
        return self._enabled_rooms


class TrayManager:
    def __init__(self, root, on_quit):
        self._root = root
        self._on_quit = on_quit
        self._icon = None

    def create_image(self):
        image = Image.new("RGB", (64, 64), color=(26, 26, 36))
        dc = ImageDraw.Draw(image)
        dc.line((32, 10, 32, 40), fill=FG_ACCENT, width=4)
        dc.rectangle((20, 30, 44, 60), fill=FG_TEXT)
        dc.rectangle((24, 34, 40, 44), fill=BG_DARK)
        return image

    def go_to_tray(self):
        self._root.withdraw()
        image = self.create_image()
        menu = pystray.Menu(
            pystray.MenuItem("Show", self._show_window, default=True),
            pystray.MenuItem("Quit", self._quit)
        )
        self._icon = pystray.Icon("walkie_talkie", image, "Walkie-Talkie LAN", menu=menu)
        threading.Thread(target=self._icon.run, daemon=True).start()
        log.info("Application minimized to system tray")

    def _show_window(self, icon=None, item=None):
        if icon:
            icon.stop()
        self._root.after(0, self._root.deiconify)

    def _quit(self, icon=None, item=None):
        if icon:
            icon.stop()
        self._root.after(0, self._on_quit)

    def show_close_dialog(self, on_minimize, on_quit):
        dialog = tk.Toplevel(self._root)
        dialog.title("Exit")
        dialog.configure(bg=BG_DARK)
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.focus_force()

        dialog.update_idletasks()
        dw, dh = 340, 180
        rx = self._root.winfo_x() + (self._root.winfo_width() - dw) // 2
        ry = self._root.winfo_y() + (self._root.winfo_height() - dh) // 2
        dialog.geometry(f"{dw}x{dh}+{rx}+{ry}")

        tk.Label(dialog, text="What would you like to do?",
                 font=_font("title", weight="bold"),
                 fg=FG_TEXT, bg=BG_DARK).pack(pady=(24, 6))

        tk.Label(dialog, text="The app can continue running in the background.",
                 font=_font("small"),
                 fg=FG_DIM, bg=BG_DARK).pack(pady=(0, 18))

        btn_frame = tk.Frame(dialog, bg=BG_DARK)
        btn_frame.pack(fill="x", padx=24)

        def minimize():
            dialog.destroy()
            on_minimize()

        def quit_app():
            dialog.destroy()
            on_quit()

        tk.Button(btn_frame, text="Minimize to Tray",
                  font=_font("body"),
                  bg=BG_INPUT, fg=FG_TEXT, activebackground=BG_PANEL,
                  activeforeground=FG_TEXT, relief="flat", cursor="hand2",
                  command=minimize, padx=12, pady=8).pack(side="left", expand=True, fill="x", padx=(0, 6))

        tk.Button(btn_frame, text="Quit",
                  font=_font("body"),
                  bg=FG_RED, fg="white", activebackground="#e05555",
                  activeforeground="white", relief="flat", cursor="hand2",
                  command=quit_app, padx=12, pady=8).pack(side="left", expand=True, fill="x", padx=(6, 0))

        dialog.bind("<Escape>", lambda e: dialog.destroy())


class WalkieTalkieGUI:
    def __init__(self, username, active_rooms, on_send_chat=None,
                 on_ptt_start=None, on_ptt_stop=None,
                 on_rooms_toggled=None, on_vad_toggled=None, on_play_beep=None,
                 on_close=None):
        try:
            self.username = username
            self.active_rooms = active_rooms
            self.on_send_chat = on_send_chat
            self.on_close = on_close
            self._is_closing = False

            self.root = tk.Tk()
            self.root.title(f"Walkie-Talkie - {username}")
            self.root.configure(bg=BG_DARK)
            self.root.minsize(800, 550)

            try:
                self.root.state("zoomed")
            except tk.TclError:
                self.root.attributes("-zoomed", True)

            self._fonts = {
                "title": _font("title", weight="bold"),
                "body": _font("body"),
                "small": _font("small"),
                "chat": _font("chat"),
                "input": _font("input"),
                "ptt": _font("ptt", weight="bold"),
                "peer": _font("peer"),
                "tab": _font("tab", weight="bold"),
            }

            main = tk.Frame(self.root, bg=BG_DARK)
            main.pack(fill="both", expand=True)

            self._peer_list = PeerListWidget(main, username, self._fonts, on_play_beep=on_play_beep)

            tk.Frame(main, bg=BORDER_COLOR, width=1).pack(side="left", fill="y")

            right = tk.Frame(main, bg=BG_DARK)
            right.pack(side="left", fill="both", expand=True)

            self._room_tabs = RoomTabBar(right, get_rooms(), self._fonts, self._on_room_changed)

            tk.Frame(right, bg=BORDER_COLOR, height=1).pack(fill="x")

            self._ptt = PTTManager(right, self._fonts, active_rooms,
                                   on_ptt_start=on_ptt_start,
                                   on_ptt_stop=on_ptt_stop,
                                   on_vad_toggled=on_vad_toggled,
                                   on_play_beep=on_play_beep)
            self._ptt.on_rooms_toggled = on_rooms_toggled

            self._chat = ChatWidget(right, self._fonts, on_send=self._on_send_message)
            self._chat._is_closing = self._is_closing

            if active_rooms:
                self._on_room_changed(self._room_tabs.selected_room)

            self._tray = TrayManager(self.root, self._do_close)

            self.root.protocol("WM_DELETE_WINDOW", self._on_window_closing)
            self.root.update_idletasks()
            log.info(f"GUI started for user '{username}'")
        except Exception as e:
            log.error(f"Failed to start GUI: {e}", exc_info=True)
            raise

    def _on_room_changed(self, room_id):
        self._chat.set_selected_room(room_id)

    def _on_send_message(self, text):
        try:
            if not text:
                return
            room_id = self._room_tabs.selected_room
            if room_id is None:
                room_id = 0
            self.add_chat_message(self.username, text, is_self=True, room_id=room_id)
            if self.on_send_chat:
                self.on_send_chat(text, room_id)
        except Exception as e:
            log.error(f"send_message: {e}", exc_info=True)

    def update_peers(self, peers):
        if self._is_closing:
            return

        def _update():
            try:
                if self._is_closing or not self.root.winfo_exists():
                    return
                self._peer_list.update(peers)
            except Exception as e:
                log.error(f"update_peers: {e}", exc_info=True)

        self.root.after(0, _update)

    def append_chat(self, sender, message, room_id, is_self=False):
        self.add_chat_message(sender, message, is_self=is_self, room_id=room_id)

    def add_chat_message(self, sender, message, is_self=False, room_id=0):
        if self._is_closing:
            return
        self._chat._is_closing = False
        self._chat.add_message(sender, message, is_self=is_self, room_id=room_id)

    def add_system_message(self, message):
        if self._is_closing:
            return
        self._chat.add_system(message)

    def _on_window_closing(self):
        if self._is_closing:
            return
        self._tray.show_close_dialog(
            on_minimize=self._tray.go_to_tray,
            on_quit=self._do_close
        )

    def _do_close(self):
        self._is_closing = True
        self._chat._is_closing = True
        try:
            if self.on_close:
                self.on_close()
            if self.root.winfo_exists():
                self.root.destroy()
        except Exception as e:
            log.error(f"close: {e}", exc_info=True)

    def mainloop(self):
        try:
            self.root.mainloop()
        except Exception as e:
            log.error(f"mainloop: {e}", exc_info=True)
