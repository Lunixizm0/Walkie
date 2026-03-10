"""
Walkie-Talkie uygulaması için arayüz.
Koyu temalı tkinter arayüzü: eşler paneli, sohbet paneli ve Bas-Konuş göstergesi.
"""

import tkinter as tk
from tkinter import scrolledtext, simpledialog, font as tkfont
import time
import threading
import logging

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False

log = logging.getLogger(__name__)

# ── Renk Paleti ────────────────────────────────────────────────
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
CHAT_SELF_BG = "#2a2555"
CHAT_OTHER_BG = "#1e2a3a"


class StartupDialog(tk.Tk):
    """Bağımsız giriş penceresi — Windows'ta düzgün gösterilmesi için doğrudan Tk kökü kullanır."""

    def __init__(self):
        try:
            super().__init__()
            self.title("Walkie-Talkie · Bağlan")
            self.configure(bg=BG_DARK)
            self.resizable(False, False)
            self.result = None  # (username, {room_id: passphrase})

            # Ekranda ortala
            w, h = 420, 500
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 2
            self.geometry(f"{w}x{h}+{x}+{y}")

            # Ön plana getir
            self.lift()
            self.attributes("-topmost", True)
            self.after(100, lambda: self.attributes("-topmost", False))

            # Yazı tipleri
            title_font = tkfont.Font(family="Segoe UI", size=18, weight="bold")
            label_font = tkfont.Font(family="Segoe UI", size=11)
            entry_font = tkfont.Font(family="Segoe UI", size=12)

            # Başlık
            header = tk.Frame(self, bg=BG_DARK, height=80)
            header.pack(fill="x", padx=30, pady=(25, 5))

            # Walkie ikonu (emoji)
            tk.Label(header, text="📻", font=("Segoe UI Emoji", 32), bg=BG_DARK).pack()
            tk.Label(
                header, text="Walkie-Talkie", font=title_font,
                fg=FG_ACCENT_LIGHT, bg=BG_DARK
            ).pack()

            # Form ana kapsayıcı
            form = tk.Frame(self, bg=BG_DARK)
            form.pack(fill="x", padx=40, pady=(5, 10))

            tk.Label(form, text="Adınız", font=label_font, fg=FG_DIM, bg=BG_DARK, anchor="w").pack(fill="x")
            self.name_entry = tk.Entry(
                form, font=entry_font, bg=BG_INPUT, fg=FG_TEXT,
                insertbackground=FG_TEXT, relief="flat", bd=0
            )
            self.name_entry.pack(fill="x", ipady=8, pady=(2, 12))
            self.name_entry.insert(0, "")
            self.name_entry.focus_set()

            # Odalar
            tk.Label(form, text="Oda Seçimi", font=label_font, fg=FG_DIM, bg=BG_DARK, anchor="w").pack(fill="x", pady=(10, 5))
            
            # Seçim değişkenleri
            self.var_genel = tk.BooleanVar(value=True)
            self.var_hocalar = tk.BooleanVar(value=False)
            self.var_yoneticiler = tk.BooleanVar(value=False)
            
            # --- Genel ---
            genel_frame = tk.Frame(form, bg=BG_DARK)
            genel_frame.pack(fill="x", pady=2)
            tk.Checkbutton(genel_frame, text="Genel (Şifresiz)", variable=self.var_genel, 
                           bg=BG_DARK, fg=FG_TEXT, selectcolor=BG_INPUT, font=label_font,
                           activebackground=BG_DARK, activeforeground=FG_TEXT).pack(side="left")
                           
            # --- Hocalar Arası ---
            hocalar_frame = tk.Frame(form, bg=BG_DARK)
            hocalar_frame.pack(fill="x", pady=2)
            cb_h = tk.Checkbutton(hocalar_frame, text="Hocalar Arası", variable=self.var_hocalar, 
                           bg=BG_DARK, fg=FG_TEXT, selectcolor=BG_INPUT, font=label_font,
                           activebackground=BG_DARK, activeforeground=FG_TEXT,
                           command=self._toggle_passwords)
            cb_h.pack(side="left")
            self.pass_hocalar = tk.Entry(hocalar_frame, font=entry_font, bg=BG_INPUT, fg=FG_TEXT,
                                         insertbackground=FG_TEXT, relief="flat", bd=0, show="•", width=15, state="disabled")
            self.pass_hocalar.pack(side="right", ipady=4)
            
            # --- Yöneticiler ---
            yonet_frame = tk.Frame(form, bg=BG_DARK)
            yonet_frame.pack(fill="x", pady=2)
            cb_y = tk.Checkbutton(yonet_frame, text="Yöneticiler", variable=self.var_yoneticiler, 
                           bg=BG_DARK, fg=FG_TEXT, selectcolor=BG_INPUT, font=label_font,
                           activebackground=BG_DARK, activeforeground=FG_TEXT,
                           command=self._toggle_passwords)
            cb_y.pack(side="left")
            self.pass_yonet = tk.Entry(yonet_frame, font=entry_font, bg=BG_INPUT, fg=FG_TEXT,
                                       insertbackground=FG_TEXT, relief="flat", bd=0, show="•", width=15, state="disabled")
            self.pass_yonet.pack(side="right", ipady=4)

            # Ayırıcı
            tk.Frame(form, bg=BG_DARK, height=10).pack()

            # --- Ayarlar ---
            settings_frame = tk.Frame(form, bg=BG_DARK)
            settings_frame.pack(fill="x", pady=2)
            self.var_tray = tk.BooleanVar(value=True)
            tk.Checkbutton(settings_frame, text="Kapattığımda arka planda çalış (Sistem Tepsisi)", variable=self.var_tray,
                           bg=BG_DARK, fg=FG_TEXT, selectcolor=BG_INPUT, font=tkfont.Font(family="Segoe UI", size=9),
                           activebackground=BG_DARK, activeforeground=FG_TEXT).pack(side="left")

            # Ayırıcı
            tk.Frame(form, bg=BG_DARK, height=15).pack()

            # Katıl butonu
            self.join_btn = tk.Button(
                form, text="Kanala Katıl", font=label_font,
                bg=FG_ACCENT, fg="white", activebackground=FG_ACCENT_LIGHT,
                activeforeground="white", relief="flat", bd=0, cursor="hand2",
                command=self._on_join
            )
            self.join_btn.pack(fill="x", ipady=8, pady=(10, 0))

            # Enter tuşu bağla
            self.bind("<Return>", lambda e: self._on_join())
            self.protocol("WM_DELETE_WINDOW", self._on_close)

            log.info("Giriş penceresi gösterildi")
        except Exception as e:
            log.error(f"Giriş penceresi oluşturulamadı: {e}", exc_info=True)
            self.result = None

    def _toggle_passwords(self):
        if self.var_hocalar.get():
            self.pass_hocalar.config(state="normal")
        else:
            self.pass_hocalar.delete(0, tk.END)
            self.pass_hocalar.config(state="disabled")
            
        if self.var_yoneticiler.get():
            self.pass_yonet.config(state="normal")
        else:
            self.pass_yonet.delete(0, tk.END)
            self.pass_yonet.config(state="disabled")

    def _on_join(self):
        try:
            name = self.name_entry.get().strip()
            if not name:
                log.debug("Boş isimle katılma denemesi")
                return
                
            rooms = {}
            if self.var_genel.get():
                rooms[0] = ""  # Genel oda için şifre gerekmiyor (sabit anahtar kullanılacak)
                
            if self.var_hocalar.get():
                pw = self.pass_hocalar.get().strip()
                if pw:
                    rooms[1] = pw
                else:
                    log.warning("Hocalar Arası seçildi ama şifre girilmedi")
                    return
                    
            if self.var_yoneticiler.get():
                pw = self.pass_yonet.get().strip()
                if pw:
                    rooms[2] = pw
                else:
                    log.warning("Yöneticiler seçildi ama şifre girilmedi")
                    return
                    
            if not rooms:
                log.warning("Hiçbir oda seçilmedi")
                return

            minimize_to_tray_enabled = self.var_tray.get()
            self.result = (name, rooms, minimize_to_tray_enabled)
            log.info(f"Kullanıcı '{name}' olarak {list(rooms.keys())} odalarına katıldı. Tray: {minimize_to_tray_enabled}")
            self.quit()
            self.destroy()
        except Exception as e:
            log.error(f"_on_join hatası: {e}", exc_info=True)

    def _on_close(self):
        log.info("Giriş penceresi katılmadan kapatıldı")
        self.result = None
        self.quit()
        self.destroy()


