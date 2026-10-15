"""Okienkowy interfejs programu Sejf (tkinter + motyw Sun Valley w stylu Windows 11)."""
from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from . import __version__, crypto, csvio, storage, vault
from .clipboard import Clipboard
from .generator import generate, strength
from .icon import ICON_PNG_B64
from .session import Session

try:
    import sv_ttk
except ImportError:  # program działa też bez motywu, tylko wygląda skromniej
    sv_ttk = None
try:
    import darkdetect
except ImportError:
    darkdetect = None

VAULT_TYPES = [("Plik sejfu", "*.json"), ("Wszystkie pliki", "*.*")]
CSV_TYPES = [("Plik CSV", "*.csv"), ("Wszystkie pliki", "*.*")]
LOCK_CHOICES = [("1 minuta", 1), ("5 minut", 5), ("15 minut", 15), ("30 minut", 30), ("1 godzina", 60), ("Nigdy", 0)]
CLIP_CHOICES = [("15 sekundach", 15), ("30 sekundach", 30), ("1 minucie", 60), ("Nie czyść", 0)]
THEME_CHOICES = [("Taki jak w systemie", "system"), ("Jasny", "light"), ("Ciemny", "dark")]

COLORS = {
    False: dict(muted="#5c6864", error="#c42b1c", warn="#9d5d00", ok="#0f7b0f", empty="#d6dcda",
                text_bg="#ffffff", text_fg="#1c1c1c", select="#cfe3da", star="#a87b1f"),
    True: dict(muted="#a3aeaa", error="#ff99a4", warn="#f0c24f", ok="#6ccb5f", empty="#3d4542",
               text_bg="#2b2b2b", text_fg="#f3f3f3", select="#2c4a3f", star="#e0b45c"),
}


def cloud_folder() -> str | None:
    """Folder Dysku Google albo OneDrive, jeśli jest na komputerze."""
    home = Path.home()
    for p in (Path("G:/Mój dysk"), Path("G:/My Drive"), home / "Google Drive", home / "Mój dysk",
              Path(os.environ.get("OneDrive", "")) if os.environ.get("OneDrive") else None, home / "OneDrive"):
        if p and p.is_dir():
            return str(p)
    return None


@dataclass
class ImportPreview:
    path: str
    fmt: str
    found: int
    fresh: list


# =============================================================================
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
        self.canvas.delete("all")
        px = self.app.px
        for i in range(5):
            x = px(i * 25)
            self.canvas.create_rectangle(x, px(1), x + px(22), px(7), width=0, fill=fill if i < score else c["empty"])
        self.label.configure(text=label if pw else self.empty_text)


class Dialog(tk.Toplevel):
    """Okno dialogowe w motywie programu, nie blokuje pętli zdarzeń."""

    def __init__(self, app, title: str):
        super().__init__(app.root)
        self.app = app
        self.withdraw()
        self.title(title)
        self.transient(app.root)
        self.resizable(False, False)
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


# =============================================================================
class LockScreen(ttk.Frame):
    def __init__(self, app, mode: str, message: str = ""):
        super().__init__(app.root)
        self.app = app
        outer, card = app.card(self, 32)
        outer.place(relx=0.5, rely=0.46, anchor="center")
        head = ttk.Frame(card)
        head.pack(fill="x")
        ttk.Label(head, image=app.icon).pack(side="left")
        t = ttk.Frame(head)
        t.pack(side="left", padx=(16, 0))
        ttk.Label(t, text="Sejf", style="Hero.TLabel").pack(anchor="w")
        ttk.Label(t, text="Twoje hasła w zaszyfrowanym pliku,\nktóry trzymasz u siebie.", style="Muted.TLabel",
                  justify="left").pack(anchor="w")
        self.body = ttk.Frame(card, width=360)
        self.body.pack(fill="x", pady=(24, 0))
        self.message = message
        {"home": self.show_home, "unlock": self.show_unlock, "create": self.show_create}[mode]()

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _note(self, text, style="Muted.TLabel"):
        lbl = ttk.Label(self.body, text=text, style=style, wraplength=360, justify="left")
        lbl.pack(fill="x", pady=(12, 0))
        return lbl

    # --- ekran startowy -------------------------------------------------------
    def show_home(self):
        self._clear()
        ttk.Button(self.body, text="Otwórz plik sejfu…", style="Accent.TButton", command=self.pick_file).pack(fill="x", ipady=3)
        ttk.Button(self.body, text="Utwórz nowy sejf…", command=self.show_create).pack(fill="x", pady=(8, 0), ipady=3)
        self._note("Zapisz plik sejfu w folderze Dysku Google albo OneDrive. Wtedy ten sam plik otworzysz na "
                   "każdym komputerze i na telefonie.")

    def pick_file(self):
        p = filedialog.askopenfilename(parent=self.app.root, title="Otwórz plik sejfu", filetypes=VAULT_TYPES,
                                       initialdir=cloud_folder())
        if p:
            self.app.last_path = p
            self.show_unlock()

    # --- odblokowanie -----------------------------------------------------------
    def show_unlock(self):
        self._clear()
        path = self.app.last_path or ""
        chip = ttk.Frame(self.body)
        chip.pack(fill="x")
        ttk.Label(chip, text="Plik:", style="Muted.TLabel").pack(side="left")
        ttk.Label(chip, text=os.path.basename(path), style="Mono.TLabel").pack(side="left", padx=(6, 0))
        ttk.Label(self.body, text=os.path.dirname(path), style="Small.TLabel", wraplength=360).pack(anchor="w")
        ttk.Label(self.body, text="Hasło główne", style="Field.TLabel").pack(anchor="w", pady=(16, 4))
        self.pw = tk.StringVar()
        self.pw_entry = ttk.Entry(self.body, textvariable=self.pw, show="•", width=40)
        self.pw_entry.pack(fill="x")
        self.pw_entry.bind("<Return>", lambda e: self.unlock())
        self.pw.trace_add("write", lambda *a: self.err.configure(text="") if self.err.cget("text") and not self.message else None)
        self.show_pw = tk.BooleanVar()
        ttk.Checkbutton(self.body, text="Pokaż hasło", variable=self.show_pw,
                        command=lambda: self.pw_entry.configure(show="" if self.show_pw.get() else "•")).pack(anchor="w", pady=(6, 0))
        self.err = ttk.Label(self.body, text=self.message, style="Error.TLabel", wraplength=360)
        self.err.pack(fill="x", pady=(6, 0))
        self.btn = ttk.Button(self.body, text="Odblokuj", style="Accent.TButton", command=self.unlock)
        self.btn.pack(fill="x", pady=(8, 0), ipady=3)
        links = ttk.Frame(self.body)
        links.pack(fill="x", pady=(10, 0))
        ttk.Button(links, text="Inny plik…", command=self.pick_file).pack(side="left")
        ttk.Button(links, text="Nowy sejf…", command=self.show_create).pack(side="right")
        self.after(50, self.pw_entry.focus_set)

    def unlock(self):
        if not self.pw.get():
            self.err.configure(text="Wpisz hasło główne.")
            return
        self.err.configure(text="")
        self.btn.configure(text="Odblokowuję…", state="disabled")
        path, pw = self.app.last_path, self.pw.get()

        def fail(e):
            if not self.winfo_exists():
                return
            msg = str(e) if isinstance(e, crypto.VaultError) else f"Nie udało się otworzyć pliku: {e}"
            if isinstance(e, FileNotFoundError):
                msg = "Nie ma już tego pliku. Wybierz inny plik sejfu."
            self.err.configure(text=msg)
            self.btn.configure(text="Odblokuj", state="normal")
            self.pw_entry.select_range(0, "end")
            self.pw_entry.focus_set()

        self.app.run_bg(lambda: self.app.s.unlock(path, pw), lambda _: self.app.enter_main(), fail)

    # --- nowy sejf --------------------------------------------------------------
    def show_create(self):
        self._clear()
        ttk.Label(self.body, text="Nowy sejf", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.body, text="Hasło główne", style="Field.TLabel").pack(anchor="w", pady=(12, 4))
        self.n1, self.n2 = tk.StringVar(), tk.StringVar()
        e1 = ttk.Entry(self.body, textvariable=self.n1, show="•", width=40)
        e1.pack(fill="x")
        self.meter = StrengthBar(self.body, self.app, "Co najmniej 8 znaków. Najlepiej kilka słów.")
        self.meter.pack(anchor="w", pady=(6, 0))
        self.n1.trace_add("write", lambda *a: (self.meter.set(self.n1.get()), self.err.configure(text="")))
        ttk.Label(self.body, text="Powtórz hasło główne", style="Field.TLabel").pack(anchor="w", pady=(12, 4))
        e2 = ttk.Entry(self.body, textvariable=self.n2, show="•", width=40)
        e2.pack(fill="x")
        e2.bind("<Return>", lambda e: self.create())
        self.n2.trace_add("write", lambda *a: self.err.configure(text=""))
        self.err = ttk.Label(self.body, text="", style="Error.TLabel", wraplength=360)
        self.err.pack(fill="x", pady=(6, 0))
        self._note("Hasła głównego nie da się odzyskać. Jeśli je zapomnisz, stracisz dostęp do wszystkich haseł "
                   "w sejfie.", style="Warn.TLabel")
        self.btn = ttk.Button(self.body, text="Wybierz miejsce i utwórz sejf…", style="Accent.TButton", command=self.create)
        self.btn.pack(fill="x", pady=(14, 0), ipady=3)
        ttk.Button(self.body, text="Wróć", command=self.show_unlock if self.app.last_path else self.show_home).pack(anchor="w", pady=(10, 0))
        self.after(50, e1.focus_set)

    def create(self):
        problem = Session.check_new_password(self.n1.get(), self.n2.get())
        if problem:
            self.err.configure(text=problem)
            return
        path = filedialog.asksaveasfilename(parent=self.app.root, title="Gdzie zapisać plik sejfu?",
                                            initialfile="hasla.sejf.json", defaultextension=".json",
                                            filetypes=VAULT_TYPES, initialdir=cloud_folder())
        if not path:
            return
        self.app.create_vault(path, self.n1.get(), self)

    def create_failed(self, e):
        self.err.configure(text=f"Nie udało się utworzyć pliku: {e}")
        self.btn.configure(text="Wybierz miejsce i utwórz sejf…", state="normal")


