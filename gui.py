"""
Walkie-Talkie uygulaması için arayüz.
"""

import tkinter as tk
from tkinter import scrolledtext, font as tkfont
import time
import threading
import logging

import pystray
from PIL import Image, ImageDraw

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


class StartupDialog(tk.Tk):
    def __init__(self):
        try:
            super().__init__()
            self.title("Walkie-Talkie · Bağlan")
            self.configure(bg=BG_DARK)
            self.resizable(False, False)
            self.result = None

            self.lift()
            self.attributes("-topmost", True)
            self.after(100, lambda: self.attributes("-topmost", False))

            title_font = tkfont.Font(family="Segoe UI", size=18, weight="bold")
            label_font = tkfont.Font(family="Segoe UI", size=11)
            entry_font = tkfont.Font(family="Segoe UI", size=12)

            header = tk.Frame(self, bg=BG_DARK)
            header.pack(fill="x", padx=30, pady=(25, 5))
            tk.Label(header, text="📻", font=("Segoe UI Emoji", 32), bg=BG_DARK).pack()
            tk.Label(header, text="Walkie-Talkie", font=title_font,
                     fg=FG_ACCENT_LIGHT, bg=BG_DARK).pack()

            form = tk.Frame(self, bg=BG_DARK)
            form.pack(fill="x", padx=40, pady=(5, 10))

            tk.Label(form, text="Adınız", font=label_font, fg=FG_DIM,
                     bg=BG_DARK, anchor="w").pack(fill="x")
            self.name_entry = tk.Entry(form, font=entry_font, bg=BG_INPUT, fg=FG_TEXT,
                                       insertbackground=FG_TEXT, relief="flat", bd=0)
            self.name_entry.pack(fill="x", ipady=8, pady=(2, 12))
            self.name_entry.focus_set()

            tk.Label(form, text="Oda Seçimi", font=label_font, fg=FG_DIM,
                     bg=BG_DARK, anchor="w").pack(fill="x", pady=(10, 5))

            self.var_genel = tk.BooleanVar(value=True)
            self.var_ogretmenler = tk.BooleanVar(value=False)
            self.var_thinktank = tk.BooleanVar(value=False)

            tk.Checkbutton(form, text="Genel (Şifresiz)", variable=self.var_genel,
                           bg=BG_DARK, fg=FG_TEXT, selectcolor=BG_INPUT, font=label_font,
                           activebackground=BG_DARK, activeforeground=FG_TEXT).pack(anchor="w", pady=2)
            tk.Checkbutton(form, text="Öğretmenler Arası", variable=self.var_ogretmenler,
                           bg=BG_DARK, fg=FG_TEXT, selectcolor=BG_INPUT, font=label_font,
                           activebackground=BG_DARK, activeforeground=FG_TEXT).pack(anchor="w", pady=2)
            tk.Checkbutton(form, text="ThinkTank", variable=self.var_thinktank,
                           bg=BG_DARK, fg=FG_TEXT, selectcolor=BG_INPUT, font=label_font,
                           activebackground=BG_DARK, activeforeground=FG_TEXT).pack(anchor="w", pady=2)

            tk.Frame(form, bg=BG_DARK, height=8).pack()
            tk.Label(form, text="Öğretmenler Arası / ThinkTank şifresi:",
                     font=label_font, fg=FG_DIM, bg=BG_DARK, anchor="w").pack(fill="x")
            self.pass_entry = tk.Entry(form, font=entry_font, bg=BG_INPUT, fg=FG_TEXT,
                                       insertbackground=FG_TEXT, relief="flat", bd=0, show="•")
            self.pass_entry.pack(fill="x", ipady=8, pady=(2, 12))

            tk.Frame(form, bg=BG_DARK, height=10).pack()

            self.join_btn = tk.Button(form, text="Kanala Katıl", font=label_font,
                                      bg=FG_ACCENT, fg="white", activebackground=FG_ACCENT_LIGHT,
                                      activeforeground="white", relief="flat", bd=0, cursor="hand2",
                                      command=self._on_join)
            self.join_btn.pack(fill="x", ipady=8, pady=(10, 0))

            self.bind("<Return>", lambda e: self._on_join())
            self.protocol("WM_DELETE_WINDOW", self._on_close)

            # İçerik yerleştikten sonra gerçek boyutu hesapla ve ortala
            self.update_idletasks()
            w = self.winfo_reqwidth()
            h = self.winfo_reqheight()
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 2
            self.geometry(f"{w}x{h}+{x}+{y}")

            log.info("Giriş penceresi gösterildi")
        except Exception as e:
            log.error(f"Giriş penceresi hatası: {e}", exc_info=True)
            self.result = None

    # Geçerli şifre — sadece bu kabul edilir
    _CORRECT_PASSWORD = "fatih"

    def _on_join(self):
        try:
            name = self.name_entry.get().strip()
            if not name:
                self.name_entry.config(bg="#3a1515")
                self.after(800, lambda: self.name_entry.config(bg=BG_INPUT))
                return

            needs_password = self.var_ogretmenler.get() or self.var_thinktank.get()
            passphrase = self.pass_entry.get().strip()

            if needs_password:
                if passphrase != self._CORRECT_PASSWORD:
                    # Yanlış veya boş şifre — kutuyu kırmızı yap
                    self.pass_entry.config(bg="#3a1515")
                    self.after(800, lambda: self.pass_entry.config(bg=BG_INPUT))
                    log.warning("Yanlış şifre girildi")
                    return

            rooms = {}
            if self.var_genel.get():
                rooms[0] = ""
            if self.var_ogretmenler.get():
                rooms[1] = passphrase
            if self.var_thinktank.get():
                rooms[2] = passphrase

            if not rooms:
                return

            self.result = (name, rooms)
            log.info(f"Kullanıcı '{name}' {list(rooms.keys())} odalarına katıldı")
            self.quit()
            self.destroy()
        except Exception as e:
            log.error(f"_on_join hatası: {e}", exc_info=True)

    def _on_close(self):
        self.result = None
        self.quit()
        self.destroy()


