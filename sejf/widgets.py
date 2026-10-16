"""Wspólne elementy interfejsu."""
from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .generator import strength

VAULT_TYPES = [("Plik sejfu", "*.json"), ("Wszystkie pliki", "*.*")]
PROFILE_TYPES = [("Profil klienta", "*.sejfklient"), ("Wszystkie pliki", "*.*")]
CSV_TYPES = [("Plik CSV", "*.csv"), ("Wszystkie pliki", "*.*")]

COLORS = {
    False: dict(muted="#5c6864", error="#c42b1c", warn="#9d5d00", ok="#0f7b0f", empty="#d6dcda",
                text_bg="#ffffff", text_fg="#1c1c1c", chip="#e8eeec", chip_fg="#33403b"),
    True: dict(muted="#a3aeaa", error="#ff99a4", warn="#f0c24f", ok="#6ccb5f", empty="#3d4542",
               text_bg="#2b2b2b", text_fg="#f3f3f3", chip="#2f3835", chip_fg="#cfd8d4"),
}


def cloud_folder() -> str | None:
    """Folder Dysku Google albo OneDrive, jeśli jest na komputerze."""
    home = Path.home()
    candidates = [Path("G:/Mój dysk"), Path("G:/My Drive"), home / "Google Drive", home / "Mój dysk"]
    if os.environ.get("OneDrive"):
        candidates.append(Path(os.environ["OneDrive"]))
    candidates.append(home / "OneDrive")
    for p in candidates:
        if p.is_dir():
            return str(p)
    return None


def open_folder(path: str) -> None:
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    if sys.platform == "win32":
        import subprocess
        if os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            os.startfile(folder)  # type: ignore[attr-defined]


class StrengthBar(ttk.Frame):
    """Pięć kresek pokazujących siłę hasła."""

    def __init__(self, master, app, empty_text: str = ""):
        super().__init__(master)
        self.app, self.empty_text = app, empty_text
        self.canvas = tk.Canvas(self, width=app.px(126), height=app.px(8), highlightthickness=0, bd=0, bg=app.bg())
        self.canvas.pack(side="left")
        self.label = ttk.Label(self, style="Muted.TLabel")
        self.label.pack(side="left", padx=(10, 0))
        self.set("")

    def set(self, pw: str) -> None:
        score, label = strength(pw)
        c = self.app.colors
        fill = c["error"] if score <= 2 else c["warn"] if score == 3 else c["ok"]
        px = self.app.px
        self.canvas.delete("all")
        for i in range(5):
            x = px(i * 25)
            self.canvas.create_rectangle(x, px(1), x + px(22), px(7), width=0, fill=fill if i < score else c["empty"])
        self.label.configure(text=label if pw else self.empty_text)


class ScrollFrame(ttk.Frame):
    """Przewijany obszar; zawartość wkłada się do ``self.inner``."""

    def __init__(self, master, app, padding=(22, 4, 12, 16)):
        super().__init__(master)
        self.app = app
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=app.bg())
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas, padding=padding)
        self.win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._update)
        self.canvas.bind("<Configure>", self._update)
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _update(self, _e=None):
        self.canvas.itemconfigure(self.win, width=self.canvas.winfo_width())
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()))
        need = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 2
        if need and not self.vsb.winfo_ismapped():
            self.vsb.pack(side="right", fill="y", before=self.canvas)
        elif not need and self.vsb.winfo_ismapped():
            self.vsb.pack_forget()
            self.canvas.yview_moveto(0)

    def _wheel(self, e):
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)


class Dialog(tk.Toplevel):
    """Okno dialogowe w motywie programu, nie blokuje pętli zdarzeń."""

    def __init__(self, app, title: str, resizable: bool = False):
        super().__init__(app.root)
        self.app = app
        self.withdraw()
        self.title(title)
        self.transient(app.root)
        self.resizable(resizable, resizable)
        self.iconphoto(False, app.icon)
        self.body = ttk.Frame(self, padding=22)
        self.body.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda e: self.close())
        app.dialogs.append(self)

    def show(self):
        self.update_idletasks()
        r = self.app.root
        x = r.winfo_rootx() + max(0, (r.winfo_width() - self.winfo_reqwidth()) // 2)
        y = r.winfo_rooty() + max(0, (r.winfo_height() - self.winfo_reqheight()) // 3)
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.lift()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_set()
        return self

    def close(self):
        if self in self.app.dialogs:
            self.app.dialogs.remove(self)
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    # pomocnicze --------------------------------------------------------------------------
    def label(self, parent, text, style="Field.TLabel", **pack):
        lbl = ttk.Label(parent, text=text, style=style)
        lbl.pack(anchor="w", **({"pady": (10, 4)} | pack))
        return lbl

    def entry(self, parent, var, show="", width=40, mono=False):
        e = ttk.Entry(parent, textvariable=var, show=show, width=width, font=self.app.mono if mono else None)
        e.pack(fill="x")
        return e

    def buttons(self, *specs):
        """specs: (tekst, polecenie, styl, strona) – zwraca listę przycisków."""
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=(18, 0))
        out = []
        for text, cmd, style, side in specs:
            b = ttk.Button(row, text=text, command=cmd, style=style or "TButton")
            b.pack(side=side, padx=(0, 8) if side == "left" else (8, 0))
            out.append(b)
        return out


def later(widget, ms: int, fn) -> None:
    """Opóźnione wywołanie zaplanowane na oknie głównym, nie na widżecie.

    Tkinter usuwa polecenia widżetu przy jego zniszczeniu, ale zaplanowane zadanie zostaje;
    jego nazwa może trafić do nowego polecenia (np. przycisku) i uruchomić je bez kliknięcia.
    Okno główne żyje przez cały czas działania programu, więc tam to bezpieczne.
    """
    root = widget._root()

    def run():
        try:
            if widget.winfo_exists():
                fn()
        except tk.TclError:
            pass

    root.after(ms, run)


def focus_later(widget, ms: int = 40) -> None:
    """Ustawia fokus po chwili, o ile pole nadal istnieje (formularz mógł zostać przebudowany)."""
    later(widget, ms, widget.focus_set)


def readonly(parent, value: str, app, secret: bool = False, width: int = 0) -> ttk.Entry:
    """Pole tylko do odczytu, z którego można zaznaczyć i skopiować tekst."""
    kw = {"width": width} if width else {}
    e = ttk.Entry(parent, font=app.mono, show="•" if secret and value else "", **kw)
    e.insert(0, value or "—")
    e.configure(state="readonly")
    return e