# =============================================================================
class MainView(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.kind, self.value = "all", ""
        self._updating = False

        bar = ttk.Frame(self, padding=(14, 12, 14, 10))
        bar.pack(fill="x")
        ttk.Button(bar, text="＋ Nowy wpis", style="Accent.TButton", command=self.new_entry).pack(side="left")
        ttk.Button(bar, text="Generator haseł", command=app.open_generator).pack(side="left", padx=(8, 0))
        ttk.Label(bar, text="Szukaj", style="Muted.TLabel").pack(side="left", padx=(22, 6))
        self.search = tk.StringVar()
        self.search_entry = ttk.Entry(bar, textvariable=self.search, width=34)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search.trace_add("write", lambda *a: self.refresh_list())
        ttk.Button(bar, text="Zablokuj", command=app.lock).pack(side="right")
        ttk.Button(bar, text="Ustawienia", command=app.open_settings).pack(side="right", padx=(8, 8))
        ttk.Button(bar, text="Eksport…", command=app.open_export).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="Import…", command=app.open_import).pack(side="right", padx=(22, 0))

        self.status = ttk.Label(self, style="Muted.TLabel", padding=(16, 6, 16, 8))
        self.status.pack(side="bottom", fill="x")

        self.paned = ttk.PanedWindow(self, orient="horizontal")
        self.paned.pack(fill="both", expand=True, padx=14)

        # filtry
        nav_box = ttk.Frame(self.paned)
        self.nav = ttk.Treeview(nav_box, show="tree", selectmode="browse")
        self.nav.pack(fill="both", expand=True)
        nb = ttk.Frame(nav_box)
        nb.pack(fill="x", pady=(6, 0))
        ttk.Button(nb, text="＋ Kategoria", command=self.add_category).pack(side="left")
        self.nav.bind("<<TreeviewSelect>>", self.on_nav)
        self.nav.bind("<Button-3>", self.nav_menu)
        self.paned.add(nav_box, weight=0)

        # lista
        list_box = ttk.Frame(self.paned)
        lh = ttk.Frame(list_box)
        lh.pack(side="top", fill="x", pady=(0, 6))
        self.list_title = ttk.Label(lh, style="Strong.TLabel")
        self.list_title.pack(side="left")
        self.list_count = ttk.Label(lh, style="Muted.TLabel")
        self.list_count.pack(side="right")
        self.list = ttk.Treeview(list_box, columns=("title", "user", "cat"), show="headings", selectmode="browse")
        for col, text, w in (("title", "Nazwa", 200), ("user", "Login", 170), ("cat", "Kategoria", 120)):
            self.list.heading(col, text=text, anchor="w")
            self.list.column(col, width=w, minwidth=60, anchor="w", stretch=True)
        sb = ttk.Scrollbar(list_box, orient="vertical", command=self.list.yview)
        self.list.configure(yscrollcommand=sb.set)
        self.list.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.list.bind("<<TreeviewSelect>>", self.on_select)
        self.list.bind("<Double-1>", lambda e: self.copy_selected("password"))
        self.list.bind("<Control-c>", lambda e: self.copy_selected("password"))
        self.list.bind("<Control-b>", lambda e: self.copy_selected("username"))
        self.list.bind("<Return>", lambda e: self.detail.edit(self.selected()) if self.selected() else None)
        self.list.bind("<Delete>", lambda e: self.delete(self.selected()) if self.selected() else None)
        self.list.bind("<Button-3>", self.list_menu)
        self.paned.add(list_box, weight=1)

        self.detail = DetailPanel(self.paned, app, self)
        self.paned.add(self.detail, weight=2)
        self.after(30, self._init_sashes)
        self.refresh()

    def _init_sashes(self):
        try:
            w = self.paned.winfo_width()
            left = self.app.px(210)
            self.paned.sashpos(0, left)
            self.paned.sashpos(1, left + max(self.app.px(300), int((w - left) * 0.42)))
        except tk.TclError:
            pass

    # --- dane --------------------------------------------------------------------
    @property
    def data(self):
        return self.app.s.data

    def entry(self, eid):
        return next((e for e in self.data["entries"] if e["id"] == eid), None)

    def selected(self):
        sel = self.list.selection()
        return self.entry(sel[0]) if sel else None

    def refresh(self, keep_detail: bool = False):
        self.refresh_nav()
        self.refresh_list(keep_detail=keep_detail)

    def refresh_nav(self):
        self._updating = True
        n = self.nav
        n.delete(*n.get_children())
        E = self.data["entries"]
        n.insert("", "end", iid="all", text=f"Wszystkie  ({len(E)})")
        n.insert("", "end", iid="fav", text=f"★ Ulubione  ({sum(e['fav'] for e in E)})")
        n.insert("", "end", iid="cats", text="Kategorie", open=True)
        for c in vault.categories(self.data):
            n.insert("cats", "end", iid="cat:" + c, text=f"{c}  ({sum(e['category'] == c for e in E)})")
        none = sum(not e["category"] for e in E)
        if none:
            n.insert("cats", "end", iid="none", text=f"Bez kategorii  ({none})")
        tags = vault.tag_counts(self.data)
        if tags:
            n.insert("", "end", iid="tags", text="Tagi", open=True)
            for t, k in tags:
                n.insert("tags", "end", iid="tag:" + t, text=f"#{t}  ({k})")
        iid = {"all": "all", "fav": "fav", "none": "none"}.get(self.kind) or f"{self.kind}:{self.value}"
        if not n.exists(iid):
            self.kind, self.value, iid = "all", "", "all"
        n.selection_set(iid)
        n.see(iid)
        self._updating = False

    def refresh_list(self, keep_detail: bool = True):
        current = self.list.selection()
        current = current[0] if current else None
        items = vault.filter_entries(self.data, self.kind, self.value, self.search.get())
        self.list.delete(*self.list.get_children())
        for e in items:
            self.list.insert("", "end", iid=e["id"], values=(("★ " if e["fav"] else "") + e["title"],
                                                             e["username"], e["category"] or "—"))
        if current and self.list.exists(current):
            self.list.selection_set(current)
            self.list.see(current)
        elif not self.detail.editing:
            self.detail.show_empty(len(items))
        title = {"all": "Wszystkie", "fav": "Ulubione", "none": "Bez kategorii"}.get(self.kind, self.value)
        if self.kind == "tag":
            title = "#" + self.value
        self.list_title.configure(text=title)
        self.list_count.configure(text=vault.wpisy(len(items)))
        if keep_detail and self.detail.editing is None and current and self.list.exists(current):
            self.detail.show(self.entry(current))

    def on_nav(self, _e=None):
        if self._updating:
            return
        sel = self.nav.selection()
        if not sel or sel[0] in ("cats", "tags"):
            return
        iid = sel[0]
        if ":" in iid:
            self.kind, self.value = iid.split(":", 1)
        else:
            self.kind, self.value = iid, ""
        self.refresh_list(keep_detail=False)

    def on_select(self, _e=None):
        e = self.selected()
        if e and (self.detail.editing is None or self.detail.editing.get("id") != e["id"]):
            if self.detail.editing is not None and not self.detail.confirm_discard():
                return
            self.detail.show(e)

    def select(self, eid):
        if self.list.exists(eid):
            self.list.selection_set(eid)
            self.list.see(eid)
            self.detail.show(self.entry(eid))

    # --- akcje -----------------------------------------------------------------
    def new_entry(self):
        if self.detail.editing is not None and not self.detail.confirm_discard():
            return
        self.list.selection_remove(*self.list.selection())
        cat = self.value if self.kind == "cat" else ""
        tags = [self.value] if self.kind == "tag" else []
        self.detail.edit(None, defaults={"category": cat, "tags": tags, "fav": self.kind == "fav"})

    def copy_selected(self, field):
        e = self.selected()
        if e and e[field]:
            self.app.copy(e[field], "hasło" if field == "password" else "login", secret=field == "password")
        return "break"

    def delete(self, e):
        if not e:
            return
        if messagebox.askyesno("Usuń wpis", f"Usunąć wpis „{e['title']}”?\n\nTej operacji nie da się cofnąć.",
                               icon="warning", parent=self.app.root):
            self.data["entries"] = [x for x in self.data["entries"] if x["id"] != e["id"]]
            self.detail.editing = None
            self.app.changed()
            self.refresh()
            self.detail.show_empty(len(self.list.get_children()))
            self.app.flash("Usunięto wpis.")

    def toggle_fav(self, e):
        e["fav"] = not e["fav"]
        self.app.changed()
        self.refresh()
        self.select(e["id"])

    def add_category(self):
        name = self.app.ask_string("Nowa kategoria", "Nazwa kategorii")
        if name and name not in vault.categories(self.data):
            self.data["categories"].append(name)
            self.app.changed()
            self.refresh_nav()

    def remove_category(self, name):
        self.data["categories"] = [c for c in self.data["categories"] if c != name]
        if self.kind == "cat" and self.value == name:
            self.kind, self.value = "all", ""
        self.app.changed()
        self.refresh()

    def nav_menu(self, ev):
        iid = self.nav.identify_row(ev.y)
        m = tk.Menu(self, tearoff=False)
        m.add_command(label="Dodaj kategorię…", command=self.add_category)
        if iid.startswith("cat:"):
            name = iid[4:]
            used = any(e["category"] == name for e in self.data["entries"])
            m.add_command(label=f"Usuń kategorię „{name}”", state="disabled" if used else "normal",
                          command=lambda: self.remove_category(name))
        m.tk_popup(ev.x_root, ev.y_root)

    def list_menu(self, ev):
        iid = self.list.identify_row(ev.y)
        if not iid:
            return
        self.list.selection_set(iid)
        e = self.entry(iid)
        m = tk.Menu(self, tearoff=False)
        m.add_command(label="Kopiuj hasło", accelerator="Ctrl+C", command=lambda: self.copy_selected("password"))
        m.add_command(label="Kopiuj login", accelerator="Ctrl+B", command=lambda: self.copy_selected("username"))
        href = vault.safe_href(e["url"])
        m.add_command(label="Otwórz stronę", state="normal" if href else "disabled", command=lambda: webbrowser.open(href))
        m.add_separator()
        m.add_command(label="Edytuj", command=lambda: self.detail.edit(e))
        m.add_command(label="Usuń…", command=lambda: self.delete(e))
        m.tk_popup(ev.x_root, ev.y_root)