from tkinter import ttk

ROOM_NAMES = {
    0: "Genel",
    1: "Öğretmenler Arası",
    2: "ThinkTank"
}


class WalkieTalkieGUI:
    def __init__(self, username: str, active_rooms: list, on_send_chat=None,
                 on_ptt_start=None, on_ptt_stop=None, on_channel_changed=None,
                 on_vad_toggled=None, on_play_beep=None, on_close=None):
        try:
            self.username = username
            self.active_rooms = active_rooms
            self.current_room_id = active_rooms[0] if active_rooms else 0
            self.on_send_chat = on_send_chat
            self.on_ptt_start = on_ptt_start
            self.on_ptt_stop = on_ptt_stop
            self.on_channel_changed = on_channel_changed
            self.on_vad_toggled = on_vad_toggled
            self.on_play_beep = on_play_beep
            self.on_close = on_close

            self._ptt_active = False
            self._shift_held = False
            self._v_held = False
            self._is_closing = False
            self.tray_icon = None
            self.vad_state = False

            self.root = tk.Tk()
            self.root.title(f"Walkie-Talkie · {username}")
            self.root.configure(bg=BG_DARK)
            self.root.minsize(800, 550)

            # Ekran boyutuna göre başlat — maximize en güvenli
            self.root.state('zoomed')

            self.font_title = tkfont.Font(family="Segoe UI", size=13, weight="bold")
            self.font_body = tkfont.Font(family="Segoe UI", size=11)
            self.font_small = tkfont.Font(family="Segoe UI", size=9)
            self.font_chat = tkfont.Font(family="Segoe UI", size=11)
            self.font_input = tkfont.Font(family="Segoe UI", size=12)
            self.font_ptt = tkfont.Font(family="Segoe UI", size=12, weight="bold")
            self.font_peer = tkfont.Font(family="Segoe UI", size=11)

            self._build_layout()
            self._bind_keys()
            self.root.protocol("WM_DELETE_WINDOW", self._on_window_closing)
            # Pencere gerçek boyutuyla ortala
            self.root.update_idletasks()
            log.info(f"Arayüz '{username}' için başlatıldı")
        except Exception as e:
            log.error(f"Arayüz başlatılamadı: {e}", exc_info=True)
            raise

    def _build_layout(self):
        main = tk.Frame(self.root, bg=BG_DARK)
        main.pack(fill="both", expand=True)

        # Sol kenar çubuğu
        sidebar = tk.Frame(main, bg=BG_SIDEBAR, width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        sb_header = tk.Frame(sidebar, bg=BG_HEADER, height=56)
        sb_header.pack(fill="x")
        sb_header.pack_propagate(False)
        tk.Label(sb_header, text="📡  Çevrimiçi Eşler", font=self.font_title,
                 fg=FG_ACCENT_LIGHT, bg=BG_HEADER).pack(side="left", padx=15, pady=12)

        tk.Frame(sidebar, bg=BORDER_COLOR, height=1).pack(fill="x")

        self.peers_frame = tk.Frame(sidebar, bg=BG_SIDEBAR)
        self.peers_frame.pack(fill="both", expand=True, padx=10, pady=10)

        you_frame = tk.Frame(self.peers_frame, bg=BG_SIDEBAR)
        you_frame.pack(fill="x", pady=(0, 8))
        tk.Label(you_frame, text="●", font=("Segoe UI", 8), fg=FG_GREEN, bg=BG_SIDEBAR).pack(side="left", padx=(5, 8))
        tk.Label(you_frame, text=f"{self.username} (Sen)", font=self.font_peer, fg=FG_TEXT, bg=BG_SIDEBAR).pack(side="left")

        tk.Frame(self.peers_frame, bg=BORDER_COLOR, height=1).pack(fill="x", pady=5)

        self.peer_widgets_frame = tk.Frame(self.peers_frame, bg=BG_SIDEBAR)
        self.peer_widgets_frame.pack(fill="both", expand=True)

        self.no_peers_label = tk.Label(self.peer_widgets_frame, text="Eşler aranıyor…",
                                       font=self.font_small, fg=FG_DIM, bg=BG_SIDEBAR)
        self.no_peers_label.pack(pady=20)

        tk.Frame(main, bg=BORDER_COLOR, width=1).pack(side="left", fill="y")

        # Sağ alan
        right = tk.Frame(main, bg=BG_DARK)
        right.pack(side="left", fill="both", expand=True)

        chat_header = tk.Frame(right, bg=BG_HEADER, height=56)
        chat_header.pack(fill="x")
        chat_header.pack_propagate(False)

        tk.Label(chat_header, text="💬  Kanal Sohbeti", font=self.font_title,
                 fg=FG_ACCENT_LIGHT, bg=BG_HEADER).pack(side="left", padx=15, pady=12)

        channel_frame = tk.Frame(chat_header, bg=BG_HEADER)
        channel_frame.pack(side="right", padx=15, pady=12)
        tk.Label(channel_frame, text="Yayın Kanalı:", font=self.font_body,
                 fg=FG_DIM, bg=BG_HEADER).pack(side="left", padx=(0, 5))

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TCombobox", fieldbackground=BG_INPUT, background=BG_DARK, foreground=FG_TEXT)

        self.room_var = tk.StringVar()
        self.room_cb = ttk.Combobox(channel_frame, textvariable=self.room_var,
                                    state="readonly", width=18, font=self.font_body)
        cb_values = [f"{rid} - {ROOM_NAMES.get(rid, 'Bilinmeyen')}" for rid in self.active_rooms]
        self.room_cb['values'] = cb_values
        if cb_values:
            self.room_cb.current(0)
        self.room_cb.bind("<<ComboboxSelected>>", self._on_room_changed)
        self.room_cb.pack(side="left")

        tk.Frame(right, bg=BORDER_COLOR, height=1).pack(fill="x")

        # Sohbet alanı
        self.chat_area = scrolledtext.ScrolledText(
            right, font=self.font_chat, bg=BG_PANEL, fg=FG_TEXT,
            relief="flat", bd=0, wrap="word", state="disabled",
            insertbackground=FG_TEXT, selectbackground=FG_ACCENT,
            padx=15, pady=10, spacing3=4
        )
        self.chat_area.pack(fill="both", expand=True)

        # Tag tanımları — TÜMÜ burada, widget oluşturulur oluşturulmaz
        self.chat_area.tag_configure("time",
            foreground=FG_DIM, font=("Segoe UI", 9))
        self.chat_area.tag_configure("channel",
            foreground=FG_ACCENT, font=("Segoe UI", 9, "bold"))
        self.chat_area.tag_configure("self",
            foreground=FG_ACCENT_LIGHT, font=("Segoe UI", 10, "bold"))
        self.chat_area.tag_configure("other",
            foreground=FG_GREEN, font=("Segoe UI", 10, "bold"))
        self.chat_area.tag_configure("text",
            foreground=FG_TEXT, font=("Segoe UI", 11))
        self.chat_area.tag_configure("system",
            foreground=FG_ORANGE, font=("Segoe UI", 10, "italic"))

        # Giriş satırı
        tk.Frame(right, bg=BORDER_COLOR, height=1).pack(fill="x")
        input_frame = tk.Frame(right, bg=BG_INPUT, height=52)
        input_frame.pack(fill="x")
        input_frame.pack_propagate(False)

        self.chat_input = tk.Entry(input_frame, font=self.font_input, bg=BG_INPUT, fg=FG_TEXT,
                                   insertbackground=FG_TEXT, relief="flat", bd=0)
        self.chat_input.pack(side="left", fill="both", expand=True, padx=15, pady=8)
        self.chat_input.bind("<Return>", self._on_send_message)

        send_btn = tk.Button(input_frame, text="Gönder", font=self.font_body,
                             bg=FG_ACCENT, fg="white", activebackground=FG_ACCENT_LIGHT,
                             relief="flat", bd=0, cursor="hand2", padx=20,
                             command=lambda: self._on_send_message(None))
        send_btn.pack(side="right", padx=(0, 10), pady=8)

        # PTT çubuğu
        tk.Frame(right, bg=BORDER_COLOR, height=1).pack(fill="x")
        self.ptt_frame = tk.Frame(right, bg=PTT_IDLE_BG)
        self.ptt_frame.pack(fill="x")

        self.ptt_indicator = tk.Label(self.ptt_frame, text="●", font=("Segoe UI", 14),
                                      fg=FG_GREEN, bg=PTT_IDLE_BG)
        self.ptt_indicator.pack(side="left", padx=(20, 8), pady=8)

        self.vad_btn = tk.Button(self.ptt_frame, text="VAD: Kapalı", font=self.font_small,
                                 fg=FG_DIM, bg=BG_DARK, activebackground=BG_INPUT,
                                 activeforeground=FG_TEXT, relief="flat", cursor="hand2",
                                 command=self._on_vad_toggle, padx=10, pady=4)
        self.vad_btn.pack(side="right", padx=(10, 20), pady=8)

        self.ptt_badge = tk.Label(self.ptt_frame, text="", font=self.font_small,
                                  fg=FG_DIM, bg=PTT_IDLE_BG)
        self.ptt_badge.pack(side="right", padx=10)

        self.ptt_label = tk.Label(self.ptt_frame,
                                  text="HAZIR  ·  Konuşmak için  Shift + V  basılı tut",
                                  font=self.font_ptt, fg=FG_GREEN, bg=PTT_IDLE_BG)
        self.ptt_label.pack(side="left", fill="x", expand=True)

        self._update_ptt_badge()

    def _on_room_changed(self, event):
        val = self.room_var.get()
        if val:
            self.current_room_id = int(val.split(" - ")[0])
            self._update_ptt_badge()
            log.debug(f"Kanal: {ROOM_NAMES.get(self.current_room_id)}")
            if self.on_channel_changed:
                self.on_channel_changed(self.current_room_id)

    def _update_ptt_badge(self):
        room_name = ROOM_NAMES.get(self.current_room_id, "Bilinmeyen")
        icon = "🔒" if self.current_room_id != 0 else "🔓"
        self.ptt_badge.config(text=f"{room_name} {icon}")

    def _on_vad_toggle(self):
        self.vad_state = not self.vad_state
        if self.vad_state:
            self.vad_btn.config(text="VAD: AÇIK", fg=FG_GREEN, bg=BG_SIDEBAR)
            self._set_ptt_state(True, override_text="YAYINDA  ·  Sesle aktivasyon devrede...")
        else:
            self.vad_btn.config(text="VAD: Kapalı", fg=FG_DIM, bg=BG_DARK)
            self._set_ptt_state(False)
        if self.on_vad_toggled:
            self.on_vad_toggled(self.vad_state, self.current_room_id)

    def _bind_keys(self):
        self.root.bind("<KeyPress>", self._on_key_press)
        self.root.bind("<KeyRelease>", self._on_key_release)

    def _on_key_press(self, event):
        try:
            if event.keysym in ("Shift_L", "Shift_R"):
                self._shift_held = True
            if event.keysym.lower() == "v" and self._shift_held:
                if self.root.focus_get() == self.chat_input:
                    return
                if not self._ptt_active:
                    self._ptt_active = True
                    self._set_ptt_state(True)
                    if self.on_play_beep:
                        self.on_play_beep(880, 50)
                    if self.on_ptt_start:
                        self.on_ptt_start(self.current_room_id)
        except Exception as e:
            log.error(f"key_press: {e}", exc_info=True)

    def _on_key_release(self, event):
        try:
            if event.keysym in ("Shift_L", "Shift_R"):
                self._shift_held = False
                if self._ptt_active:
                    self._ptt_active = False
                    self._set_ptt_state(False)
                    if self.on_play_beep:
                        self.on_play_beep(659, 50)
                    if self.on_ptt_stop:
                        self.on_ptt_stop()
            if event.keysym.lower() == "v":
                if self._ptt_active:
                    self._ptt_active = False
                    self._set_ptt_state(False)
                    if self.on_play_beep:
                        self.on_play_beep(659, 50)
                    if self.on_ptt_stop:
                        self.on_ptt_stop()
        except Exception as e:
            log.error(f"key_release: {e}", exc_info=True)

    def _set_ptt_state(self, active: bool, override_text: str = None):
        try:
            if active:
                self.ptt_frame.configure(bg=PTT_ACTIVE_BG)
                self.ptt_indicator.configure(fg=FG_RED, bg=PTT_ACTIVE_BG, text="⏺")
                if not self.vad_state:
                    self.vad_btn.configure(bg=PTT_ACTIVE_BG)
                txt = override_text or f"YAYINDA ({ROOM_NAMES.get(self.current_room_id, '?')})  ·  Konuşuluyor..."
                self.ptt_label.configure(text=txt, fg=FG_RED, bg=PTT_ACTIVE_BG)
                self.ptt_badge.configure(bg=PTT_ACTIVE_BG)
            else:
                self.ptt_frame.configure(bg=PTT_IDLE_BG)
                self.ptt_indicator.configure(fg=FG_GREEN, bg=PTT_IDLE_BG, text="●")
                if not self.vad_state:
                    self.vad_btn.configure(bg=BG_DARK)
                self.ptt_label.configure(
                    text="HAZIR  ·  Konuşmak için  Shift + V  basılı tut",
                    fg=FG_GREEN, bg=PTT_IDLE_BG)
                self.ptt_badge.configure(bg=PTT_IDLE_BG)
        except Exception as e:
            log.error(f"ptt_state: {e}", exc_info=True)

    def _on_send_message(self, event):
        try:
            text = self.chat_input.get().strip()
            if not text:
                return "break"
            self.chat_input.delete(0, "end")
            self.add_chat_message(self.username, text, is_self=True, room_id=self.current_room_id)
            if self.on_send_chat:
                self.on_send_chat(text, self.current_room_id)
            return "break"
        except Exception as e:
            log.error(f"send_message: {e}", exc_info=True)

    def append_chat(self, sender: str, message: str, room_id: int, is_self: bool = False):
        """Ağdan gelen mesajı ekrana yazar."""
        self.add_chat_message(sender, message, is_self=is_self, room_id=room_id)

    def add_chat_message(self, sender: str, message: str, is_self: bool = False, room_id: int = 0):
        """Mesajı renk kodlu tag'lerle sohbet alanına ekler."""
        if self._is_closing:
            return

        def _update():
            try:
                if self._is_closing or not getattr(self, "chat_area", None) or not self.root.winfo_exists():
                    return
                self.chat_area.config(state="normal")
                t_str = time.strftime("%H:%M")
                self.chat_area.insert("end", f"[{t_str}] ", "time")
                r_name = ROOM_NAMES.get(room_id, str(room_id))
                self.chat_area.insert("end", f"[{r_name}] ", "channel")
                name_tag = "self" if is_self else "other"
                self.chat_area.insert("end", f"{sender}: ", name_tag)
                self.chat_area.insert("end", f"{message}\n", "text")
                self.chat_area.config(state="disabled")
                self.chat_area.see("end")
            except tk.TclError:
                pass

        self.root.after(0, _update)

    def add_system_message(self, message: str):
        if self._is_closing:
            return

        def _update():
            try:
                if self._is_closing or not getattr(self, "chat_area", None) or not self.root.winfo_exists():
                    return
                self.chat_area.config(state="normal")
                self.chat_area.insert("end", f"\n[SİSTEM] {message}\n", "system")
                self.chat_area.config(state="disabled")
                self.chat_area.see("end")
            except tk.TclError:
                pass

        self.root.after(0, _update)

    def update_peers(self, peers: list):
        if self._is_closing:
            return

        def _update():
            try:
                if self._is_closing or not self.root.winfo_exists():
                    return

                old_peer_ips = set()
                for widget in self.peer_widgets_frame.winfo_children():
                    if isinstance(widget, tk.Frame):
                        children = widget.winfo_children()
                        if len(children) >= 3:
                            old_peer_ips.add(children[2].cget("text"))

                for widget in self.peer_widgets_frame.winfo_children():
                    widget.destroy()

                if not peers:
                    tk.Label(self.peer_widgets_frame, text="Henüz eş bulunamadı…",
                             font=self.font_small, fg=FG_DIM, bg=BG_SIDEBAR).pack(pady=20)
                    return

                for name, ip in peers:
                    row = tk.Frame(self.peer_widgets_frame, bg=BG_SIDEBAR)
                    row.pack(fill="x", pady=2)
                    tk.Label(row, text="●", font=("Segoe UI", 8), fg=PEER_DOT_ONLINE, bg=BG_SIDEBAR).pack(side="left", padx=(5, 8))
                    tk.Label(row, text=name, font=self.font_peer, fg=FG_TEXT, bg=BG_SIDEBAR).pack(side="left")
                    tk.Label(row, text=ip, font=self.font_small, fg=FG_DIM, bg=BG_SIDEBAR).pack(side="right", padx=5)

                    if ip not in old_peer_ips and self.on_play_beep:
                        self.on_play_beep(880, 50)
                        self.root.after(100, lambda: self.on_play_beep(1046, 50))

                log.debug(f"Eş listesi: {len(peers)} eş")
            except Exception as e:
                log.error(f"update_peers: {e}", exc_info=True)

        self.root.after(0, _update)

    def _do_close(self):
        self._is_closing = True
        try:
            if self.on_close:
                self.on_close()
            if self.root.winfo_exists():
                self.root.destroy()
        except Exception as e:
            log.error(f"close: {e}", exc_info=True)

    def _handle_actual_close(self, icon=None, item=None):
        if icon:
            icon.stop()
        self.root.after(0, self._do_close)

    def _create_tray_image(self):
        image = Image.new('RGB', (64, 64), color=(26, 26, 36))
        dc = ImageDraw.Draw(image)
        dc.line((32, 10, 32, 40), fill=FG_ACCENT, width=4)
        dc.rectangle((20, 30, 44, 60), fill=FG_TEXT)
        dc.rectangle((24, 34, 40, 44), fill=BG_DARK)
        return image

    def _show_window(self, icon=None, item=None):
        if icon:
            icon.stop()
        self.root.after(0, self.root.deiconify)

    def _on_window_closing(self):
        """Kapatma butonuna basılınca ne yapılacağını kullanıcıya sor."""
        if self._is_closing:
            return
        self._show_close_dialog()

    def _show_close_dialog(self):
        """'Traye küçült / Tamamen çık' seçim penceresi."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Çıkış")
        dialog.configure(bg=BG_DARK)
        dialog.resizable(False, False)
        dialog.grab_set()          # Modal yap
        dialog.focus_force()

        # Ortala
        dialog.update_idletasks()
        dw, dh = 340, 180
        rx = self.root.winfo_x() + (self.root.winfo_width() - dw) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - dh) // 2
        dialog.geometry(f"{dw}x{dh}+{rx}+{ry}")

        tk.Label(dialog, text="Ne yapmak istiyorsunuz?",
                 font=tkfont.Font(family="Segoe UI", size=12, weight="bold"),
                 fg=FG_TEXT, bg=BG_DARK).pack(pady=(24, 6))

        tk.Label(dialog, text="Uygulama arka planda çalışmaya devam edebilir.",
                 font=tkfont.Font(family="Segoe UI", size=9),
                 fg=FG_DIM, bg=BG_DARK).pack(pady=(0, 18))

        btn_frame = tk.Frame(dialog, bg=BG_DARK)
        btn_frame.pack(fill="x", padx=24)

        def minimize_to_tray():
            dialog.destroy()
            self._go_to_tray()

        def quit_app():
            dialog.destroy()
            self._do_close()

        tk.Button(btn_frame, text="🔽  Traye Küçült",
                  font=tkfont.Font(family="Segoe UI", size=10),
                  bg=BG_INPUT, fg=FG_TEXT, activebackground=BG_PANEL,
                  activeforeground=FG_TEXT, relief="flat", cursor="hand2",
                  command=minimize_to_tray, padx=12, pady=8).pack(side="left", expand=True, fill="x", padx=(0, 6))

        tk.Button(btn_frame, text="❌  Tamamen Çık",
                  font=tkfont.Font(family="Segoe UI", size=10),
                  bg=FG_RED, fg="white", activebackground="#e05555",
                  activeforeground="white", relief="flat", cursor="hand2",
                  command=quit_app, padx=12, pady=8).pack(side="left", expand=True, fill="x", padx=(6, 0))

        dialog.bind("<Escape>", lambda e: dialog.destroy())

    def _go_to_tray(self):
        """Pencereyi gizle, sistem tepsisine al."""
        self.root.withdraw()
        image = self._create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Göster", self._show_window, default=True),
            pystray.MenuItem("Çıkış", self._handle_actual_close)
        )
        self.tray_icon = pystray.Icon("walkie_talkie", image, "Walkie-Talkie LAN", menu=menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()
        log.info("Uygulama sistem tepsisine alındı")

    def mainloop(self):
        try:
            self.root.mainloop()
        except Exception as e:
            log.error(f"mainloop: {e}", exc_info=True)