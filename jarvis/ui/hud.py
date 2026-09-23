"""Iron Man style HUD dashboard."""

from __future__ import annotations

import math
import threading
import time
import tkinter as tk
from tkinter import font as tkfont


class JarvisHUD:
    """Floating HUD window - status, transcript, animated radar."""

    def __init__(self, assistant_name: str = "JARVIS") -> None:
        self.assistant_name = assistant_name
        self._angle = 0
        self._status = "ONLINE"
        self._last_user = ""
        self._last_jarvis = ""
        self._thread: threading.Thread | None = None
        self._running = False
        self.root: tk.Tk | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_ui, daemon=True)
        self._thread.start()
        time.sleep(0.3)

    def stop(self) -> None:
        self._running = False
        if self.root:
            try:
                self.root.after(0, self.root.destroy)
            except Exception:
                pass

    def set_status(self, status: str) -> None:
        self._status = status
        if self.root:
            self.root.after(0, self._update_labels)

    def show_user(self, text: str) -> None:
        self._last_user = text
        if self.root:
            self.root.after(0, self._update_labels)

    def show_jarvis(self, text: str) -> None:
        self._last_jarvis = text
        if self.root:
            self.root.after(0, self._update_labels)

    def _run_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S")
        self.root.geometry("420x520+50+50")
        self.root.configure(bg="#0a0e14")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        title_font = tkfont.Font(family="Consolas", size=14, weight="bold")
        mono = tkfont.Font(family="Consolas", size=9)

        tk.Label(
            self.root, text=f"J.A.R.V.I.S  MK-1",
            fg="#22d3ee", bg="#0a0e14", font=title_font,
        ).pack(pady=(12, 4))

        self.status_label = tk.Label(
            self.root, text="● ONLINE", fg="#4ade80", bg="#0a0e14", font=mono,
        )
        self.status_label.pack()

        self.canvas = tk.Canvas(self.root, width=200, height=200, bg="#0a0e14", highlightthickness=0)
        self.canvas.pack(pady=8)

        tk.Label(self.root, text="TRANSCRIPT", fg="#64748b", bg="#0a0e14", font=mono).pack()
        self.user_label = tk.Label(
            self.root, text="", fg="#94a3b8", bg="#0a0e14", font=mono,
            wraplength=380, justify="left",
        )
        self.user_label.pack(padx=12, anchor="w")
        self.jarvis_label = tk.Label(
            self.root, text="Awaiting command, sir.",
            fg="#22d3ee", bg="#0a0e14", font=mono,
            wraplength=380, justify="left",
        )
        self.jarvis_label.pack(padx=12, pady=(4, 12), anchor="w")

        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self) -> None:
        self._running = False
        if self.root:
            self.root.destroy()

    def _update_labels(self) -> None:
        color = {"ONLINE": "#4ade80", "LISTENING": "#facc15", "THINKING": "#fb923c", "SPEAKING": "#22d3ee"}
        self.status_label.config(text=f"● {self._status}", fg=color.get(self._status, "#4ade80"))
        if self._last_user:
            self.user_label.config(text=f"You: {self._last_user}")
        if self._last_jarvis:
            self.jarvis_label.config(text=f"Jarvis: {self._last_jarvis}")

    def _animate(self) -> None:
        if not self._running or not self.root:
            return
        self.canvas.delete("all")
        cx, cy, r = 100, 100, 80
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#164e63", width=1)
        self.canvas.create_oval(cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2, outline="#0e7490", width=1)
        for i in range(3):
            a = self._angle + i * 120
            x = cx + r * 0.7 * math.cos(math.radians(a))
            y = cy + r * 0.7 * math.sin(math.radians(a))
            self.canvas.create_line(cx, cy, x, y, fill="#22d3ee", width=1)
        self._angle = (self._angle + 3) % 360
        self.root.after(50, self._animate)