# =============================================================================
class DetailPanel(ttk.Frame):
    def __init__(self, master, app, main):
        super().__init__(master, padding=(22, 4, 8, 8))
        self.app, self.main = app, main
        self.editing: dict | None = None
        self.form: dict = {}

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    # --- pusty widok -------------------------------------------------------------
    def show_empty(self, count: int | None = None):
        self.editing = None
        self._clear()
        box = ttk.Frame(self)
        box.place(relx=0.5, rely=0.4, anchor="center")
        ttk.Label(box, image=self.app.icon).pack()
        total = len(self.app.s.data["entries"])
        if total:
            ttk.Label(box, text="Wybierz wpis z listy", style="Title.TLabel").pack(pady=(12, 4))
            ttk.Label(box, text=f"W sejfie: {vault.wpisy(total)}.\nDwuklik na wpisie kopiuje hasło.",
                      style="Muted.TLabel", justify="center").pack()
        else:
            ttk.Label(box, text="Sejf jest pusty", style="Title.TLabel").pack(pady=(12, 4))
            ttk.Label(box, text="Dodaj pierwsze hasło albo przenieś hasła\nzapisane w przeglądarce.",
                      style="Muted.TLabel", justify="center").pack()
            row = ttk.Frame(box)
            row.pack(pady=(14, 0))
            ttk.Button(row, text="＋ Dodaj wpis", style="Accent.TButton", command=self.main.new_entry).pack(side="left")
            ttk.Button(row, text="Importuj z przeglądarki…", command=self.app.open_import).pack(side="left", padx=(8, 0))

    # --- podgląd wpisu -----------------------------------------------------------
    def show(self, e: dict):
        if e is None:
            self.show_empty()
            return
        self.editing = None
        self._clear()
        c = self.app.colors
        head = ttk.Frame(self)
        head.pack(fill="x", pady=(10, 0))
        txt = ttk.Frame(head)
        txt.pack(side="left", fill="x", expand=True)
        ttk.Label(txt, text=e["title"], style="Title.TLabel", wraplength=420).pack(anchor="w")
        ttk.Label(txt, text=e["category"] or "Bez kategorii", style="Muted.TLabel").pack(anchor="w")
        acts = ttk.Frame(head)
        acts.pack(side="right", anchor="n")
        ttk.Button(acts, text="★ W ulubionych" if e["fav"] else "☆ Do ulubionych",
                   command=lambda: self.main.toggle_fav(e)).pack(side="left")
        ttk.Button(acts, text="Edytuj", command=lambda: self.edit(e)).pack(side="left", padx=(6, 0))
        ttk.Button(acts, text="Usuń…", command=lambda: self.main.delete(e)).pack(side="left", padx=(6, 0))

        grid = ttk.Frame(self)
        grid.pack(fill="x", pady=(18, 0))
        grid.columnconfigure(1, weight=1)
        row = 0

        def field(label, value, buttons=(), secret=False):
            nonlocal row
            ttk.Label(grid, text=label.upper(), style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=6, padx=(0, 14))
            ent = ttk.Entry(grid, font=self.app.mono, show="•" if secret and value else "")
            ent.insert(0, value or "—")
            ent.configure(state="readonly")
            ent.grid(row=row, column=1, sticky="ew", pady=6)
            bf = ttk.Frame(grid)
            bf.grid(row=row, column=2, sticky="e", padx=(8, 0))
            btns = []
            for text, cmd in buttons:
                btn = ttk.Button(bf, text=text, command=cmd)
                btn.pack(side="left", padx=(4, 0))
                btns.append(btn)
            row += 1
            return ent, btns

        field("Login", e["username"], [("Kopiuj", lambda: self.app.copy(e["username"], "login"))] if e["username"] else ())
        pw_ent = show_btn = None

        def toggle():
            shown = pw_ent.cget("show") == ""
            pw_ent.configure(show="•" if shown else "")
            show_btn.configure(text="Pokaż" if shown else "Ukryj")

        if e["password"]:
            pw_ent, (show_btn, _) = field("Hasło", e["password"], [("Pokaż", toggle), ("Kopiuj", lambda: self.app.copy(e["password"], "hasło", secret=True))], secret=True)
            meter = StrengthBar(grid, self.app)
            meter.set(e["password"])
            meter.grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 4))
            row += 1
            reused = vault.reused_by(self.app.s.data, e)
            if reused:
                ttk.Label(grid, text="⚠ To samo hasło jest też w: " + ", ".join(x["title"] for x in reused[:5]) +
                          ". Lepiej mieć osobne hasło do każdego konta.", style="Warn.TLabel", wraplength=420,
                          justify="left").grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 6))
                row += 1
        else:
            field("Hasło", "")
        href = vault.safe_href(e["url"])
        field("Adres", e["url"], [("Otwórz", lambda: webbrowser.open(href)), ("Kopiuj", lambda: self.app.copy(e["url"], "adres"))] if href else ())
        if e["tags"]:
            ttk.Label(grid, text="TAGI", style="Field.TLabel").grid(row=row, column=0, sticky="w", pady=6)
            ttk.Label(grid, text="   ".join("#" + t for t in e["tags"])).grid(row=row, column=1, sticky="w", pady=6)
            row += 1
        if e["notes"]:
            ttk.Label(grid, text="NOTATKI", style="Field.TLabel").grid(row=row, column=0, sticky="nw", pady=6)
            t = tk.Text(grid, height=min(8, e["notes"].count("\n") + 2), wrap="word", relief="flat", bd=0,
                        padx=8, pady=6, bg=c["text_bg"], fg=c["text_fg"], font=self.app.base_font,
                        highlightthickness=0)
            t.insert("1.0", e["notes"])
            t.configure(state="disabled")
            t.grid(row=row, column=1, columnspan=2, sticky="ew", pady=6)
            row += 1

        foot = ttk.Frame(self)
        foot.pack(fill="x", pady=(14, 0))
        ttk.Label(foot, text=f"Utworzono: {vault.fmt_date(e['created'])}     Zmieniono: {vault.fmt_date(e['updated'])}",
                  style="Muted.TLabel").pack(side="left")
        if e["history"]:
            ttk.Button(foot, text=f"Poprzednie hasła ({len(e['history'])})…",
                       command=lambda: self.app.open_history(e)).pack(side="right")

    # --- edycja ------------------------------------------------------------------
    def edit(self, e: dict | None, defaults: dict | None = None):
        src = e or {"title": "", "username": "", "password": "", "url": "", "notes": "", "category": "",
                    "tags": [], "fav": False, **(defaults or {})}
        self.editing = {"id": e["id"] if e else None}
        self._clear()
        ttk.Label(self, text="Edycja wpisu" if e else "Nowy wpis", style="Title.TLabel").pack(anchor="w", pady=(10, 12))
        g = ttk.Frame(self)
        g.pack(fill="x")
        g.columnconfigure(0, weight=1)
        g.columnconfigure(1, weight=1)
        f = self.form = {
            "title": tk.StringVar(value=src["title"]), "username": tk.StringVar(value=src["username"]),
            "url": tk.StringVar(value=src["url"]), "password": tk.StringVar(value=src["password"]),
            "category": tk.StringVar(value=src["category"]), "tags": tk.StringVar(value=", ".join(src["tags"])),
            "fav": tk.BooleanVar(value=src["fav"]),
        }

        def lab(text, r, c):
            ttk.Label(g, text=text, style="Field.TLabel").grid(row=r, column=c, sticky="w", pady=(8, 3), padx=(0 if c == 0 else 8, 0))

        lab("NAZWA", 0, 0)
        title = ttk.Entry(g, textvariable=f["title"])
        title.grid(row=1, column=0, columnspan=2, sticky="ew")
        lab("LOGIN LUB E-MAIL", 2, 0)
        lab("ADRES STRONY", 2, 1)
        ttk.Entry(g, textvariable=f["username"]).grid(row=3, column=0, sticky="ew")
        ttk.Entry(g, textvariable=f["url"]).grid(row=3, column=1, sticky="ew", padx=(8, 0))
        lab("HASŁO", 4, 0)
        pr = ttk.Frame(g)
        pr.grid(row=5, column=0, columnspan=2, sticky="ew")
        pw = ttk.Entry(pr, textvariable=f["password"], show="•", font=self.app.mono)
        pw.pack(side="left", fill="x", expand=True)
        show = tk.BooleanVar()
        ttk.Checkbutton(pr, text="Pokaż", variable=show, command=lambda: pw.configure(show="" if show.get() else "•")).pack(side="left", padx=(8, 0))

        def use(v):
            f["password"].set(v)
            show.set(True)
            pw.configure(show="")

        ttk.Button(pr, text="Generuj…", command=lambda: self.app.open_generator(use)).pack(side="left", padx=(8, 0))
        meter = StrengthBar(g, self.app, "Wpisz hasło albo wygeneruj losowe.")
        meter.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        meter.set(src["password"])
        f["password"].trace_add("write", lambda *a: meter.set(f["password"].get()))
        lab("KATEGORIA", 7, 0)
        lab("TAGI (ODDZIEL PRZECINKAMI)", 7, 1)
        ttk.Combobox(g, textvariable=f["category"], values=vault.categories(self.app.s.data)).grid(row=8, column=0, sticky="ew")
        ttk.Entry(g, textvariable=f["tags"]).grid(row=8, column=1, sticky="ew", padx=(8, 0))
        lab("NOTATKI", 9, 0)
        c = self.app.colors
        self.notes = tk.Text(g, height=6, wrap="word", relief="flat", bd=0, padx=8, pady=6, bg=c["text_bg"],
                             fg=c["text_fg"], insertbackground=c["text_fg"], font=self.app.base_font,
                             highlightthickness=1, highlightbackground=c["empty"], highlightcolor=c["muted"])
        self.notes.insert("1.0", src["notes"])
        self.notes.grid(row=10, column=0, columnspan=2, sticky="ew")
        ttk.Checkbutton(g, text="Dodaj do ulubionych", variable=f["fav"]).grid(row=11, column=0, sticky="w", pady=(10, 0))
        self.form_error = ttk.Label(g, style="Error.TLabel")
        self.form_error.grid(row=12, column=0, columnspan=2, sticky="w")
        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Zapisz", style="Accent.TButton", command=self.save).pack(side="left")
        ttk.Button(btns, text="Anuluj", command=self.cancel).pack(side="left", padx=(8, 0))
        ttk.Label(btns, text="Ctrl+S zapisuje, Esc anuluje", style="Muted.TLabel").pack(side="right")
        for w in (title, pw):
            w.bind("<Return>", lambda ev: self.save())
        self.bind_all_form()
        self.after(30, title.focus_set)

    def bind_all_form(self):
        root = self.app.root
        root.bind("<Control-s>", lambda ev: self.save() if self.editing is not None else None)
        root.bind("<Escape>", lambda ev: self.cancel() if self.editing is not None and not self.app.dialogs else None)

    def values(self) -> dict:
        f = self.form
        url = f["url"].get().strip()
        return {
            "title": f["title"].get().strip() or vault.host_of(url) or f["username"].get().strip() or "Bez nazwy",
            "username": f["username"].get().strip(), "password": f["password"].get(), "url": url,
            "category": f["category"].get().strip(), "tags": vault.parse_tags(f["tags"].get()),
            "notes": self.notes.get("1.0", "end-1c"), "fav": bool(f["fav"].get()),
        }

    def save(self):
        if self.editing is None:
            return
        data = self.app.s.data
        vals = self.values()
        eid = self.editing["id"]
        if eid:
            e = self.main.entry(eid)
            vault.update_entry(e, vals)
        else:
            e = vault.new_entry(**vals)
            data["entries"].append(e)
        if vals["category"] and vals["category"] not in data["categories"]:
            data["categories"].append(vals["category"])
        self.editing = None
        self.app.changed()
        self.main.refresh()
        if not self.main.list.exists(e["id"]):
            self.main.kind, self.main.value = "all", ""
            self.main.search.set("")
            self.main.refresh()
        self.main.select(e["id"])
        self.app.flash("Zapisano wpis.")

    def cancel(self):
        if self.editing is None:
            return
        eid = self.editing["id"]
        self.editing = None
        if eid and self.main.entry(eid):
            self.main.select(eid)
            self.show(self.main.entry(eid))
        else:
            self.show_empty()

    def confirm_discard(self) -> bool:
        if messagebox.askyesno("Niezapisane zmiany", "Porzucić zmiany w edytowanym wpisie?", parent=self.app.root):
            self.editing = None
            return True
        return False


