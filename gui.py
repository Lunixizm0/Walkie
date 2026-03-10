"""
GUI for the Walkie-Talkie application.
Dark-themed tkinter interface with peers panel, chat panel, and PTT indicator.
"""

import tkinter as tk
from tkinter import scrolledtext, simpledialog, font as tkfont
import time
import threading
import logging

log = logging.getLogger(__name__)

# ── Color Palette ──────────────────────────────────────────────
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
    """Standalone login window — uses Tk root directly so it always shows on Windows."""

    def __init__(self):
        try:
            super().__init__()
            self.title("Walkie-Talkie · Connect")
            self.configure(bg=BG_DARK)
            self.resizable(False, False)
            self.result = None

            # Center on screen
            w, h = 420, 340
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 2
            self.geometry(f"{w}x{h}+{x}+{y}")

            # Bring to front
            self.lift()
            self.attributes("-topmost", True)
            self.after(100, lambda: self.attributes("-topmost", False))

            # Fonts
            title_font = tkfont.Font(family="Segoe UI", size=18, weight="bold")
            label_font = tkfont.Font(family="Segoe UI", size=11)
            entry_font = tkfont.Font(family="Segoe UI", size=12)

            # Header
            header = tk.Frame(self, bg=BG_DARK, height=80)
            header.pack(fill="x", padx=30, pady=(25, 5))

            # Walkie icon (emoji)
            tk.Label(header, text="📻", font=("Segoe UI Emoji", 32), bg=BG_DARK).pack()
            tk.Label(
                header, text="Walkie-Talkie", font=title_font,
                fg=FG_ACCENT_LIGHT, bg=BG_DARK
            ).pack()

            # Form
            form = tk.Frame(self, bg=BG_DARK)
            form.pack(fill="x", padx=40, pady=(15, 10))

            tk.Label(form, text="Your Name", font=label_font, fg=FG_DIM, bg=BG_DARK, anchor="w").pack(fill="x")
            self.name_entry = tk.Entry(
                form, font=entry_font, bg=BG_INPUT, fg=FG_TEXT,
                insertbackground=FG_TEXT, relief="flat", bd=0
            )
            self.name_entry.pack(fill="x", ipady=8, pady=(2, 12))
            self.name_entry.insert(0, "")
            self.name_entry.focus_set()

            tk.Label(form, text="Channel Passphrase", font=label_font, fg=FG_DIM, bg=BG_DARK, anchor="w").pack(fill="x")
            self.pass_entry = tk.Entry(
                form, font=entry_font, bg=BG_INPUT, fg=FG_TEXT,
                insertbackground=FG_TEXT, relief="flat", bd=0, show="•"
            )
            self.pass_entry.pack(fill="x", ipady=8, pady=(2, 15))

            # Join button
            self.join_btn = tk.Button(
                form, text="Join Channel", font=label_font,
                bg=FG_ACCENT, fg="white", activebackground=FG_ACCENT_LIGHT,
                activeforeground="white", relief="flat", bd=0, cursor="hand2",
                command=self._on_join
            )
            self.join_btn.pack(fill="x", ipady=8)

            # Bind enter
            self.bind("<Return>", lambda e: self._on_join())
            self.protocol("WM_DELETE_WINDOW", self._on_close)

            log.info("StartupDialog displayed")
        except Exception as e:
            log.error(f"Failed to create StartupDialog: {e}", exc_info=True)
            self.result = None

    def _on_join(self):
        try:
            name = self.name_entry.get().strip()
            passphrase = self.pass_entry.get().strip()
            if name and passphrase:
                self.result = (name, passphrase)
                log.info(f"User joined as '{name}'")
                self.quit()
                self.destroy()
            else:
                log.debug("Join attempted with empty name or passphrase")
        except Exception as e:
            log.error(f"Error in _on_join: {e}", exc_info=True)

    def _on_close(self):
        log.info("StartupDialog closed without joining")
        self.result = None
        self.quit()
        self.destroy()