from tkinter import ttk

# Oda ID'den İsme haritalama
ROOM_NAMES = {
    0: "Genel",
    1: "Hocalar Arası",
    2: "Yöneticiler"
}

class WalkieTalkieGUI:
    """Ana uygulama arayüzü. Birden fazla odayı destekler."""

    def __init__(self, username: str, active_rooms: list[int], on_send_chat=None, on_ptt_start=None, on_ptt_stop=None, on_channel_changed=None, on_vad_toggled=None, on_play_beep=None, on_close=None, minimize_to_tray_enabled: bool = True):
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
            self.minimize_to_tray_enabled = minimize_to_tray_enabled

            self._ptt_active = False
            self._shift_held = False
            self._v_held = False
            self._is_closing = False

            # ── Ana Pencere ────────────────────────────────────────
            self.root = tk.Tk()
            self.root.title(f"Walkie-Talkie · {username}")
            self.root.configure(bg=BG_DARK)
            self.root.minsize(900, 650)

            # Sistem tepsisi iş parçacığı yönetimi
            self.tray_icon = None

            # Ekranda ortala
            w, h = 1000, 700
            x = (self.root.winfo_screenwidth() - w) // 2
            y = (self.root.winfo_screenheight() - h) // 2
            self.root.geometry(f"{w}x{h}+{x}+{y}")

            # Yazı tipleri
            self.font_title = tkfont.Font(family="Segoe UI", size=13, weight="bold")
            self.font_body = tkfont.Font(family="Segoe UI", size=11)
            self.font_small = tkfont.Font(family="Segoe UI", size=9)
            self.font_chat = tkfont.Font(family="Segoe UI", size=11)
            self.font_input = tkfont.Font(family="Segoe UI", size=12)
            self.font_ptt = tkfont.Font(family="Segoe UI", size=12, weight="bold")
            self.font_peer = tkfont.Font(family="Segoe UI", size=11)

            # ── Düzen ──────────────────────────────────────────────
            self._build_layout()
            self._bind_keys()

            # Kapatma olayını yakala
            self.root.protocol("WM_DELETE_WINDOW", self._on_window_closing)
            
            log.info(f"Arayüz '{username}' kullanıcısı için başlatıldı")
        except Exception as e:
            log.error(f"Arayüz başlatılamadı: {e}", exc_info=True)
            raise

    def _build_layout(self):
        try:
            # Ana kapsayıcı
            main = tk.Frame(self.root, bg=BG_DARK)
            main.pack(fill="both", expand=True)

            # ── Sol Kenar Çubuğu (Eşler) ─────────────────────────
            sidebar = tk.Frame(main, bg=BG_SIDEBAR, width=220)
            sidebar.pack(side="left", fill="y")
            sidebar.pack_propagate(False)

            # Kenar çubuğu başlığı
            sb_header = tk.Frame(sidebar, bg=BG_HEADER, height=56)
            sb_header.pack(fill="x")
            sb_header.pack_propagate(False)
            tk.Label(
                sb_header, text="📡  Çevrimiçi Eşler", font=self.font_title,
                fg=FG_ACCENT_LIGHT, bg=BG_HEADER
            ).pack(side="left", padx=15, pady=12)

            # Ayırıcı
            tk.Frame(sidebar, bg=BORDER_COLOR, height=1).pack(fill="x")

            # Eşler listesi alanı
            self.peers_frame = tk.Frame(sidebar, bg=BG_SIDEBAR)
            self.peers_frame.pack(fill="both", expand=True, padx=10, pady=10)

            # "Sen" etiketi
            you_frame = tk.Frame(self.peers_frame, bg=BG_SIDEBAR)
            you_frame.pack(fill="x", pady=(0, 8))
            tk.Label(
                you_frame, text="●", font=("Segoe UI", 8), fg=FG_GREEN, bg=BG_SIDEBAR
            ).pack(side="left", padx=(5, 8))
            tk.Label(
                you_frame, text=f"{self.username} (Sen)", font=self.font_peer,
                fg=FG_TEXT, bg=BG_SIDEBAR
            ).pack(side="left")

            tk.Frame(self.peers_frame, bg=BORDER_COLOR, height=1).pack(fill="x", pady=5)

            self.peer_widgets_frame = tk.Frame(self.peers_frame, bg=BG_SIDEBAR)
            self.peer_widgets_frame.pack(fill="both", expand=True)

            # Eş yok etiketi
            self.no_peers_label = tk.Label(
                self.peer_widgets_frame, text="Eşler aranıyor…",
                font=self.font_small, fg=FG_DIM, bg=BG_SIDEBAR
            )
            self.no_peers_label.pack(pady=20)

            # ── Ayırıcı ──────────────────────────────────────────
            tk.Frame(main, bg=BORDER_COLOR, width=1).pack(side="left", fill="y")

            # ── Sağ Alan (Sohbet + Bas-Konuş) ────────────────────
            right = tk.Frame(main, bg=BG_DARK)
            right.pack(side="left", fill="both", expand=True)

            # Sohbet başlığı ve Kanal Seçimi
            chat_header = tk.Frame(right, bg=BG_HEADER, height=56)
            chat_header.pack(fill="x")
            chat_header.pack_propagate(False)
            
            tk.Label(
                chat_header, text="💬  Kanal Sohbeti", font=self.font_title,
                fg=FG_ACCENT_LIGHT, bg=BG_HEADER
            ).pack(side="left", padx=15, pady=12)
            
            # --- Kanal Seçim Dropdown ---
            channel_frame = tk.Frame(chat_header, bg=BG_HEADER)
            channel_frame.pack(side="right", padx=15, pady=12)
            
            tk.Label(channel_frame, text="Yayın Kanalı:", font=self.font_body, fg=FG_DIM, bg=BG_HEADER).pack(side="left", padx=(0, 5))
            
            # combobox stili
            style = ttk.Style()
            style.theme_use('clam')
            style.configure("TCombobox", fieldbackground=BG_INPUT, background=BG_DARK, foreground=FG_TEXT)
            
            self.room_var = tk.StringVar()
            self.room_cb = ttk.Combobox(channel_frame, textvariable=self.room_var, state="readonly", width=15, font=self.font_body)
            
            # Sadece aktif odaları listele
            cb_values = [f"{room_id} - {ROOM_NAMES.get(room_id, 'Bilinmeyen')}" for room_id in self.active_rooms]
            self.room_cb['values'] = cb_values
            
            if cb_values:
                self.room_cb.current(0)
            
            self.room_cb.bind("<<ComboboxSelected>>", self._on_room_changed)
            self.room_cb.pack(side="left")

            tk.Frame(right, bg=BORDER_COLOR, height=1).pack(fill="x")

            # Sohbet mesajları alanı
            self.chat_area = scrolledtext.ScrolledText(
                right, font=self.font_chat, bg=BG_PANEL, fg=FG_TEXT,
                relief="flat", bd=0, wrap="word", state="disabled",
                insertbackground=FG_TEXT, selectbackground=FG_ACCENT,
                padx=15, pady=10, spacing3=4
            )
            self.chat_area.pack(fill="both", expand=True)

            # Stil için metin etiketlerini yapılandır
            self.chat_area.tag_configure("self_name", foreground=FG_ACCENT_LIGHT, font=("Segoe UI", 10, "bold"))
            self.chat_area.tag_configure("other_name", foreground=FG_GREEN, font=("Segoe UI", 10, "bold"))
            self.chat_area.tag_configure("message", foreground=FG_TEXT, font=("Segoe UI", 11))
            self.chat_area.tag_configure("timestamp", foreground=FG_DIM, font=("Segoe UI", 8))
            self.chat_area.tag_configure("system", foreground=FG_ORANGE, font=("Segoe UI", 10, "italic"))

            # Sohbet girişi alanı
            input_frame = tk.Frame(right, bg=BG_INPUT, height=52)
            input_frame.pack(fill="x")
            input_frame.pack_propagate(False)

            tk.Frame(right, bg=BORDER_COLOR, height=1).pack(fill="x", before=input_frame)

            self.chat_input = tk.Entry(
                input_frame, font=self.font_input, bg=BG_INPUT, fg=FG_TEXT,
                insertbackground=FG_TEXT, relief="flat", bd=0
            )
            self.chat_input.pack(side="left", fill="both", expand=True, padx=15, pady=8)
            self.chat_input.bind("<Return>", self._on_send_message)

            send_btn = tk.Button(
                input_frame, text="Gönder", font=self.font_body,
                bg=FG_ACCENT, fg="white", activebackground=FG_ACCENT_LIGHT,
                relief="flat", bd=0, cursor="hand2", padx=20,
                command=lambda: self._on_send_message(None)
            )
            send_btn.pack(side="right", padx=(0, 10), pady=8)

            # ── Bas-Konuş Durum Çubuğu ───────────────────────────
            tk.Frame(right, bg=BORDER_COLOR, height=1).pack(fill="x")

            self.ptt_frame = tk.Frame(right, bg=PTT_IDLE_BG)
            self.ptt_frame.pack(fill="x")

            self.ptt_indicator = tk.Label(
                self.ptt_frame, text="●", font=("Segoe UI", 16),
                fg=FG_GREEN, bg=PTT_IDLE_BG
            )
            self.ptt_indicator.pack(side="left", padx=(20, 8), pady=15)

            # --- VAD (Sesle Aktivasyon) Butonu ---
            self.vad_state = False
            self.vad_btn = tk.Button(
                self.ptt_frame, text="VAD: Kapalı", font=self.font_small,
                fg=FG_DIM, bg=BG_DARK, activebackground=BG_INPUT, activeforeground=FG_TEXT,
                relief="flat", cursor="hand2", command=self._on_vad_toggle,
                padx=10, pady=5
            )
            # vad_btn'i önce paketleyerek alanın garanti edilmesini sağlıyoruz
            self.vad_btn.pack(side="right", padx=(10, 20), pady=15)

            self.ptt_badge = tk.Label(
                self.ptt_frame, text="U2U 🔒", font=self.font_small,
                fg=FG_DIM, bg=PTT_IDLE_BG
            )
            self.ptt_badge.pack(side="right", padx=10)

            self.ptt_label = tk.Label(
                self.ptt_frame, text="HAZIR  ·  Konuşmak için  Shift + V  basılı tut",
                font=self.font_ptt, fg=FG_GREEN, bg=PTT_IDLE_BG
            )
            # En geniş olabilecek öğe en son paketleniyor, sığmazsa kendi kesilecek
            self.ptt_label.pack(side="left", fill="x", expand=True)

            log.debug("Arayüz düzeni başarıyla oluşturuldu")
            self._update_ptt_badge()
        except Exception as e:
            log.error(f"Arayüz düzeni oluşturulamadı: {e}", exc_info=True)
            raise

    def _on_room_changed(self, event):
        val = self.room_var.get()
        if val:
            # "0 - Genel" -> 0
            self.current_room_id = int(val.split(" - ")[0])
            self._update_ptt_badge()
            log.debug(f"Yayın kanalı değiştirildi: {ROOM_NAMES.get(self.current_room_id)}")
            if self.on_channel_changed:
                self.on_channel_changed(self.current_room_id)

    def _update_ptt_badge(self):
        room_name = ROOM_NAMES.get(self.current_room_id, "Bilinmeyen")
        is_encrypted = self.current_room_id != 0
        icon = "🔒" if is_encrypted else "🔓"
        self.ptt_badge.config(text=f"{room_name} {icon}")

    def _on_vad_toggle(self):
        self.vad_state = not self.vad_state
        is_on = self.vad_state
        
        # UI Güncellemesi
        if is_on:
            self.vad_btn.config(text="VAD: AÇIK", fg=FG_GREEN, bg=BG_SIDEBAR)
        else:
            self.vad_btn.config(text="VAD: Kapalı", fg=FG_DIM, bg=BG_DARK)

        log.info(f"Sesle Aktivasyon (VAD) {'açıldı' if is_on else 'kapatıldı'}.")
        if self.on_vad_toggled:
            self.on_vad_toggled(is_on, self.current_room_id)
        if is_on:
            self._set_ptt_state(True, override_text="YAYINDA  ·  Sesle aktivasyon devrede...")
        else:
            self._set_ptt_state(False)

    def _bind_keys(self):
        """Bas-Konuş tuşlarını bağlar (Shift + V)."""
        try:
            self.root.bind("<KeyPress>", self._on_key_press)
            self.root.bind("<KeyRelease>", self._on_key_release)
            log.debug("Tuş bağlamaları ayarlandı (Bas-Konuş için Shift+V)")
        except Exception as e:
            log.error(f"Tuş bağlamaları ayarlanamadı: {e}", exc_info=True)

    def _on_key_press(self, event):
        try:
            # Değiştirici tuş durumunu takip et
            if event.keysym in ("Shift_L", "Shift_R"):
                self._shift_held = True

            # Shift + V ile Bas-Konuşu etkinleştir
            if event.keysym.lower() == "v" and self._shift_held:
                # Sohbet girişine yazarken Bas-Konuşu etkinleştirme
                if self.root.focus_get() == self.chat_input:
                    return
                if not self._ptt_active:
                    self._ptt_active = True
                    self._v_held = True
                    self._set_ptt_state(True)
                    log.info("Bas-Konuş etkinleştirildi (Shift+V basıldı)")
                    if self.on_play_beep:
                        self.on_play_beep(880, 50) # Telsiz açılış bip (A5)
                    if self.on_ptt_start:
                        self.on_ptt_start(self.current_room_id)
        except Exception as e:
            log.error(f"_on_key_press hatası: {e}", exc_info=True)

    def _on_key_release(self, event):
        try:
            if event.keysym in ("Shift_L", "Shift_R"):
                self._shift_held = False
                # Shift bırakılınca Bas-Konuşu durdur
                if self._ptt_active:
                    self._ptt_active = False
                    self._v_held = False
                    self._set_ptt_state(False)
                    log.info("Bas-Konuş devre dışı bırakıldı (Shift bırakıldı)")
                    if self.on_play_beep:
                        self.on_play_beep(659, 50) # Telsiz kapanış bip (E5)
                    if self.on_ptt_stop:
                        self.on_ptt_stop()

            if event.keysym.lower() == "v":
                self._v_held = False
                # V bırakılınca Bas-Konuşu durdur
                if self._ptt_active:
                    self._ptt_active = False
                    self._set_ptt_state(False)
                    log.info("Bas-Konuş devre dışı bırakıldı (V bırakıldı)")
                    if self.on_play_beep:
                        self.on_play_beep(659, 50) # Telsiz kapanış bip (E5)
                    if self.on_ptt_stop:
                        self.on_ptt_stop()
        except Exception as e:
            log.error(f"_on_key_release hatası: {e}", exc_info=True)

    def _set_ptt_state(self, active: bool, override_text: str = None):
        """Bas-Konuş görsel göstergesini günceller."""
        try:
            if active:
                self.ptt_frame.configure(bg=PTT_ACTIVE_BG)
                self.ptt_indicator.configure(fg=FG_RED, bg=PTT_ACTIVE_BG, text="⏺")
                # Butonu da panelle çok uyumsuz durmasın diye kırmızımsı temaya atalım (Eğer vad açık değilse)
                if not self.vad_state:
                    self.vad_btn.configure(bg=PTT_ACTIVE_BG)
                
                txt = override_text or f"YAYINDA ({ROOM_NAMES.get(self.current_room_id, 'Bilinmeyen')})  ·  Konuşuluyor..."
                self.ptt_label.configure(
                    text=txt,
                    fg=FG_RED, bg=PTT_ACTIVE_BG
                )
                self.ptt_badge.configure(bg=PTT_ACTIVE_BG)
            else:
                self.ptt_frame.configure(bg=PTT_IDLE_BG)
                self.ptt_indicator.configure(fg=FG_GREEN, bg=PTT_IDLE_BG, text="●")
                if not self.vad_state:
                    self.vad_btn.configure(bg=BG_DARK)
                
                self.ptt_label.configure(
                    text="HAZIR  ·  Konuşmak için  Shift + V  basılı tut",
                    fg=FG_GREEN, bg=PTT_IDLE_BG
                )
                self.ptt_badge.configure(bg=PTT_IDLE_BG)
        except Exception as e:
            log.error(f"Bas-Konuş durumu güncellenirken hata: {e}", exc_info=True)

    def _on_send_message(self, event):
        """Sohbet mesajı gönderir."""
        try:
            text = self.chat_input.get().strip()
            if not text:
                return "break" # Prevent default Enter key behavior if no text
            self.chat_input.delete(0, "end")
            self.add_chat_message(self.username, text, is_self=True, room_id=self.current_room_id)
            log.debug(f"Sohbet mesajı gönderiliyor: '{text[:50]}'")
            if self.on_send_chat:
                self.on_send_chat(text, self.current_room_id)
            return "break" # Prevent default Enter key behavior
        except Exception as e:
            log.error(f"Mesaj gönderilirken hata: {e}", exc_info=True)

    def append_chat(self, sender: str, message: str, room_id: int, is_self: bool = False):
        """Sohbet alanına arayüzü dondurmayacak şekilde mesaj ekler."""
        if self._is_closing: return
        def _update():
            try:
                if self._is_closing or not self.root.winfo_exists(): return
                
                # Zaten mesaj gösterilmişse (kendi mesajı) sadece scroll yapalım
                # Bu gerçekte ağdan onay gibi eklenebilir, fakat burada UI'den direkt ekliyoruz
                # O yüzden if is_self mantığı için tekrarını önledik.
                pass # ...
            except tk.TclError:
                pass
        self.root.after(0, _update)

    def add_system_message(self, message: str):
        if self._is_closing: return
        def _update():
            try:
                if self._is_closing or not getattr(self, "chat_area", None) or not self.root.winfo_exists(): return
                self.chat_area.config(state="normal")
                self.chat_area.insert("end", f"\n[SİSTEM] {message}\n", "system")
                self.chat_area.config(state="disabled")
                self.chat_area.see("end")
            except tk.TclError:
                pass
        self.root.after(0, _update)

    def add_chat_message(self, sender: str, message: str, is_self: bool = False, room_id: int = 0):
        if self._is_closing: return
        def _update():
            try:
                if self._is_closing or not getattr(self, "chat_area", None) or not self.root.winfo_exists(): return
                self.chat_area.config(state="normal")
                
                # Timestamp
                t_str = time.strftime("%H:%M")
                self.chat_area.insert("end", f"[{t_str}] ", "time")
                
                # Channel tag
                r_name = ROOM_NAMES.get(room_id, str(room_id))
                self.chat_area.insert("end", f"[{r_name}] ", "channel")

                # Sender name
                tag = "self" if is_self else "other"
                self.chat_area.insert("end", f"{sender}: ", tag)
                
                # Message text
                self.chat_area.insert("end", f"{message}\n", "text")
                
                self.chat_area.config(state="disabled")
                self.chat_area.see("end")
            except tk.TclError:
                pass
        self.root.after(0, _update)

    def update_peers(self, peers: list[tuple[str, str]]):
        """Çevrimiçi eşleri yan panele güvenle günceller."""
        if self._is_closing: return
        def _update():
            try:
                if self._is_closing or not self.root.winfo_exists(): return
                
                # Sesi tetiklemek için eski eş listesini oluştur
                old_peer_ips = set()
                try:
                    for widget in self.peer_widgets_frame.winfo_children():
                        if isinstance(widget, tk.Frame):
                            labels = widget.winfo_children()
                            if len(labels) == 3:
                                old_peer_ips.add(labels[2].cget("text"))
                except Exception:
                    pass

                # Mevcut eş bileşenlerini temizle
                for widget in self.peer_widgets_frame.winfo_children():
                    widget.destroy()

                if not peers:
                    self.no_peers_label = tk.Label(
                        self.peer_widgets_frame, text="Henüz eş bulunamadı…",
                        font=self.font_small, fg=FG_DIM, bg=BG_SIDEBAR
                    )
                    self.no_peers_label.pack(pady=20)
                    log.debug("Eş listesi güncellendi: eş yok")
                    return

                for name, ip in peers:
                    peer_row = tk.Frame(self.peer_widgets_frame, bg=BG_SIDEBAR)
                    peer_row.pack(fill="x", pady=2)
                    tk.Label(
                        peer_row, text="●", font=("Segoe UI", 8),
                        fg=PEER_DOT_ONLINE, bg=BG_SIDEBAR
                    ).pack(side="left", padx=(5, 8))
                    tk.Label(
                        peer_row, text=name, font=self.font_peer,
                        fg=FG_TEXT, bg=BG_SIDEBAR
                    ).pack(side="left")
                    tk.Label(
                        peer_row, text=ip, font=self.font_small,
                        fg=FG_DIM, bg=BG_SIDEBAR
                    ).pack(side="right", padx=5)
                    
                    if ip not in old_peer_ips and self.on_play_beep:
                        # Yeni bir eş bağlandı sesi (A5, C6)
                        self.on_play_beep(880, 50)
                        self.root.after(100, lambda: self.on_play_beep(1046, 50))

                log.debug(f"Eş listesi güncellendi: {len(peers)} eş çevrimiçi")
            except Exception as e:
                log.error(f"Eş listesi güncellenirken hata: {e}", exc_info=True)

        self.root.after(0, _update)

    def _handle_close(self):
        """Pencere kapatmayı yönetir."""
        try:
            log.info("Pencere kapatma isteği — kapatılıyor")
            if self.on_close:
                self.on_close()
            self._on_window_closing()
        except Exception as e:
            log.error(f"Pencere kapatılırken hata: {e}", exc_info=True)

    def _do_close(self):
        """Tkinter ana thread'inden çağrılan güvenli kapatma."""
        self._is_closing = True
        log.info("Güvenli kapatma adımı başlatılıyor...")
        try:
            if self.on_close:
                self.on_close()
            # on_close tamamlandıysa (threadler kapandıysa) UI'ı yok et
            if self.root.winfo_exists():
                self.root.destroy()
        except Exception as e:
            log.error(f"Kapatma sırasında hata: {e}", exc_info=True)

    def _handle_actual_close(self, icon=None, item=None):
        """Gerçek uygulama kapatma işlemi (Sistem Tepsisi "Çıkış" tıklaması)."""
        if icon:
            icon.stop()
        log.info("Pencere tam kapatma isteği — kapatılıyor")
        self.root.after(0, self._do_close)
        
    def _create_tray_image(self):
        """Sistem tepsisi için basit bir simge oluşturur."""
        image = Image.new('RGB', (64, 64), color=(26, 26, 36))
        dc = ImageDraw.Draw(image)
        # Anten
        dc.line((32, 10, 32, 40), fill=FG_ACCENT, width=4)
        # Telsiz Gövdesi
        dc.rectangle((20, 30, 44, 60), fill=FG_TEXT)
        # Ekran
        dc.rectangle((24, 34, 40, 44), fill=BG_DARK)
        # Hoparlör delikleri
        dc.point((26, 50), fill=BG_DARK)
        dc.point((30, 50), fill=BG_DARK)
        dc.point((34, 50), fill=BG_DARK)
        dc.point((38, 50), fill=BG_DARK)
        return image

    def _show_window(self, icon=None, item=None):
        """Sistem tepsisinden programı tekrar ekrana getirir."""
        if icon:
            icon.stop()
        self.root.after(0, self.root.deiconify)
        log.info("Sistem tepsisinden arayüz tekrar açıldı")

    def _on_window_closing(self):
        """Pencere kapatılmak istendiğinde tepsisi tepsisine küçültür."""
        if HAS_PYSTRAY and self.minimize_to_tray_enabled:
            log.info("Uygulama arka plana (sistem tepsisine) alındı")
            self.root.withdraw() # Pencereyi gizle
            
            image = self._create_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem("Göster", self._show_window, default=True),
                pystray.MenuItem("Çıkış", self._handle_actual_close)
            )
            
            self.tray_icon = pystray.Icon("walkie_talkie", image, "Walkie-Talkie LAN", menu=menu)
            
            # Tray icon'u ayrı bir iş parçacığında çalıştır ki tkinter donmasın
            tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            tray_thread.start()
            
            # İlk defa tepsiye küçüldüğünde sisteme özel notification yollayabiliriz
            # tray_icon.notify() - İsteğe bağlı
        else:
            # pystray yoksa direkt çıkış yap
            log.warning("pystray bulunamadı, uygulama tamamen kapatılıyor.")
            self._handle_actual_close()

    def mainloop(self):
        """Tkinter ana döngüsünü başlatır."""
        try:
            log.info("Tkinter ana döngüsü başlatılıyor")
            self.root.mainloop()
            log.info("Tkinter ana döngüsü sona erdi")
        except Exception as e:
            log.error(f"Tkinter ana döngüsünde hata: {e}", exc_info=True)