# =============================================================================
class GeneratorDialog(Dialog):
    def __init__(self, app, use_cb=None):
        super().__init__(app, "Generator haseł")
        self.use_cb = use_cb
        s = app.s.data["settings"]["gen"] if app.s.unlocked else {}
        b = self.body
        self.out = tk.StringVar()
        row = ttk.Frame(b)
        row.pack(fill="x")
        self.entry = ttk.Entry(row, textvariable=self.out, state="readonly", font=app.mono_big, width=34)
        self.entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Losuj", command=self.regen).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Kopiuj", command=self.copy).pack(side="left", padx=(6, 0))
        self.meter = StrengthBar(b, app)
        self.meter.pack(anchor="w", pady=(8, 0))
        lr = ttk.Frame(b)
        lr.pack(fill="x", pady=(18, 0))
        ttk.Label(lr, text="Długość", style="Field.TLabel").pack(side="left")
        self.length = tk.IntVar(value=int(s.get("length", 20)))
        self.len_label = ttk.Label(lr, width=3, anchor="e", font=app.mono)
        self.len_label.pack(side="right")
        ttk.Scale(lr, from_=8, to=64, variable=self.length, command=lambda v: self.regen()).pack(side="left", fill="x", expand=True, padx=12)
        opts = ttk.Frame(b)
        opts.pack(fill="x", pady=(14, 0))
        self.vars = {}
        for i, (key, text) in enumerate((("lower", "małe litery a–z"), ("upper", "wielkie litery A–Z"),
                                          ("digits", "cyfry 0–9"), ("symbols", "znaki specjalne !@#"),
                                          ("noAmb", "bez podobnych znaków (l, 1, O, 0)"))):
            v = tk.BooleanVar(value=bool(s.get(key, key != "noAmb")))
            self.vars[key] = v
            ttk.Checkbutton(opts, text=text, variable=v, command=self.regen).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 24), pady=3)
        bt = ttk.Frame(b)
        bt.pack(fill="x", pady=(20, 0))
        if use_cb:
            ttk.Button(bt, text="Użyj tego hasła", style="Accent.TButton", command=self.use).pack(side="left")
        ttk.Button(bt, text="Zamknij", command=self.close).pack(side="right")
        self.regen()

    def options(self):
        return {"length": int(round(self.length.get())), **{k: v.get() for k, v in self.vars.items()}}

    def regen(self):
        o = self.options()
        self.len_label.configure(text=str(o["length"]))
        pw = generate(**o)
        self.out.set(pw or "Zaznacz rodzaj znaków")
        self.meter.set(pw)
        if self.app.s.unlocked and self.app.s.data["settings"].get("gen") != o:
            self.app.s.data["settings"]["gen"] = o
            self.app.changed()

    def copy(self):
        if self.out.get() and not self.out.get().startswith("Zaznacz"):
            self.app.copy(self.out.get(), "hasło", secret=True)

    def use(self):
        v = self.out.get()
        if v and not v.startswith("Zaznacz"):
            self.use_cb(v)
            self.close()