class WalkieTalkieGUI:
    """Main application GUI."""

    def __init__(self, username: str, on_send_chat=None, on_ptt_start=None, on_ptt_stop=None, on_close=None):
        try:
            self.username = username
            self.on_send_chat = on_send_chat
            self.on_ptt_start = on_ptt_start
            self.on_ptt_stop = on_ptt_stop
            self.on_close = on_close

            self._ptt_active = False
            self._shift_held = False
            self._v_held = False

            # ── Root Window ────────────────────────────────────────
            self.root = tk.Tk()
            self.root.title(f"Walkie-Talkie · {username}")
            self.root.configure(bg=BG_DARK)
            self.root.minsize(900, 600)

            # Center on screen
            w, h = 1000, 650
            x = (self.root.winfo_screenwidth() - w) // 2
            y = (self.root.winfo_screenheight() - h) // 2
            self.root.geometry(f"{w}x{h}+{x}+{y}")

            # Fonts
            self.font_title = tkfont.Font(family="Segoe UI", size=13, weight="bold")
            self.font_body = tkfont.Font(family="Segoe UI", size=11)
            self.font_small = tkfont.Font(family="Segoe UI", size=9)
            self.font_chat = tkfont.Font(family="Segoe UI", size=11)
            self.font_input = tkfont.Font(family="Segoe UI", size=12)
            self.font_ptt = tkfont.Font(family="Segoe UI", size=12, weight="bold")
            self.font_peer = tkfont.Font(family="Segoe UI", size=11)

            # ── Layout ─────────────────────────────────────────────
            self._build_layout()
            self._bind_keys()

            self.root.protocol("WM_DELETE_WINDOW", self._handle_close)
            log.info(f"WalkieTalkieGUI initialized for user '{username}'")
        except Exception as e:
            log.error(f"Failed to initialize WalkieTalkieGUI: {e}", exc_info=True)
            raise

    def _build_layout(self):
        try:
            # Main container
            main = tk.Frame(self.root, bg=BG_DARK)
            main.pack(fill="both", expand=True)

            # ── Left Sidebar (Peers) ──────────────────────────────
            sidebar = tk.Frame(main, bg=BG_SIDEBAR, width=220)
            sidebar.pack(side="left", fill="y")
            sidebar.pack_propagate(False)

            # Sidebar header
            sb_header = tk.Frame(sidebar, bg=BG_HEADER, height=56)
            sb_header.pack(fill="x")
            sb_header.pack_propagate(False)
            tk.Label(
                sb_header, text="📡  Online Peers", font=self.font_title,
                fg=FG_ACCENT_LIGHT, bg=BG_HEADER
            ).pack(side="left", padx=15, pady=12)

            # Separator
            tk.Frame(sidebar, bg=BORDER_COLOR, height=1).pack(fill="x")

            # Peers list area
            self.peers_frame = tk.Frame(sidebar, bg=BG_SIDEBAR)
            self.peers_frame.pack(fill="both", expand=True, padx=10, pady=10)

            # "You" label
            you_frame = tk.Frame(self.peers_frame, bg=BG_SIDEBAR)
            you_frame.pack(fill="x", pady=(0, 8))
            tk.Label(
                you_frame, text="●", font=("Segoe UI", 8), fg=FG_GREEN, bg=BG_SIDEBAR
            ).pack(side="left", padx=(5, 8))
            tk.Label(
                you_frame, text=f"{self.username} (You)", font=self.font_peer,
                fg=FG_TEXT, bg=BG_SIDEBAR
            ).pack(side="left")

            tk.Frame(self.peers_frame, bg=BORDER_COLOR, height=1).pack(fill="x", pady=5)

            self.peer_widgets_frame = tk.Frame(self.peers_frame, bg=BG_SIDEBAR)
            self.peer_widgets_frame.pack(fill="both", expand=True)

            # No peers label
            self.no_peers_label = tk.Label(
                self.peer_widgets_frame, text="Searching for peers…",
                font=self.font_small, fg=FG_DIM, bg=BG_SIDEBAR
            )
            self.no_peers_label.pack(pady=20)

            # ── Separator ────────────────────────────────────────
            tk.Frame(main, bg=BORDER_COLOR, width=1).pack(side="left", fill="y")

            # ── Right Area (Chat + PTT) ──────────────────────────
            right = tk.Frame(main, bg=BG_DARK)
            right.pack(side="left", fill="both", expand=True)

            # Chat header
            chat_header = tk.Frame(right, bg=BG_HEADER, height=56)
            chat_header.pack(fill="x")
            chat_header.pack_propagate(False)
            tk.Label(
                chat_header, text="💬  Channel Chat", font=self.font_title,
                fg=FG_ACCENT_LIGHT, bg=BG_HEADER
            ).pack(side="left", padx=15, pady=12)

            tk.Frame(right, bg=BORDER_COLOR, height=1).pack(fill="x")

            # Chat messages area
            self.chat_area = scrolledtext.ScrolledText(
                right, font=self.font_chat, bg=BG_PANEL, fg=FG_TEXT,
                relief="flat", bd=0, wrap="word", state="disabled",
                insertbackground=FG_TEXT, selectbackground=FG_ACCENT,
                padx=15, pady=10, spacing3=4
            )
            self.chat_area.pack(fill="both", expand=True)

            # Configure text tags for styling
            self.chat_area.tag_configure("self_name", foreground=FG_ACCENT_LIGHT, font=("Segoe UI", 10, "bold"))
            self.chat_area.tag_configure("other_name", foreground=FG_GREEN, font=("Segoe UI", 10, "bold"))
            self.chat_area.tag_configure("message", foreground=FG_TEXT, font=("Segoe UI", 11))
            self.chat_area.tag_configure("timestamp", foreground=FG_DIM, font=("Segoe UI", 8))
            self.chat_area.tag_configure("system", foreground=FG_ORANGE, font=("Segoe UI", 10, "italic"))

            # Chat input area
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
                input_frame, text="Send", font=self.font_body,
                bg=FG_ACCENT, fg="white", activebackground=FG_ACCENT_LIGHT,
                relief="flat", bd=0, cursor="hand2", padx=20,
                command=lambda: self._on_send_message(None)
            )
            send_btn.pack(side="right", padx=(0, 10), pady=8)

            # ── PTT Status Bar ────────────────────────────────────
            tk.Frame(right, bg=BORDER_COLOR, height=1).pack(fill="x")

            self.ptt_frame = tk.Frame(right, bg=PTT_IDLE_BG, height=50)
            self.ptt_frame.pack(fill="x")
            self.ptt_frame.pack_propagate(False)

            self.ptt_indicator = tk.Label(
                self.ptt_frame, text="●", font=("Segoe UI", 14),
                fg=FG_GREEN, bg=PTT_IDLE_BG
            )
            self.ptt_indicator.pack(side="left", padx=(20, 8))

            self.ptt_label = tk.Label(
                self.ptt_frame, text="READY  ·  Hold  Shift + V  to talk",
                font=self.font_ptt, fg=FG_GREEN, bg=PTT_IDLE_BG
            )
            self.ptt_label.pack(side="left")

            self.ptt_badge = tk.Label(
                self.ptt_frame, text="E2E 🔒", font=self.font_small,
                fg=FG_DIM, bg=PTT_IDLE_BG
            )
            self.ptt_badge.pack(side="right", padx=20)

            log.debug("GUI layout built successfully")
        except Exception as e:
            log.error(f"Failed to build GUI layout: {e}", exc_info=True)
            raise

    def _bind_keys(self):
        """Bind push-to-talk keys (Shift + V)."""
        try:
            self.root.bind("<KeyPress>", self._on_key_press)
            self.root.bind("<KeyRelease>", self._on_key_release)
            log.debug("Key bindings set up (Shift+V for PTT)")
        except Exception as e:
            log.error(f"Failed to bind keys: {e}", exc_info=True)

    def _on_key_press(self, event):
        try:
            # Track modifier state
            if event.keysym in ("Shift_L", "Shift_R"):
                self._shift_held = True

            # Activate PTT on Shift + V
            if event.keysym.lower() == "v" and self._shift_held:
                # Don't activate PTT when typing in chat input
                if self.root.focus_get() == self.chat_input:
                    return
                if not self._ptt_active:
                    self._ptt_active = True
                    self._v_held = True
                    self._set_ptt_state(True)
                    log.info("PTT activated (Shift+V pressed)")
                    if self.on_ptt_start:
                        self.on_ptt_start()
        except Exception as e:
            log.error(f"Error in _on_key_press: {e}", exc_info=True)

    def _on_key_release(self, event):
        try:
            if event.keysym in ("Shift_L", "Shift_R"):
                self._shift_held = False
                # Stop PTT if shift is released
                if self._ptt_active:
                    self._ptt_active = False
                    self._v_held = False
                    self._set_ptt_state(False)
                    log.info("PTT deactivated (Shift released)")
                    if self.on_ptt_stop:
                        self.on_ptt_stop()

            if event.keysym.lower() == "v":
                self._v_held = False
                # Stop PTT if V is released
                if self._ptt_active:
                    self._ptt_active = False
                    self._set_ptt_state(False)
                    log.info("PTT deactivated (V released)")
                    if self.on_ptt_stop:
                        self.on_ptt_stop()
        except Exception as e:
            log.error(f"Error in _on_key_release: {e}", exc_info=True)

    def _set_ptt_state(self, active: bool):
        """Update PTT visual indicator."""
        try:
            if active:
                self.ptt_frame.configure(bg=PTT_ACTIVE_BG)
                self.ptt_indicator.configure(fg=FG_RED, bg=PTT_ACTIVE_BG, text="⏺")
                self.ptt_label.configure(
                    text="TRANSMITTING  ·  Release to stop",
                    fg=FG_RED, bg=PTT_ACTIVE_BG
                )
                self.ptt_badge.configure(bg=PTT_ACTIVE_BG)
            else:
                self.ptt_frame.configure(bg=PTT_IDLE_BG)
                self.ptt_indicator.configure(fg=FG_GREEN, bg=PTT_IDLE_BG, text="●")
                self.ptt_label.configure(
                    text="READY  ·  Hold  Shift + V  to talk",
                    fg=FG_GREEN, bg=PTT_IDLE_BG
                )
                self.ptt_badge.configure(bg=PTT_IDLE_BG)
        except Exception as e:
            log.error(f"Error updating PTT state: {e}", exc_info=True)

    def _on_send_message(self, event):
        """Send a chat message."""
        try:
            text = self.chat_input.get().strip()
            if not text:
                return
            self.chat_input.delete(0, "end")
            # Show own message
            self.add_chat_message(self.username, text, is_self=True)
            log.debug(f"Sending chat message: '{text[:50]}'")
            if self.on_send_chat:
                self.on_send_chat(text)
        except Exception as e:
            log.error(f"Error sending message: {e}", exc_info=True)

    def add_chat_message(self, sender: str, message: str, is_self: bool = False):
        """Add a message to the chat area. Thread-safe."""
        def _insert():
            try:
                self.chat_area.configure(state="normal")
                timestamp = time.strftime("%H:%M")
                name_tag = "self_name" if is_self else "other_name"
                self.chat_area.insert("end", f"  {timestamp}  ", "timestamp")
                self.chat_area.insert("end", f"{sender}: ", name_tag)
                self.chat_area.insert("end", f"{message}\n", "message")
                self.chat_area.configure(state="disabled")
                self.chat_area.see("end")
            except Exception as e:
                log.error(f"Error inserting chat message: {e}", exc_info=True)

        self.root.after(0, _insert)

    def add_system_message(self, message: str):
        """Add a system notification to the chat. Thread-safe."""
        def _insert():
            try:
                self.chat_area.configure(state="normal")
                self.chat_area.insert("end", f"  ── {message} ──\n", "system")
                self.chat_area.configure(state="disabled")
                self.chat_area.see("end")
            except Exception as e:
                log.error(f"Error inserting system message: {e}", exc_info=True)

        self.root.after(0, _insert)

    def update_peers(self, peers: list[tuple[str, str]]):
        """Update the peers list. Thread-safe. peers = [(username, ip), ...]."""
        def _update():
            try:
                # Clear current peer widgets
                for widget in self.peer_widgets_frame.winfo_children():
                    widget.destroy()

                if not peers:
                    self.no_peers_label = tk.Label(
                        self.peer_widgets_frame, text="No peers found yet…",
                        font=self.font_small, fg=FG_DIM, bg=BG_SIDEBAR
                    )
                    self.no_peers_label.pack(pady=20)
                    log.debug("Peers list updated: no peers")
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

                log.debug(f"Peers list updated: {len(peers)} peers online")
            except Exception as e:
                log.error(f"Error updating peers list: {e}", exc_info=True)

        self.root.after(0, _update)

    def _handle_close(self):
        """Handle window close."""
        try:
            log.info("Window close requested — shutting down")
            if self.on_close:
                self.on_close()
            self.root.destroy()
        except Exception as e:
            log.error(f"Error during window close: {e}", exc_info=True)

    def run(self):
        """Start the tkinter main loop."""
        try:
            log.info("Starting tkinter main loop")
            self.root.mainloop()
            log.info("Tkinter main loop exited")
        except Exception as e:
            log.error(f"Error in tkinter main loop: {e}", exc_info=True)