class ImportDialog(Dialog):
    def __init__(self, app, preview: ImportPreview):
        super().__init__(app, "Import haseł")
        self.preview = preview
        b = self.body
        ttk.Label(b, text="Import z pliku CSV", style="Title.TLabel").pack(anchor="w")
        box, info = app.card(b, 14)
        box.pack(fill="x", pady=(12, 0))
        dups = preview.found - len(preview.fresh)
        lines = [("Plik", os.path.basename(preview.path)), ("Format", preview.fmt),
                 ("Znaleziono", vault.wpisy(preview.found))]
        if dups:
            lines.append(("Pominę powtórzenia", str(dups)))
        lines.append(("Do dodania", vault.wpisy(len(preview.fresh))))
        for i, (k, v) in enumerate(lines):
            ttk.Label(info, text=k, style="Muted.TLabel").grid(row=i, column=0, sticky="w", padx=(0, 18), pady=1)
            ttk.Label(info, text=v, style="Strong.TLabel").grid(row=i, column=1, sticky="w", pady=1)
        self.cat = tk.StringVar(value="Zaimportowane")
        if any(not e["category"] for e in preview.fresh):
            ttk.Label(b, text="KATEGORIA DLA WPISÓW BEZ KATEGORII", style="Field.TLabel").pack(anchor="w", pady=(16, 4))
            ttk.Combobox(b, textvariable=self.cat, values=vault.categories(app.s.data)).pack(fill="x")
        ttk.Label(b, text="Po imporcie usuń plik CSV z dysku. Nie jest zaszyfrowany i każdy, kto go otworzy, "
                          "zobaczy Twoje hasła.", style="Warn.TLabel", wraplength=420, justify="left").pack(fill="x", pady=(14, 0))
        bt = ttk.Frame(b)
        bt.pack(fill="x", pady=(18, 0))
        go = ttk.Button(bt, text=f"Importuj {vault.wpisy(len(preview.fresh))}", style="Accent.TButton", command=self.go)
        go.pack(side="left")
        if not preview.fresh:
            go.configure(state="disabled")
        ttk.Button(bt, text="Anuluj", command=self.close).pack(side="right")

    def go(self):
        n = self.app.apply_import(self.preview.fresh, self.cat.get().strip())
        self.close()
        messagebox.showinfo("Import zakończony", f"Zaimportowano {vault.wpisy(n)}.\n\nUsuń teraz plik CSV z dysku.",
                            parent=self.app.root)


class ExportDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, "Eksport i kopia zapasowa")
        b = self.body
        for title, text, btn, cmd, style in (
            ("Zaszyfrowana kopia zapasowa", "Kopia całego sejfu chroniona tym samym hasłem głównym.\n"
             "Trzymaj ją np. na pendrivie, poza chmurą.", "Zapisz kopię…", app.export_backup, "Accent.TButton"),
            ("Plik CSV bez szyfrowania", "Do przeniesienia haseł do innego programu. Każdy, kto otworzy\n"
             "ten plik, zobaczy wszystkie hasła.", "Zapisz CSV…", app.export_csv, "TButton"),
        ):
            box, card = app.card(b, 16)
            box.pack(fill="x", pady=(0, 12))
            ttk.Label(card, text=title, style="Strong.TLabel").pack(anchor="w")
            ttk.Label(card, text=text, style="Muted.TLabel", justify="left").pack(anchor="w", pady=(4, 10))
            ttk.Button(card, text=btn, style=style, command=lambda c=cmd: (self.close(), c())).pack(anchor="w")
        ttk.Button(b, text="Zamknij", command=self.close).pack(anchor="e")


class SettingsDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, "Ustawienia")
        b = self.body
        st = app.s.data["settings"]

        def combo(label, choices, current, on_change):
            ttk.Label(b, text=label, style="Field.TLabel").pack(anchor="w", pady=(0, 4))
            names = [n for n, _ in choices]
            var = tk.StringVar(value=next((n for n, v in choices if v == current), names[0]))
            cb = ttk.Combobox(b, textvariable=var, values=names, state="readonly", width=30)
            cb.pack(anchor="w", pady=(0, 14))
            cb.bind("<<ComboboxSelected>>", lambda e: on_change(dict(choices)[var.get()]))
            return cb

        def set_lock(v):
            st["autoLockMin"] = v
            app.changed()

        def set_clip(v):
            st["clipSec"] = v
            app.changed()

        combo("BLOKUJ SEJF PO BEZCZYNNOŚCI", LOCK_CHOICES, st["autoLockMin"], set_lock)
        combo("CZYŚĆ SKOPIOWANE HASŁO ZE SCHOWKA PO", CLIP_CHOICES, st["clipSec"], set_clip)
        combo("MOTYW", THEME_CHOICES, app.cfg.get("theme", "system"), lambda v: app.after_dialog(lambda: app.set_theme(v)))
        ttk.Separator(b).pack(fill="x", pady=(4, 14))
        ttk.Label(b, text="Zmiana hasła głównego", style="Strong.TLabel").pack(anchor="w")
        self.cur, self.n1, self.n2 = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for label, var in (("OBECNE HASŁO GŁÓWNE", self.cur), ("NOWE HASŁO GŁÓWNE", self.n1)):
            ttk.Label(b, text=label, style="Field.TLabel").pack(anchor="w", pady=(10, 4))
            ttk.Entry(b, textvariable=var, show="•", width=40).pack(fill="x")
        self.meter = StrengthBar(b, app)
        self.meter.pack(anchor="w", pady=(6, 0))
        self.n1.trace_add("write", lambda *a: self.meter.set(self.n1.get()))
        ttk.Label(b, text="POWTÓRZ NOWE HASŁO", style="Field.TLabel").pack(anchor="w", pady=(10, 4))
        ttk.Entry(b, textvariable=self.n2, show="•", width=40).pack(fill="x")
        self.err = ttk.Label(b, style="Error.TLabel", wraplength=380)
        self.err.pack(anchor="w", pady=(6, 0))
        bt = ttk.Frame(b)
        bt.pack(fill="x", pady=(10, 0))
        self.btn = ttk.Button(bt, text="Zmień hasło główne", command=self.change)
        self.btn.pack(side="left")
        ttk.Button(bt, text="Zamknij", command=self.close).pack(side="right")
        ttk.Label(b, text=f"Sejf {__version__}", style="Muted.TLabel").pack(anchor="w", pady=(16, 0))

    def change(self):
        problem = Session.check_new_password(self.n1.get(), self.n2.get())
        if problem:
            self.err.configure(text=problem)
            return
        self.err.configure(text="")
        self.btn.configure(text="Zmieniam…", state="disabled")
        cur, new = self.cur.get(), self.n1.get()
        self.app.flush_save()

        def done(_):
            self.app.saved_at = time.localtime()
            self.app.refresh_status()
            self.close()
            messagebox.showinfo("Hasło główne", "Zmieniono hasło główne.", parent=self.app.root)

        def fail(e):
            if self.winfo_exists():
                self.err.configure(text=str(e))
                self.btn.configure(text="Zmień hasło główne", state="normal")

        self.app.run_bg(lambda: self.app.s.change_password(cur, new), done, fail)


class HistoryDialog(Dialog):
    def __init__(self, app, e):
        super().__init__(app, "Poprzednie hasła")
        b = self.body
        ttk.Label(b, text=e["title"], style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        for h in e["history"]:
            r = ttk.Frame(b)
            r.pack(fill="x", pady=3)
            ent = ttk.Entry(r, font=app.mono, width=30)
            ent.insert(0, h["password"])
            ent.configure(state="readonly")
            ent.pack(side="left")
            ttk.Label(r, text=vault.fmt_date(h.get("changed", "")), style="Muted.TLabel").pack(side="left", padx=10)
            ttk.Button(r, text="Kopiuj", command=lambda p=h["password"]: app.copy(p, "hasło", secret=True)).pack(side="right")
        ttk.Button(b, text="Zamknij", command=self.close).pack(anchor="e", pady=(14, 0))


class ConflictDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, "Plik zmienił się na innym urządzeniu")
        b = self.body
        ttk.Label(b, text="Plik sejfu zmienił się na innym urządzeniu", style="Title.TLabel").pack(anchor="w")
        ttk.Label(b, text="Ktoś (albo Ty na telefonie) zapisał nowszą wersję pliku, a tutaj też są niezapisane "
                          "zmiany. Wybierz, którą wersję zachować.", wraplength=420, justify="left").pack(anchor="w", pady=(8, 16))
        bt = ttk.Frame(b)
        bt.pack(fill="x")
        ttk.Button(bt, text="Zachowaj moją wersję", style="Accent.TButton", command=lambda: self.pick("mine")).pack(side="left")
        ttk.Button(bt, text="Wczytaj wersję z pliku", command=lambda: self.pick("file")).pack(side="left", padx=(8, 0))
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.unbind("<Escape>")

    def pick(self, which):
        self.close()
        self.app.resolve_conflict(which)


class AskStringDialog(Dialog):
    def __init__(self, app, title, label):
        super().__init__(app, title)
        self.result = None
        self.var = tk.StringVar()
        ttk.Label(self.body, text=label.upper(), style="Field.TLabel").pack(anchor="w", pady=(0, 4))
        e = ttk.Entry(self.body, textvariable=self.var, width=36)
        e.pack(fill="x")
        e.bind("<Return>", lambda ev: self.ok())
        bt = ttk.Frame(self.body)
        bt.pack(fill="x", pady=(14, 0))
        ttk.Button(bt, text="Dodaj", style="Accent.TButton", command=self.ok).pack(side="left")
        ttk.Button(bt, text="Anuluj", command=self.close).pack(side="right")
        self.after(30, e.focus_set)

    def ok(self):
        self.result = self.var.get().strip()
        self.close()


# =============================================================================
class App:
    def __init__(self, root: tk.Tk, open_path: str | None = None):
        self.root = root
        self.cfg = storage.load_config()
        self.s = Session()
        self.clip = Clipboard(root)
        self.dialogs: list[Dialog] = []
        self.view = None
        self.main: MainView | None = None
        self.save_job = None
        self.flash_job = None
        self.clip_job = None
        self.clip_text = None
        self.saved_at = None
        self.save_error = ""
        self.conflict_open = False
        self.last_act = time.monotonic()
        self.last_check = 0.0

        root.title("Sejf")
        root.minsize(940, 580)
        root.geometry(self.cfg.get("geometry") or "1240x760")
        self.icon = tk.PhotoImage(data=ICON_PNG_B64)
        root.iconphoto(True, self.icon)
        try:
            self.scale = max(1.0, float(root.tk.call("tk", "scaling")) / (96 / 72))
        except (tk.TclError, ValueError):
            self.scale = 1.0
        self._fonts()
        self.apply_theme(self.cfg.get("theme", "system"))

        p = open_path or self.cfg.get("last_path")
        self.last_path = p if p and os.path.exists(p) else None

        for seq in ("<KeyPress>", "<ButtonPress>", "<MouseWheel>", "<Motion>"):
            root.bind_all(seq, self._activity, add="+")
        root.bind_all("<Control-n>", lambda e: self.main.new_entry() if self.main and not self.dialogs else None)
        root.bind_all("<Control-f>", lambda e: self._focus_search())
        root.bind_all("<Control-l>", lambda e: self.lock() if self.s.unlocked else None)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.show_lock("unlock" if self.last_path else "home")
        root.after(1000, self.tick)

    # --- wygląd ---------------------------------------------------------------------
    def _fonts(self):
        fams = set(tkfont.families(self.root))
        ui = next((f for f in ("Segoe UI Variable Text", "Segoe UI", "Helvetica") if f in fams), "TkDefaultFont")
        disp = next((f for f in ("Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI") if f in fams), ui)
        mono = next((f for f in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New") if f in fams), "TkFixedFont")
        self.base_font = tkfont.Font(family=ui, size=10)
        self.mono = tkfont.Font(family=mono, size=10)
        self.mono_big = tkfont.Font(family=mono, size=14)
        self.f_title = tkfont.Font(family=disp, size=16, weight="bold")
        self.f_hero = tkfont.Font(family=disp, size=24, weight="bold")
        self.f_field = tkfont.Font(family=ui, size=8, weight="bold")
        self.f_strong = tkfont.Font(family=ui, size=10, weight="bold")
        self.f_small = tkfont.Font(family=ui, size=8)

    def is_dark(self, mode):
        if mode == "dark":
            return True
        if mode == "light":
            return False
        try:
            return bool(darkdetect and darkdetect.isDark())
        except Exception:  # noqa: BLE001
            return False

    def apply_theme(self, mode: str):
        self.dark = self.is_dark(mode)
        self.colors = COLORS[self.dark]
        if sv_ttk:
            sv_ttk.set_theme("dark" if self.dark else "light")
        st = ttk.Style(self.root)
        c = self.colors
        bg = self.bg()
        st.configure("Title.TLabel", font=self.f_title)
        st.configure("Hero.TLabel", font=self.f_hero)
        st.configure("Muted.TLabel", foreground=c["muted"])
        st.configure("Small.TLabel", foreground=c["muted"], font=self.f_small)
        st.configure("Field.TLabel", foreground=c["muted"], font=self.f_field)
        st.configure("Strong.TLabel", font=self.f_strong)
        st.configure("Mono.TLabel", font=self.mono)
        st.configure("Error.TLabel", foreground=c["error"])
        st.configure("Warn.TLabel", foreground=c["warn"])
        st.configure("Treeview", rowheight=self.px(30))
        self.root.configure(background=bg)

    def px(self, n: float) -> int:
        return int(round(n * self.scale))

    def bg(self):
        try:
            return ttk.Style(self.root).lookup("TFrame", "background") or ("#1c1c1c" if self.dark else "#fafafa")
        except tk.TclError:
            return "#fafafa"

    def card(self, parent, padding):
        """Ramka z cienką obwódką; zwraca (zewnętrzną, wewnętrzną) ramkę."""
        outer = tk.Frame(parent, bg=self.bg(), highlightthickness=1, highlightbackground=self.colors["empty"],
                         highlightcolor=self.colors["empty"], bd=0, takefocus=0)
        inner = ttk.Frame(outer, padding=padding)
        inner.pack(fill="both", expand=True)
        return outer, inner

    def set_theme(self, mode: str):
        self.cfg["theme"] = mode
        storage.save_config(self.cfg)
        self.apply_theme(mode)
        if self.s.unlocked:
            sel = self.main.selected() if self.main else None
            self.enter_main(keep=True)
            if sel:
                self.main.select(sel["id"])
        else:
            self.show_lock("unlock" if self.last_path else "home")

    def after_dialog(self, fn):
        for d in list(self.dialogs):
            d.close()
        self.root.after(10, fn)

    # --- widoki -----------------------------------------------------------------------
    def _swap(self, view):
        if self.view is not None:
            self.view.destroy()
        self.view = view
        view.pack(fill="both", expand=True)

    def show_lock(self, mode: str, message: str = ""):
        self.main = None
        self._swap(LockScreen(self, mode, message))
        self.root.title("Sejf")

    def enter_main(self, keep: bool = False):
        if not keep:
            self.last_path = self.s.path
            self.cfg["last_path"] = self.s.path
            storage.save_config(self.cfg)
            self.saved_at = None
            self.last_act = time.monotonic()
        self.main = MainView(self)
        self._swap(self.main)
        self.root.title(f"Sejf — {self.s.file_name}")
        self.refresh_status()

    def create_vault(self, path, pw, lock_screen=None):
        if lock_screen:
            lock_screen.btn.configure(text="Tworzę sejf…", state="disabled")

        def done(_):
            self.saved_at = time.localtime()
            self.enter_main()
            self.refresh_status()

        self.run_bg(lambda: self.s.create(path, pw), done,
                    lambda e: lock_screen.create_failed(e) if lock_screen and lock_screen.winfo_exists() else None)

    def _focus_search(self):
        if self.main and not self.dialogs:
            self.main.search_entry.focus_set()
            self.main.search_entry.select_range(0, "end")
            return "break"

    # --- tło ----------------------------------------------------------------------------
    def run_bg(self, fn, done, fail):
        """Wolne operacje (wyprowadzanie klucza) w osobnym wątku, żeby okno nie zamarzało."""
        box = {}

        def work():
            try:
                box["v"] = fn()
            except Exception as e:  # noqa: BLE001
                box["e"] = e

        t = threading.Thread(target=work, daemon=True)
        t.start()

        def poll():
            if t.is_alive():
                self.root.after(30, poll)
            elif "e" in box:
                fail(box["e"])
            else:
                done(box.get("v"))

        self.root.after(30, poll)

    # --- zapis ----------------------------------------------------------------------------
    def changed(self):
        self.s.mark_changed()
        if self.save_job:
            self.root.after_cancel(self.save_job)
        self.save_job = self.root.after(300, self.do_save)
        self.refresh_status()

    def flush_save(self):
        if self.save_job:
            self.root.after_cancel(self.save_job)
            self.do_save()

    def do_save(self, force: bool = False):
        self.save_job = None
        if not self.s.unlocked:
            return
        try:
            result = self.s.save(force=force)
            self.save_error = ""
        except OSError as e:
            self.save_error = f"Nie udało się zapisać pliku: {e.strerror or e}"
            result = "error"
        if result == "saved":
            self.saved_at = time.localtime()
        elif result == "conflict":
            self.show_conflict()
        self.refresh_status()

    def show_conflict(self):
        if not self.conflict_open:
            self.conflict_open = True
            ConflictDialog(self).show()

    def resolve_conflict(self, which):
        self.conflict_open = False
        if which == "mine":
            self.do_save(force=True)
            self.flash("Zapisano Twoją wersję.")
            return
        try:
            self.s.reload_from_file()
        except crypto.VaultError:
            self.lock(message="Hasło główne zmieniono na innym urządzeniu. Odblokuj sejf nowym hasłem.")
            return
        self.main.detail.editing = None
        self.main.refresh()
        self.flash("Wczytano wersję z pliku.")

    def refresh_status(self):
        if not self.main:
            return
        if self.save_error:
            text = self.save_error
        elif self.save_job or self.s.dirty:
            text = f"{self.s.file_name}  ·  zapisywanie…"
        elif self.saved_at:
            text = f"{self.s.file_name}  ·  zapisano automatycznie o {time.strftime('%H:%M', self.saved_at)}"
        else:
            text = f"{self.s.file_name}  ·  {self.s.path}"
        self.main.status.configure(text=text, style="Error.TLabel" if self.save_error else "Muted.TLabel")

    def flash(self, msg: str, ms: int = 4000):
        if not self.main:
            return
        self.main.status.configure(text=msg, style="TLabel")
        if self.flash_job:
            self.root.after_cancel(self.flash_job)
        self.flash_job = self.root.after(ms, self._end_flash)

    def _end_flash(self):
        self.flash_job = None
        self.refresh_status()

    # --- schowek ---------------------------------------------------------------------------
    def copy(self, text: str, what: str, secret: bool = False):
        try:
            self.clip.set(text, private=secret)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Schowek", f"Nie udało się skopiować: {e}", parent=self.root)
            return
        sec = int(self.s.data["settings"].get("clipSec", 0)) if self.s.unlocked else 0
        if secret and sec:
            if self.clip_job:
                self.root.after_cancel(self.clip_job)
            self.clip_text = text
            self.clip_job = self.root.after(sec * 1000, self.clear_clip)
            self.flash(f"Skopiowano {what}. Schowek wyczyszczę za {sec} s.")
        else:
            self.flash(f"Skopiowano {what}.")

    def clear_clip(self):
        self.clip_job = None
        if self.clip_text is not None and self.clip.clear_if(self.clip_text):
            self.flash("Wyczyszczono schowek.")
        self.clip_text = None

    # --- blokada ---------------------------------------------------------------------------
    def _activity(self, _e=None):
        self.last_act = time.monotonic()

    def tick(self):
        try:
            if self.s.unlocked:
                minutes = int(self.s.data["settings"].get("autoLockMin", 0))
                if minutes and time.monotonic() - self.last_act > minutes * 60:
                    self.lock(message="Sejf został zablokowany po okresie bezczynności.")
                elif time.monotonic() - self.last_check > 3 and not self.save_job and not self.conflict_open:
                    self.last_check = time.monotonic()
                    self.check_external()
        finally:
            self.root.after(1000, self.tick)

    def check_external(self):
        r = self.s.check_external()
        if r == "reloaded":
            editing = self.main.detail.editing is not None
            self.main.refresh(keep_detail=not editing)
            self.flash("Wczytano zmiany z innego urządzenia.")
        elif r == "conflict":
            self.show_conflict()
        elif r == "relock":
            self.lock(message="Hasło główne zmieniono na innym urządzeniu. Odblokuj sejf nowym hasłem.", save=False)
        elif r == "missing":
            self.save_error = "Nie ma pliku sejfu w tym miejscu. Zostanie utworzony przy następnym zapisie."
            self.refresh_status()

    def lock(self, message: str = "", save: bool = True):
        if save:
            self.flush_save()
        if self.clip_job:
            self.root.after_cancel(self.clip_job)
            self.clear_clip()
        for d in list(self.dialogs):
            d.close()
        self.conflict_open = False
        self.root.unbind("<Control-s>")
        self.root.unbind("<Escape>")
        self.s.lock()
        self.save_error = ""
        self.show_lock("unlock" if self.last_path else "home", message)

    def quit(self):
        try:
            if self.s.unlocked:
                self.flush_save()
            if self.clip_text is not None:
                self.clip.clear_if(self.clip_text)
            if self.root.state() == "normal":
                self.cfg["geometry"] = self.root.geometry()
            storage.save_config(self.cfg)
        finally:
            self.root.destroy()

    # --- okna dialogowe -------------------------------------------------------------------------
    def ask_string(self, title, label):
        d = AskStringDialog(self, title, label).show()
        self.root.wait_window(d)
        return d.result

    def open_generator(self, use_cb=None):
        if not self.s.unlocked:
            return
        return GeneratorDialog(self, use_cb).show()

    def open_settings(self):
        return SettingsDialog(self).show()

    def open_history(self, e):
        return HistoryDialog(self, e).show()

    def open_export(self):
        return ExportDialog(self).show()

    def open_import(self):
        path = filedialog.askopenfilename(parent=self.root, title="Wybierz plik CSV z hasłami", filetypes=CSV_TYPES)
        if not path:
            return None
        try:
            preview = self.load_import(path)
        except (OSError, ValueError) as e:
            messagebox.showerror("Import", str(e), parent=self.root)
            return None
        return ImportDialog(self, preview).show()

    def load_import(self, path) -> ImportPreview:
        with open(path, "rb") as f:
            res = csvio.parse(csvio.decode(f.read()))
        return ImportPreview(path, res.fmt, len(res.entries), csvio.without_duplicates(self.s.data["entries"], res.entries))

    def apply_import(self, entries, category: str) -> int:
        data = self.s.data
        for e in entries:
            cat = e["category"] or category
            data["entries"].append(vault.new_entry(**{**e, "category": cat}))
            if cat and cat not in data["categories"]:
                data["categories"].append(cat)
        self.changed()
        if self.main:
            self.main.kind, self.main.value = "all", ""
            self.main.refresh()
        return len(entries)

    def export_backup(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="Zapisz zaszyfrowaną kopię",
                                            initialfile=f"hasla-kopia-{date.today().isoformat()}.sejf.json",
                                            defaultextension=".json", filetypes=VAULT_TYPES)
        if path:
            try:
                self.s.write_backup(path)
                self.flash("Zapisano zaszyfrowaną kopię.")
            except OSError as e:
                messagebox.showerror("Kopia zapasowa", f"Nie udało się zapisać: {e}", parent=self.root)

    def export_csv(self):
        if not messagebox.askyesno("Eksport bez szyfrowania",
                                   "Plik CSV nie jest zaszyfrowany. Każdy, kto go otworzy, zobaczy wszystkie hasła.\n\n"
                                   "Zapisać go mimo to? Usuń go zaraz po użyciu.", icon="warning", parent=self.root):
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="Zapisz CSV",
                                            initialfile=f"hasla-{date.today().isoformat()}.csv",
                                            defaultextension=".csv", filetypes=CSV_TYPES)
        if path:
            try:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(csvio.to_csv(self.s.data["entries"]))
                self.flash("Zapisano CSV. Usuń go po użyciu.")
            except OSError as e:
                messagebox.showerror("Eksport", f"Nie udało się zapisać: {e}", parent=self.root)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--selftest":
        from .selftest import run
        return run(argv[1] if len(argv) > 1 else None)
    if sys.platform == "win32":
        try:  # ostre czcionki na ekranach z powiększeniem
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sejf.MenedzerHasel")
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()
    App(root, open_path=argv[0] if argv and os.path.exists(argv[0]) else None)
    root.mainloop()
    return 0
