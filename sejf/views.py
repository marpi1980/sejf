"""Ekran blokady i główne okno: drzewo (moje hasła i klienci), lista wpisów, szczegóły."""
from __future__ import annotations

import os
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from . import connect, crypto, kinds, vault
from .kinds import BY_KEY, KINDS, kind_of
from .session import ME, Session
from .widgets import VAULT_TYPES, ScrollFrame, StrengthBar, cloud_folder, focus_later, readonly

SEP = "|"


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
        ttk.Label(t, text="Hasła własne i hasła klientów\nw zaszyfrowanych plikach.", style="Muted.TLabel",
                  justify="left").pack(anchor="w")
        self.body = ttk.Frame(card, width=360)
        self.body.pack(fill="x", pady=(24, 0))
        self.message = message
        {"home": self.show_home, "unlock": self.show_unlock, "create": self.show_create, "totp": self.show_totp}[mode]()

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _note(self, text, style="Muted.TLabel"):
        lbl = ttk.Label(self.body, text=text, style=style, wraplength=self.app.px(360), justify="left")
        lbl.pack(fill="x", pady=(12, 0))
        return lbl

    # --- ekran startowy ---------------------------------------------------------------
    def show_home(self):
        self._clear()
        ttk.Button(self.body, text="Otwórz plik sejfu…", style="Accent.TButton", command=self.pick_file).pack(fill="x", ipady=3)
        ttk.Button(self.body, text="Utwórz nowy sejf…", command=self.show_create).pack(fill="x", pady=(8, 0), ipady=3)
        self._note("Sejf to Twój osobisty plik chroniony hasłem głównym. Trzymasz w nim swoje hasła oraz klucze "
                   "do profili klientów, które dodasz później.")

    def pick_file(self):
        p = filedialog.askopenfilename(parent=self.app.root, title="Otwórz plik sejfu", filetypes=VAULT_TYPES,
                                       initialdir=cloud_folder())
        if p:
            self.app.last_path = p
            self.message = ""
            self.show_unlock()

    # --- odblokowanie -------------------------------------------------------------------
    def show_unlock(self):
        self._clear()
        path = self.app.last_path or ""
        chip = ttk.Frame(self.body)
        chip.pack(fill="x")
        ttk.Label(chip, text="Plik:", style="Muted.TLabel").pack(side="left")
        ttk.Label(chip, text=os.path.basename(path), style="Mono.TLabel").pack(side="left", padx=(6, 0))
        ttk.Label(self.body, text=os.path.dirname(path), style="Small.TLabel", wraplength=self.app.px(360)).pack(anchor="w")
        ttk.Label(self.body, text="HASŁO GŁÓWNE", style="Field.TLabel").pack(anchor="w", pady=(16, 4))
        self.pw = tk.StringVar()
        self.pw_entry = ttk.Entry(self.body, textvariable=self.pw, show="•", width=40)
        self.pw_entry.pack(fill="x")
        self.pw_entry.bind("<Return>", lambda e: self.unlock())
        self.show_pw = tk.BooleanVar()
        ttk.Checkbutton(self.body, text="Pokaż hasło", variable=self.show_pw,
                        command=lambda: self.pw_entry.configure(show="" if self.show_pw.get() else "•")).pack(anchor="w", pady=(6, 0))
        self.err = ttk.Label(self.body, text=self.message, style="Error.TLabel", wraplength=self.app.px(360))
        self.err.pack(fill="x", pady=(6, 0))
        self.pw.trace_add("write", lambda *a: self.err.configure(text=""))
        self.btn = ttk.Button(self.body, text="Odblokuj", style="Accent.TButton", command=self.unlock)
        self.btn.pack(fill="x", pady=(8, 0), ipady=3)
        links = ttk.Frame(self.body)
        links.pack(fill="x", pady=(10, 0))
        ttk.Button(links, text="Inny plik…", command=self.pick_file).pack(side="left")
        ttk.Button(links, text="Nowy sejf…", command=self.show_create).pack(side="right")
        focus_later(self.pw_entry, 50)

    def unlock(self):
        if not self.pw.get():
            self.err.configure(text="Wpisz hasło główne.")
            return
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

        self.app.run_bg(lambda: self.app.s.unlock(path, pw), lambda _: self.app.after_unlock(), fail)

    # --- weryfikacja dwuetapowa --------------------------------------------------------
    def show_totp(self):
        self._clear()
        ttk.Label(self.body, text="Weryfikacja dwuetapowa", style="Title.TLabel").pack(anchor="w")
        self._note("Wpisz 6-cyfrowy kod z aplikacji Google Authenticator (lub innej, w której dodałeś Sejf). "
                   "Na tym komputerze program zapyta o kod ponownie po upływie ustawionego okresu.")
        ttk.Label(self.body, text="KOD", style="Field.TLabel").pack(anchor="w", pady=(16, 4))
        self.code = tk.StringVar()
        e = ttk.Entry(self.body, textvariable=self.code, font=self.app.mono_big, width=12, justify="center")
        e.pack(anchor="w")
        e.bind("<Return>", lambda ev: self.check_code())
        self.err = ttk.Label(self.body, text="", style="Error.TLabel", wraplength=self.app.px(360))
        self.err.pack(fill="x", pady=(6, 0))
        self.code.trace_add("write", lambda *a: self.err.configure(text=""))
        ttk.Button(self.body, text="Potwierdź", style="Accent.TButton", command=self.check_code).pack(fill="x", pady=(8, 0), ipady=3)
        self._note("Nie masz telefonu? Wpisz w to samo pole jeden z kodów zapasowych (np. ABCD-EFGH).")
        ttk.Button(self.body, text="Anuluj i zablokuj", command=lambda: self.app.lock(save=False)).pack(anchor="w", pady=(12, 0))
        focus_later(e, 50)

    def check_code(self):
        code = self.code.get().strip()
        if not code:
            self.err.configure(text="Wpisz kod z aplikacji.")
            return
        if self.app.s.totp_check(code):
            self.app.save_config()
            self.app.enter_main()
            left = self.app.s.recovery_left()
            if any(ch.isalpha() for ch in code) and left <= 3:
                messagebox.showwarning("Kody zapasowe", f"Zostało {left} kodów zapasowych. Wygeneruj nowe w Ustawieniach.",
                                       parent=self.app.root)
        else:
            self.err.configure(text="Nieprawidłowy kod. Sprawdź, czy zegar w telefonie jest ustawiony automatycznie.")

    # --- nowy sejf -------------------------------------------------------------------------
    def show_create(self):
        self._clear()
        ttk.Label(self.body, text="Nowy sejf", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.body, text="HASŁO GŁÓWNE", style="Field.TLabel").pack(anchor="w", pady=(12, 4))
        self.n1, self.n2 = tk.StringVar(), tk.StringVar()
        e1 = ttk.Entry(self.body, textvariable=self.n1, show="•", width=40)
        e1.pack(fill="x")
        self.meter = StrengthBar(self.body, self.app, "Co najmniej 8 znaków. Najlepiej kilka słów.")
        self.meter.pack(anchor="w", pady=(6, 0))
        ttk.Label(self.body, text="POWTÓRZ HASŁO GŁÓWNE", style="Field.TLabel").pack(anchor="w", pady=(12, 4))
        e2 = ttk.Entry(self.body, textvariable=self.n2, show="•", width=40)
        e2.pack(fill="x")
        e2.bind("<Return>", lambda e: self.create())
        self.err = ttk.Label(self.body, text="", style="Error.TLabel", wraplength=self.app.px(360))
        self.err.pack(fill="x", pady=(6, 0))
        self.n1.trace_add("write", lambda *a: (self.meter.set(self.n1.get()), self.err.configure(text="")))
        self.n2.trace_add("write", lambda *a: self.err.configure(text=""))
        self._note("Hasła głównego nie da się odzyskać. Jeśli je zapomnisz, stracisz dostęp do swoich haseł "
                   "i zapamiętanych profili klientów.", style="Warn.TLabel")
        self.btn = ttk.Button(self.body, text="Wybierz miejsce i utwórz sejf…", style="Accent.TButton", command=self.create)
        self.btn.pack(fill="x", pady=(14, 0), ipady=3)
        ttk.Button(self.body, text="Wróć", command=self.show_unlock if self.app.last_path else self.show_home).pack(anchor="w", pady=(10, 0))
        focus_later(e1, 50)

    def create(self):
        problem = Session.check_new_password(self.n1.get(), self.n2.get())
        if problem:
            self.err.configure(text=problem)
            return
        path = filedialog.asksaveasfilename(parent=self.app.root, title="Gdzie zapisać plik sejfu?",
                                            initialfile="hasla.sejf.json", defaultextension=".json",
                                            filetypes=VAULT_TYPES, initialdir=cloud_folder())
        if path:
            self.app.create_vault(path, self.n1.get(), self)

    def create_failed(self, e):
        self.err.configure(text=f"Nie udało się utworzyć pliku: {e}")
        self.btn.configure(text="Wybierz miejsce i utwórz sejf…", state="normal")


# =============================================================================
class Scope:
    """Co pokazuje lista: źródła (moje hasła / profile) i filtr."""

    def __init__(self, iid: str, sids: list[str], kind: str = "all", value: str = "", title: str = ""):
        self.iid, self.sids, self.kind, self.value, self.title = iid, sids, kind, value, title

    @property
    def single(self) -> str | None:
        return self.sids[0] if len(self.sids) == 1 else None

    @property
    def profile(self) -> str | None:
        return self.single if self.single and self.single != ME else None


class MainView(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.scope_iid = "all"
        self._updating = False

        bar = ttk.Frame(self, padding=(14, 12, 14, 10))
        bar.pack(fill="x")
        ttk.Button(bar, text="＋ Nowy wpis", style="Accent.TButton", command=self.new_entry).pack(side="left")
        self.client_btn = ttk.Button(bar, text="＋ Klient ▾", command=self.client_menu)
        self.client_btn.pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Generator", command=app.open_generator).pack(side="left", padx=(8, 0))
        self.search = tk.StringVar()
        self.search_entry = ttk.Entry(bar, textvariable=self.search, width=28)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(18, 0))
        self.search.trace_add("write", lambda *a: self.refresh_list())
        ttk.Button(bar, text="Zablokuj", command=app.lock).pack(side="right")
        ttk.Button(bar, text="Ustawienia", command=app.open_settings).pack(side="right", padx=(6, 6))
        ttk.Button(bar, text="Eksport…", command=app.open_export).pack(side="right", padx=(6, 0))
        ttk.Button(bar, text="Import…", command=app.open_import).pack(side="right", padx=(18, 0))
        self._placeholder()

        self.status = ttk.Label(self, style="Muted.TLabel", padding=(16, 6, 16, 8))
        self.status.pack(side="bottom", fill="x")

        self.paned = ttk.PanedWindow(self, orient="horizontal")
        self.paned.pack(fill="both", expand=True, padx=14)

        nav_box = ttk.Frame(self.paned)
        self.nav = ttk.Treeview(nav_box, show="tree", selectmode="browse")
        nsb = ttk.Scrollbar(nav_box, orient="vertical", command=self.nav.yview)
        self.nav.configure(yscrollcommand=nsb.set)
        self.nav.pack(side="left", fill="both", expand=True)
        nsb.pack(side="left", fill="y")
        self.nav.bind("<<TreeviewSelect>>", self.on_nav)
        self.nav.bind("<Button-3>", self.nav_menu)
        self.paned.add(nav_box, weight=0)

        list_box = ttk.Frame(self.paned)
        lh = ttk.Frame(list_box)
        lh.pack(side="top", fill="x", pady=(0, 6))
        self.list_title = ttk.Label(lh, style="Strong.TLabel")
        self.list_title.pack(side="left")
        self.list_count = ttk.Label(lh, style="Muted.TLabel")
        self.list_count.pack(side="right")
        self.list = ttk.Treeview(list_box, columns=("title", "type", "addr", "user", "src"), show="headings",
                                 selectmode="browse")
        for col, text, w in (("title", "Nazwa", 180), ("type", "Typ", 120), ("addr", "Adres", 130),
                             ("user", "Login", 120), ("src", "Klient", 110)):
            self.list.heading(col, text=text, anchor="w")
            self.list.column(col, width=app.px(w), minwidth=50, anchor="w", stretch=True)
        sb = ttk.Scrollbar(list_box, orient="vertical", command=self.list.yview)
        self.list.configure(yscrollcommand=sb.set)
        self.list.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.list.bind("<<TreeviewSelect>>", self.on_select)
        self.list.bind("<Double-1>", lambda e: self.copy_selected("password"))
        self.list.bind("<Control-c>", lambda e: self.copy_selected("password"))
        self.list.bind("<Control-b>", lambda e: self.copy_selected("username"))
        self.list.bind("<Return>", lambda e: self.edit_selected())
        self.list.bind("<Delete>", lambda e: self.delete(*self.selected()) if self.selected() else None)
        self.list.bind("<Button-3>", self.list_menu)
        self.paned.add(list_box, weight=1)

        self.detail = DetailPanel(self.paned, app, self)
        self.paned.add(self.detail, weight=2)
        self.after(30, self._init_sashes)
        self.refresh()

    def _placeholder(self):
        """Podpowiedź w pustym polu wyszukiwania."""
        hint = "Szukaj: nazwa, IP, login, model, lokalizacja…"
        e = self.search_entry

        def show(_=None):
            if not e.winfo_exists() or self.search.get() or self._focused(e):
                return
            self._hint = True  # przed wstawieniem tekstu, żeby lista nie filtrowała po podpowiedzi
            e.configure(foreground=self.app.colors["muted"])
            e.insert(0, hint)

        def hide(_=None):
            if getattr(self, "_hint", False):
                self._hint = False
                e.delete(0, "end")
                e.configure(foreground="")

        self._hint = False
        self._hint_text = hint
        e.bind("<FocusIn>", hide, add="+")
        e.bind("<FocusOut>", show, add="+")
        self.after(50, show)

    def _focused(self, w) -> bool:
        try:
            return self.app.root.focus_get() is w
        except (KeyError, tk.TclError):
            return False

    def query(self) -> str:
        return "" if getattr(self, "_hint", False) else self.search.get()

    def _init_sashes(self):
        try:
            w = self.paned.winfo_width()
            left = self.app.px(210)
            self.paned.sashpos(0, left)
            self.paned.sashpos(1, left + max(self.app.px(300), int((w - left) * 0.40)))
        except tk.TclError:
            pass

    # --- dane -----------------------------------------------------------------------------
    @property
    def s(self) -> Session:
        return self.app.s

    def scope(self) -> Scope:
        iid = self.scope_iid
        parts = iid.split(SEP)
        profiles = [pid for pid, p in self.s.profiles.items() if p.file]
        if iid == "all":
            return Scope(iid, self.s.open_sources(), title="Wszystko")
        if iid == "clients":
            return Scope(iid, profiles, title="Wszyscy klienci")
        if parts[0] == ME:
            if len(parts) == 1:
                return Scope(iid, [ME], title="Moje hasła")
            kind = parts[1]
            value = parts[2] if len(parts) > 2 else ""
            title = {"fav": "Ulubione", "none": "Bez kategorii"}.get(kind) or (
                "#" + value if kind == "tag" else BY_KEY[value].group if kind == "type" else value)
            return Scope(iid, [ME], kind, value, title)
        if parts[0] == "c" and len(parts) >= 2:
            pid = parts[1]
            name = self.s.profiles[pid].name if pid in self.s.profiles else "?"
            if len(parts) == 2:
                return Scope(iid, [pid], title=name)
            kind, value = parts[2], parts[3] if len(parts) > 3 else ""
            sub = BY_KEY[value].group if kind == "type" else value
            return Scope(iid, [pid], kind, value, f"{name} · {sub}")
        return Scope("all", self.s.open_sources(), title="Wszystko")

    def entry_of(self, iid: str):
        sid, eid = iid.split(SEP, 1)
        return sid, self.s.find(sid, eid)

    def selected(self):
        sel = self.list.selection()
        if not sel:
            return None
        sid, e = self.entry_of(sel[0])
        return (sid, e) if e else None

    def refresh(self, keep_detail: bool = False):
        self.refresh_nav()
        self.refresh_list(keep_detail=keep_detail)

    def refresh_nav(self):
        self._updating = True
        n = self.nav
        open_state = {iid: n.item(iid, "open") for iid in self._all_iids()} if n.get_children() else {}
        n.delete(*n.get_children())
        s = self.s
        total = sum(1 for _ in s.all_entries())
        n.insert("", "end", iid="all", text=f"Wszystko  ({total})")
        me = s.data
        n.insert("", "end", iid=ME, text=f"Moje hasła  ({len(me['entries'])})", open=open_state.get(ME, True))
        favs = sum(e["fav"] for e in me["entries"])
        if favs:
            n.insert(ME, "end", iid=f"{ME}{SEP}fav", text=f"★ Ulubione  ({favs})")
        types = vault.type_counts(me)
        if len(types) > 1:
            for k, c in types:
                n.insert(ME, "end", iid=f"{ME}{SEP}type{SEP}{k}", text=f"{BY_KEY[k].group}  ({c})")
        for c in vault.categories(me):
            cnt = sum(e["category"] == c for e in me["entries"])
            if cnt:
                n.insert(ME, "end", iid=f"{ME}{SEP}cat{SEP}{c}", text=f"{c}  ({cnt})")
        none = sum(not e["category"] for e in me["entries"])
        if none and len(me["entries"]) > none:
            n.insert(ME, "end", iid=f"{ME}{SEP}none", text=f"Bez kategorii  ({none})")
        for t, k in vault.tag_counts(me):
            n.insert(ME, "end", iid=f"{ME}{SEP}tag{SEP}{t}", text=f"#{t}  ({k})")

        n.insert("", "end", iid="clients", text=f"Klienci  ({len(s.profiles)})", open=open_state.get("clients", True))
        for pid, p in s.profiles.items():
            piid = f"c{SEP}{pid}"
            if p.file:
                n.insert("clients", "end", iid=piid, text=f"{p.name}  ({len(p.data['entries'])})",
                         open=open_state.get(piid, False))
                for k, c in vault.type_counts(p.data):
                    n.insert(piid, "end", iid=f"{piid}{SEP}type{SEP}{k}", text=f"{BY_KEY[k].group}  ({c})")
                for t, k in vault.tag_counts(p.data):
                    n.insert(piid, "end", iid=f"{piid}{SEP}tag{SEP}{t}", text=f"#{t}  ({k})")
            else:
                state = {"loading": "otwieram…", "missing": "brak pliku", "password": "podaj hasło",
                         "corrupt": "błąd pliku"}.get(p.error, "")
                n.insert("clients", "end", iid=piid, text=f"{p.name}  ({state})")
        if not n.exists(self.scope_iid):
            self.scope_iid = "all"
        n.selection_set(self.scope_iid)
        n.see(self.scope_iid)
        self._updating = False

    def _all_iids(self):
        out, stack = [], list(self.nav.get_children())
        while stack:
            i = stack.pop()
            out.append(i)
            stack.extend(self.nav.get_children(i))
        return out

    def refresh_list(self, keep_detail: bool = True):
        cur = self.list.selection()
        cur = cur[0] if cur else None
        sc = self.scope()
        rows = []
        for sid in sc.sids:
            f = self.s.source(sid)
            if not f:
                continue
            for e in vault.filter_entries(f.data, sc.kind, sc.value, self.query()):
                rows.append((sid, e))
        rows.sort(key=lambda r: vault.sort_key(r[1]))
        self.list.delete(*self.list.get_children())
        for sid, e in rows:
            self.list.insert("", "end", iid=f"{sid}{SEP}{e['id']}", values=(
                ("★ " if e["fav"] else "") + e["title"], kind_of(e).label.split(" (")[0].split(" /")[0],
                kinds.address_of(e), e["username"], self.s.source_name(sid)))
        multi = len(sc.sids) > 1
        self.list.configure(displaycolumns=("title", "type", "addr", "user", "src") if multi else
                            ("title", "type", "addr", "user"))
        self.list.heading("src", text="Gdzie")
        self.list_title.configure(text=sc.title)
        self.list_count.configure(text=vault.wpisy(len(rows)))
        if cur and self.list.exists(cur):
            self.list.selection_set(cur)
            self.list.see(cur)
            if keep_detail and self.detail.editing is None:
                sid, e = self.entry_of(cur)
                self.detail.show(sid, e)
        elif self.detail.editing is None:
            self.detail.show_scope(sc)

    def on_nav(self, _e=None):
        if self._updating:
            return
        sel = self.nav.selection()
        if not sel or sel[0] == self.scope_iid:
            return  # zdarzenie po odświeżeniu drzewa, wybór się nie zmienił
        if self.detail.editing is not None and not self.detail.confirm_discard():
            self._updating = True
            self.nav.selection_set(self.scope_iid)
            self._updating = False
            return
        self.scope_iid = sel[0]
        self.list.selection_remove(*self.list.selection())
        self.refresh_list(keep_detail=False)

    def on_select(self, _e=None):
        sel = self.selected()
        if not sel:
            return
        sid, e = sel
        ed = self.detail.editing
        if ed is not None and ed.get("id") == e["id"]:
            return
        if ed is not None and not self.detail.confirm_discard():
            return
        self.detail.show(sid, e)

    def select(self, sid, eid):
        iid = f"{sid}{SEP}{eid}"
        if not self.list.exists(iid):
            self.search.set("")
            self.refresh_list(keep_detail=False)
        if not self.list.exists(iid):
            self.scope_iid = "all" if sid == ME else f"c{SEP}{sid}"
            self.refresh_nav()
            self.refresh_list(keep_detail=False)
        if self.list.exists(iid):
            self.list.selection_set(iid)
            self.list.see(iid)
            self.detail.show(sid, self.s.find(sid, eid))

    def select_scope(self, iid):
        self.scope_iid = iid
        self.refresh()

    # --- akcje ---------------------------------------------------------------------------
    def default_target(self) -> str:
        sc = self.scope()
        return sc.single or ME

    def new_entry(self):
        if self.detail.editing is not None and not self.detail.confirm_discard():
            return
        sc = self.scope()
        self.list.selection_remove(*self.list.selection())
        defaults = {"type": "server" if sc.profile else "web"}
        if sc.kind == "type":
            defaults["type"] = sc.value
        if sc.kind == "cat":
            defaults["category"] = sc.value
        if sc.kind == "tag":
            defaults["tags"] = [sc.value]
        if sc.kind == "fav":
            defaults["fav"] = True
        self.detail.edit(self.default_target(), None, defaults)

    def edit_selected(self):
        sel = self.selected()
        if sel:
            self.detail.edit(*sel)

    def copy_selected(self, field):
        sel = self.selected()
        if sel and sel[1][field]:
            self.app.copy(sel[1][field], "hasło" if field == "password" else "login", secret=field == "password")
        return "break"

    def delete(self, sid, e):
        if not e:
            return
        where = "" if sid == ME else f"\n\nWpis zniknie z profilu „{self.s.source_name(sid)}” u wszystkich osób, które go używają."
        if messagebox.askyesno("Usuń wpis", f"Usunąć wpis „{e['title']}”?{where}\n\nTej operacji nie da się cofnąć.",
                               icon="warning", parent=self.app.root):
            vault.delete_entry(self.s.source(sid).data, e["id"])
            self.detail.editing = None
            self.app.changed(sid)
            self.refresh()
            self.app.flash("Usunięto wpis.")

    def toggle_fav(self, sid, e):
        e["fav"] = not e["fav"]
        e["updated"] = vault.now_iso()
        self.app.changed(sid)
        self.refresh()
        self.select(sid, e["id"])

    def client_menu(self):
        m = tk.Menu(self, tearoff=False)
        m.add_command(label="Nowy profil klienta…", command=self.app.new_profile)
        m.add_command(label="Dodaj profil z pliku…", command=self.app.add_profile)
        b = self.client_btn
        m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def nav_menu(self, ev):
        iid = self.nav.identify_row(ev.y)
        m = tk.Menu(self, tearoff=False)
        parts = iid.split(SEP)
        if parts[0] == "c" and len(parts) >= 2 and parts[1] in self.s.profiles:
            pid = parts[1]
            p = self.s.profiles[pid]
            self.nav.selection_set(f"c{SEP}{pid}")
            if p.file:
                m.add_command(label="Nowy wpis w tym profilu", command=self.new_entry)
                m.add_command(label="Dane klienta…", command=lambda: self.app.edit_profile_info(pid))
                m.add_command(label="Udostępnij…", command=lambda: self.app.share_profile(pid))
                m.add_command(label="Zmień hasło profilu…", command=lambda: self.app.change_profile_password(pid))
            m.add_command(label="Pokaż plik w folderze", command=lambda: self.app.reveal(p.path))
            m.add_separator()
            m.add_command(label="Usuń z programu…", command=lambda: self.app.forget_profile(pid))
        elif parts[0] == ME and len(parts) == 3 and parts[1] == "cat":
            name = parts[2]
            used = any(e["category"] == name for e in self.s.data["entries"])
            m.add_command(label=f"Usuń kategorię „{name}”", state="disabled" if used else "normal",
                          command=lambda: self.remove_category(name))
        else:
            m.add_command(label="Nowy profil klienta…", command=self.app.new_profile)
            m.add_command(label="Dodaj profil z pliku…", command=self.app.add_profile)
        m.tk_popup(ev.x_root, ev.y_root)

    def remove_category(self, name):
        self.s.data["categories"] = [c for c in self.s.data["categories"] if c != name]
        self.app.changed(ME)
        self.refresh()

    def list_menu(self, ev):
        iid = self.list.identify_row(ev.y)
        if not iid:
            return
        self.list.selection_set(iid)
        sid, e = self.entry_of(iid)
        m = tk.Menu(self, tearoff=False)
        m.add_command(label="Kopiuj hasło", accelerator="Ctrl+C", command=lambda: self.copy_selected("password"))
        m.add_command(label="Kopiuj login", accelerator="Ctrl+B", command=lambda: self.copy_selected("username"))
        addr = kinds.address_of(e)
        if addr:
            m.add_command(label="Kopiuj adres", command=lambda: self.app.copy(addr, "adres"))
        act = connect.plan(e)
        if act and (connect.available() or act.kind == "url"):
            m.add_command(label=act.label, command=lambda: self.app.connect(e, act))
        m.add_separator()
        m.add_command(label="Edytuj", command=lambda: self.detail.edit(sid, e))
        m.add_command(label="Usuń…", command=lambda: self.delete(sid, e))
        m.tk_popup(ev.x_root, ev.y_root)


# =============================================================================
class DetailPanel(ttk.Frame):
    def __init__(self, master, app, main):
        super().__init__(master)
        self.app, self.main = app, main
        self.editing: dict | None = None
        self.sf = ScrollFrame(self, app)
        self.sf.pack(fill="both", expand=True)

    @property
    def body(self):
        return self.sf.inner

    def _clear(self):
        self.sf.clear()

    # --- widoki bez wybranego wpisu ---------------------------------------------------
    def show_scope(self, sc: Scope):
        self.editing = None
        parts = sc.iid.split(SEP)
        if parts[0] == "c" and len(parts) == 2:
            self.show_profile(parts[1])
        elif sc.iid == "clients":
            self.show_clients()
        else:
            self.show_empty()

    def _centered(self):
        box = ttk.Frame(self.body)
        box.pack(fill="x", pady=(self.app.px(70), 0))
        return box

    def show_empty(self):
        self.editing = None
        self._clear()
        box = self._centered()
        ttk.Label(box, image=self.app.icon).pack()
        total = sum(1 for _ in self.app.s.all_entries())
        if total:
            ttk.Label(box, text="Wybierz wpis z listy", style="Title.TLabel").pack(pady=(12, 4))
            ttk.Label(box, text="Dwuklik na wpisie kopiuje hasło.\nPrawy przycisk myszy otwiera menu.",
                      style="Muted.TLabel", justify="center").pack()
        else:
            ttk.Label(box, text="Sejf jest pusty", style="Title.TLabel").pack(pady=(12, 4))
            ttk.Label(box, text="Dodaj swoje hasło albo utwórz profil klienta\nz hasłami do jego serwerów i urządzeń.",
                      style="Muted.TLabel", justify="center").pack()
            row = ttk.Frame(box)
            row.pack(pady=(14, 0))
            ttk.Button(row, text="＋ Nowy wpis", command=self.main.new_entry).pack(side="left")
            ttk.Button(row, text="＋ Nowy profil klienta", style="Accent.TButton", command=self.app.new_profile).pack(side="left", padx=(8, 0))

    def show_clients(self):
        self._clear()
        ttk.Label(self.body, text="Klienci", style="Title.TLabel").pack(anchor="w", pady=(10, 4))
        ttk.Label(self.body, text="Każdy klient to osobny zaszyfrowany plik .sejfklient z własnym hasłem. Plik możesz "
                                  "przekazać współpracownikowi albo trzymać we wspólnym folderze (np. na Dysku Google), "
                                  "z którego korzysta cały zespół. Zmiany kilku osób program łączy sam.",
                  style="Muted.TLabel", wraplength=self.app.px(440), justify="left").pack(anchor="w")
        row = ttk.Frame(self.body)
        row.pack(anchor="w", pady=(14, 0))
        ttk.Button(row, text="＋ Nowy profil klienta…", style="Accent.TButton", command=self.app.new_profile).pack(side="left")
        ttk.Button(row, text="Dodaj profil z pliku…", command=self.app.add_profile).pack(side="left", padx=(8, 0))

    def show_profile(self, pid):
        self.editing = None
        self._clear()
        s = self.app.s
        p = s.profiles.get(pid)
        if not p:
            return self.show_empty()
        head = ttk.Frame(self.body)
        head.pack(fill="x", pady=(10, 0))
        ttk.Label(head, text=p.name, style="Title.TLabel", wraplength=self.app.px(420)).pack(anchor="w")
        ttk.Label(head, text="Profil klienta", style="Muted.TLabel").pack(anchor="w")
        if not p.file:
            msg = p.message or "Otwieram profil…"
            ttk.Label(self.body, text=msg, style="Warn.TLabel" if p.error != "loading" else "Muted.TLabel",
                      wraplength=self.app.px(440), justify="left").pack(anchor="w", pady=(16, 0))
            readonly(self.body, p.path, self.app).pack(fill="x", pady=(8, 0))
            row = ttk.Frame(self.body)
            row.pack(anchor="w", pady=(14, 0))
            if p.error == "password":
                ttk.Button(row, text="Wpisz nowe hasło…", style="Accent.TButton",
                           command=lambda: self.app.relink_password(pid)).pack(side="left", padx=(0, 8))
            if p.error in ("missing", "corrupt"):
                ttk.Button(row, text="Wskaż plik…", style="Accent.TButton",
                           command=lambda: self.app.relink_file(pid)).pack(side="left", padx=(0, 8))
            if p.error != "loading":
                ttk.Button(row, text="Usuń z programu…", command=lambda: self.app.forget_profile(pid)).pack(side="left")
            return
        acts = ttk.Frame(self.body)
        acts.pack(fill="x", pady=(14, 0))
        ttk.Button(acts, text="＋ Nowy wpis", style="Accent.TButton", command=self.main.new_entry).pack(side="left")
        ttk.Button(acts, text="Dane klienta…", command=lambda: self.app.edit_profile_info(pid)).pack(side="left", padx=(6, 0))
        ttk.Button(acts, text="Udostępnij…", command=lambda: self.app.share_profile(pid)).pack(side="left", padx=(6, 0))
        info = p.data.get("info") or {}
        grid = ttk.Frame(self.body)
        grid.pack(fill="x", pady=(18, 0))
        grid.columnconfigure(1, weight=1)
        r = 0
        for key, label in vault.PROFILE_INFO_FIELDS:
            v = info.get(key, "")
            if not v:
                continue
            ttk.Label(grid, text=label.upper(), style="Field.TLabel").grid(row=r, column=0, sticky="nw", pady=5, padx=(0, 14))
            if key == "notes" or "\n" in v:
                ttk.Label(grid, text=v, wraplength=self.app.px(360), justify="left").grid(row=r, column=1, sticky="w", pady=5)
            else:
                readonly(grid, v, self.app).grid(row=r, column=1, sticky="ew", pady=5)
                ttk.Button(grid, text="Kopiuj", command=lambda v=v, l=label: self.app.copy(v, l.lower())).grid(
                    row=r, column=2, sticky="e", padx=(8, 0))
            r += 1
        if r == 0:
            ttk.Label(grid, text="Brak danych kontaktowych. Uzupełnij je przyciskiem „Dane klienta…”.",
                      style="Muted.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        counts = vault.type_counts(p.data)
        if counts:
            ttk.Label(self.body, text="ZAWARTOŚĆ", style="Field.TLabel").pack(anchor="w", pady=(18, 6))
            box = ttk.Frame(self.body)
            box.pack(fill="x")
            for i, (k, c) in enumerate(counts):
                b = ttk.Button(box, text=f"{BY_KEY[k].group}  {c}",
                               command=lambda k=k: self.main.select_scope(f"c{SEP}{pid}{SEP}type{SEP}{k}"))
                b.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 6), pady=(0, 6))
            for col in range(2):
                box.columnconfigure(col, weight=1, uniform="z")
        warn = [(e, st) for e in p.data["entries"] if (st := vault.expiry_state(e))]
        for e, (state, text) in warn[:5]:
            ttk.Label(self.body, text=f"⚠ {e['title']}: {text}", style="Error.TLabel" if state == "expired" else "Warn.TLabel",
                      wraplength=self.app.px(440)).pack(anchor="w", pady=(8, 0))
        foot = ttk.Frame(self.body)
        foot.pack(fill="x", pady=(18, 0))
        ttk.Label(foot, text="PLIK PROFILU", style="Field.TLabel").pack(anchor="w")
        readonly(foot, p.path, self.app).pack(fill="x", pady=(4, 8))
        row = ttk.Frame(foot)
        row.pack(fill="x")
        for i, (text, cmd) in enumerate((("Pokaż w folderze", lambda: self.app.reveal(p.path)),
                                         ("Zmień hasło profilu…", lambda: self.app.change_profile_password(pid)),
                                         ("Usuń z programu…", lambda: self.app.forget_profile(pid)))):
            ttk.Button(row, text=text, command=cmd).grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 6), pady=(0, 6))
        row.columnconfigure(0, weight=1, uniform="f")
        row.columnconfigure(1, weight=1, uniform="f")

    # --- podgląd wpisu ----------------------------------------------------------------------
    def show(self, sid, e: dict | None):
        if e is None:
            return self.show_scope(self.main.scope())
        self.editing = None
        self._clear()
        app = self.app
        k = kind_of(e)
        ex = e.get("extra") or {}
        head = ttk.Frame(self.body)
        head.pack(fill="x", pady=(10, 0))
        txt = ttk.Frame(head)
        txt.pack(side="left", fill="x", expand=True)
        ttk.Label(txt, text=e["title"], style="Title.TLabel", wraplength=app.px(300)).pack(anchor="w")
        sub = k.label + ("" if sid == ME else f"  ·  {app.s.source_name(sid)}")
        if e["category"]:
            sub += f"  ·  {e['category']}"
        ttk.Label(txt, text=sub, style="Muted.TLabel", wraplength=app.px(300)).pack(anchor="w")
        manage = ttk.Frame(head)
        manage.pack(side="right", anchor="n")
        ttk.Button(manage, text="Edytuj", command=lambda: self.edit(sid, e)).pack(side="left")
        ttk.Button(manage, text="★" if e["fav"] else "☆", width=3,
                   command=lambda: self.main.toggle_fav(sid, e)).pack(side="left", padx=(6, 0))
        ttk.Button(manage, text="Usuń…", command=lambda: self.main.delete(sid, e)).pack(side="left", padx=(6, 0))
        acts = ttk.Frame(self.body)
        acts.pack(fill="x", pady=(12, 0))
        act = connect.plan(e)
        if act and (connect.available() or act.kind == "url"):
            ttk.Button(acts, text=act.label, style="Accent.TButton", command=lambda: app.connect(e, act)).pack(side="left", padx=(0, 6))
        con = connect.console_action(e)
        if con:
            ttk.Button(acts, text=con.label, command=lambda: app.connect(e, con)).pack(side="left", padx=(0, 6))
        sh = connect.share_action(e)
        if sh and connect.available() and not (act and act.target == sh.target):
            ttk.Button(acts, text=sh.label, command=lambda: app.connect(e, sh)).pack(side="left", padx=(0, 6))
        if connect.ping_action(e) and connect.available():
            ttk.Button(acts, text="Ping", command=lambda: app.connect(e, connect.ping_action(e))).pack(side="left", padx=(0, 6))

        state = vault.expiry_state(e)
        if state:
            ttk.Label(self.body, text="⚠ " + state[1], style="Error.TLabel" if state[0] == "expired" else "Warn.TLabel").pack(anchor="w", pady=(10, 0))

        grid = ttk.Frame(self.body)
        grid.pack(fill="x", pady=(16, 0))
        grid.columnconfigure(1, weight=1)
        row = [0]

        def field(label, value, secret=False, copy_what=None, link=None):
            r = row[0]
            ttk.Label(grid, text=label.upper(), style="Field.TLabel", wraplength=app.px(105)).grid(
                row=r, column=0, sticky="w", pady=5, padx=(0, 10))
            ent = readonly(grid, value, app, secret=secret)
            ent.grid(row=r, column=1, sticky="ew", pady=5)
            bf = ttk.Frame(grid)
            bf.grid(row=r, column=2, sticky="e", padx=(8, 0))
            if secret and value:
                def toggle(ent=ent, b=None):
                    shown = ent.cget("show") == ""
                    ent.configure(show="•" if shown else "")
                    show_btn.configure(text="Pokaż" if shown else "Ukryj")
                show_btn = ttk.Button(bf, text="Pokaż", command=toggle, width=6)
                show_btn.pack(side="left", padx=(4, 0))
            if link:
                ttk.Button(bf, text="Otwórz", command=lambda: webbrowser.open(link), width=7).pack(side="left", padx=(4, 0))
            if value:
                ttk.Button(bf, text="Kopiuj", width=6,
                           command=lambda: app.copy(value, copy_what or label.lower(), secret=secret)).pack(side="left", padx=(4, 0))
            row[0] += 1
            return ent

        if e.get("accounts") and (e["username"] or e["password"]):
            ttk.Label(grid, text="Konto główne", style="Strong.TLabel").grid(row=row[0], column=0, columnspan=3, sticky="w")
            row[0] += 1
        if k.uses_login or e["username"]:
            field(k.login_label, e["username"], copy_what="login")
        if k.uses_login or e["password"]:
            field(k.password_label if k.key != "wifi" else "Hasło Wi-Fi", e["password"], secret=True, copy_what="hasło")
            if e["password"]:
                meter = StrengthBar(grid, app)
                meter.set(e["password"])
                meter.grid(row=row[0], column=1, columnspan=2, sticky="w", pady=(0, 4))
                row[0] += 1
                reused = vault.reused_by([x for _, x in app.s.all_entries()], e)
                if reused:
                    ttk.Label(grid, text="⚠ To samo hasło jest też w: " + ", ".join(x["title"] for x in reused[:5]) + ".",
                              style="Warn.TLabel", wraplength=app.px(400), justify="left").grid(
                        row=row[0], column=1, columnspan=2, sticky="w", pady=(0, 6))
                    row[0] += 1
        for i, a in enumerate(e.get("accounts") or []):
            ttk.Label(grid, text=a.get("label") or f"Konto {i + 2}", style="Strong.TLabel").grid(
                row=row[0], column=0, columnspan=3, sticky="w", pady=(12, 0))
            row[0] += 1
            if a.get("username"):
                field("Login", a["username"], copy_what="login")
            if a.get("password"):
                field("Hasło", a["password"], secret=True, copy_what="hasło")
        if e.get("accounts"):
            ttk.Separator(grid).grid(row=row[0], column=0, columnspan=3, sticky="ew", pady=(10, 4))
            row[0] += 1
        for f in k.fields:
            v = ex.get(f.key, "")
            if not v:
                continue
            field(f.label, v, secret=f.kind == "secret")
        for c in e.get("custom") or []:
            if c.get("value"):
                field(c["label"], c["value"], secret=c.get("secret", False), copy_what=c["label"].lower())
        if k.uses_url or e["url"]:
            if e["url"]:
                field("Adres WWW", e["url"], copy_what="adres", link=vault.safe_href(e["url"]))
        known = {f.key for f in k.fields}
        for key, v in ex.items():
            if key not in known and v:
                field(key, v)
        if e["tags"]:
            ttk.Label(grid, text="TAGI", style="Field.TLabel").grid(row=row[0], column=0, sticky="w", pady=5)
            ttk.Label(grid, text="   ".join("#" + t for t in e["tags"])).grid(row=row[0], column=1, sticky="w", pady=5)
            row[0] += 1
        if e["notes"]:
            c = app.colors
            ttk.Label(grid, text="NOTATKI", style="Field.TLabel").grid(row=row[0], column=0, sticky="nw", pady=5)
            t = tk.Text(grid, height=min(12, e["notes"].count("\n") + 2), wrap="word", relief="flat", bd=0,
                        padx=8, pady=6, bg=c["text_bg"], fg=c["text_fg"], font=app.base_font, highlightthickness=0)
            t.insert("1.0", e["notes"])
            t.configure(state="disabled")
            t.grid(row=row[0], column=1, columnspan=2, sticky="ew", pady=5)
            row[0] += 1
        if row[0] == 0:
            ttk.Label(grid, text="Ten wpis nie ma jeszcze danych. Kliknij „Edytuj”.", style="Muted.TLabel").grid(row=0, column=0, sticky="w")

        foot = ttk.Frame(self.body)
        foot.pack(fill="x", pady=(14, 0))
        ttk.Label(foot, text=f"Utworzono: {vault.fmt_date(e['created'])}     Zmieniono: {vault.fmt_date(e['updated'])}",
                  style="Muted.TLabel").pack(side="left")
        if e["history"]:
            ttk.Button(foot, text=f"Poprzednie hasła ({len(e['history'])})…",
                       command=lambda: app.open_history(e)).pack(side="right")

    # --- edycja ----------------------------------------------------------------------------
    def edit(self, sid: str, e: dict | None, defaults: dict | None = None):
        if e is None:
            src = vault.new_entry(**(defaults or {}))
            src["id"] = None
        else:
            src = e
        targets = [(ME, "Moje hasła")] + [(pid, p.name) for pid, p in self.app.s.profiles.items() if p.file]
        self.editing = {"id": e["id"] if e else None, "sid": sid, "targets": targets,
                        "values": {"type": src["type"], "title": src["title"], "username": src["username"],
                                   "password": src["password"], "url": src["url"], "category": src["category"],
                                   "tags": ", ".join(src["tags"]), "notes": src["notes"], "fav": src["fav"],
                                   "target": dict(targets).get(sid, "Moje hasła"), **(src.get("extra") or {})},
                        "accounts": [dict(a) for a in src.get("accounts") or []],
                        "custom": [dict(c) for c in src.get("custom") or []],
                        "show_pw": False}
        if e is None:  # nowy wpis dostaje własne pola zapisane jako szablon typu
            self._apply_templates()
        self._render_form()

    def _collect(self):
        """Przepisuje wartości z pól do słownika (przed przebudową formularza i przed zapisem)."""
        ed = self.editing
        for key, var in self.vars.items():
            ed["values"][key] = var.get()
        ed["values"]["notes"] = self.notes.get("1.0", "end-1c")
        ed["values"]["type"] = self.type_key()
        for a, row in zip(ed["accounts"], self.acc_vars):
            for key, var in row.items():
                a[key] = var.get()
        for c, var in zip(ed["custom"], self.custom_vars):
            c["value"] = var.get()

    def type_key(self) -> str:
        label = self.vars["type_label"].get()
        return next((k.key for k in KINDS if k.label == label), "web")

    def _render_form(self):
        app = self.app
        ed = self.editing
        val = ed["values"]
        k = BY_KEY.get(val["type"], BY_KEY["web"])
        self._clear()
        b = self.body
        ttk.Label(b, text="Edycja wpisu" if ed["id"] else "Nowy wpis", style="Title.TLabel").pack(anchor="w", pady=(10, 10))
        g = ttk.Frame(b)
        g.pack(fill="x")
        g.columnconfigure(0, weight=1, uniform="c")
        g.columnconfigure(1, weight=1, uniform="c")
        self.vars = {}
        self.acc_vars = []
        self.custom_vars = []
        settings = app.s.data["settings"]
        r = [0]

        def var(key, value="", cls=tk.StringVar):
            v = cls(value=val.get(key, value))
            self.vars[key] = v
            return v

        def lab(text, col, colspan=1):
            ttk.Label(g, text=text.upper(), style="Field.TLabel").grid(row=r[0], column=col, columnspan=colspan, sticky="w",
                                                                         pady=(10, 3), padx=(0 if col == 0 else 10, 0))

        def put(widget, col, colspan=1):
            widget.grid(row=r[0] + 1, column=col, columnspan=colspan, sticky="ew", padx=(0 if col == 0 else 10, 0))

        def next_row():
            r[0] += 2

        # typ i miejsce
        lab("Typ", 0)
        lab("Zapisz w", 1)
        tv = tk.StringVar(value=k.label)
        self.vars["type_label"] = tv
        tcb = ttk.Combobox(g, textvariable=tv, values=[x.label for x in KINDS], state="readonly", height=20)
        put(tcb, 0)
        tcb.bind("<<ComboboxSelected>>", lambda ev: self._retype())
        tg = ttk.Combobox(g, textvariable=var("target"), values=[n for _, n in ed["targets"]], state="readonly")
        put(tg, 1)
        next_row()
        lab("Nazwa", 0, 2)
        title = ttk.Entry(g, textvariable=var("title"))
        put(title, 0, 2)
        next_row()
        self.secret_entries = []
        has_toggle = k.key != "wifi" and (k.uses_login or bool(val.get("username")) or bool(val.get("password")))
        if k.key != "wifi" and (k.uses_login or val.get("username") or val.get("password")):
            lab(k.login_label if k.key not in ("email",) else "Adres e-mail / login", 0)
            lab(k.password_label, 1)
            put(ttk.Entry(g, textvariable=var("username")), 0)
            pr = ttk.Frame(g)
            put(pr, 1)
            pw = ttk.Entry(pr, textvariable=var("password"), show="" if ed["show_pw"] else "•", font=app.mono)
            pw.pack(side="left", fill="x", expand=True)
            ttk.Button(pr, text="Generuj…", command=lambda: app.open_generator(self._use_generated)).pack(side="left", padx=(6, 0))
            next_row()
            meter = StrengthBar(g, app, "")
            meter.set(val.get("password", ""))
            meter.grid(row=r[0], column=1, sticky="w", padx=(10, 0), pady=(4, 0))
            showv = tk.BooleanVar(value=ed["show_pw"])

            def toggle():
                ed["show_pw"] = showv.get()
                for w in [pw, *self.secret_entries]:
                    w.configure(show="" if showv.get() else "•")
            ttk.Checkbutton(g, text="Pokaż hasło", variable=showv, command=toggle).grid(row=r[0], column=0, sticky="w", pady=(4, 0))
            self.vars["password"].trace_add("write", lambda *a: meter.set(self.vars["password"].get()))
            self.pw_entry = pw
            r[0] += 1
        if kinds.has_accounts(k):
            for i, a in enumerate(ed["accounts"]):
                box = ttk.Frame(g)
                box.grid(row=r[0], column=0, columnspan=2, sticky="ew", pady=(12, 0))
                box.columnconfigure(0, weight=1, uniform="a")
                box.columnconfigure(1, weight=1, uniform="a")
                rv = {key: tk.StringVar(value=a.get(key, "")) for key in ("label", "username", "password")}
                self.acc_vars.append(rv)
                top = ttk.Frame(box)
                top.grid(row=0, column=0, columnspan=2, sticky="ew")
                ttk.Label(top, text=f"DODATKOWE KONTO {i + 1}", style="Field.TLabel").pack(side="left")
                ttk.Button(top, text="Usuń konto", command=lambda i=i: self._remove_account(i)).pack(side="right")
                ttk.Label(box, text="OPIS", style="Field.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 3))
                ttk.Entry(box, textvariable=rv["label"]).grid(row=2, column=0, columnspan=2, sticky="ew")
                ttk.Label(box, text="LOGIN", style="Field.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 3))
                ttk.Label(box, text="HASŁO", style="Field.TLabel").grid(row=3, column=1, sticky="w", pady=(8, 3), padx=(10, 0))
                ttk.Entry(box, textvariable=rv["username"]).grid(row=4, column=0, sticky="ew")
                apr = ttk.Frame(box)
                apr.grid(row=4, column=1, sticky="ew", padx=(10, 0))
                aw = ttk.Entry(apr, textvariable=rv["password"], show="" if ed["show_pw"] else "•", font=app.mono)
                aw.pack(side="left", fill="x", expand=True)
                self.secret_entries.append(aw)
                ttk.Button(apr, text="Generuj…", command=lambda i=i: app.open_generator(
                    lambda v, i=i: self._use_generated(v, i))).pack(side="left", padx=(6, 0))
                r[0] += 1
            ttk.Button(g, text="＋ Dodaj kolejne konto", command=self._add_account).grid(
                row=r[0], column=0, sticky="w", pady=(10, 0))
            ttk.Label(g, text="np. konto serwisowe, kopii zapasowych, lokalny administrator", style="Small.TLabel").grid(
                row=r[0], column=1, sticky="w", pady=(10, 0), padx=(10, 0))
            r[0] += 1
        if k.key == "wifi":
            lab("Hasło Wi-Fi", 0, 2)
            put(ttk.Entry(g, textvariable=var("password"), font=app.mono), 0, 2)
            next_row()
        # pola typu, po dwa w wierszu; pola ukryte przez użytkownika pomijamy, chyba że mają wartość
        hidden = vault.hidden_fields(settings, k.key)
        shown = [f for f in k.fields if f.key not in hidden or val.get(f.key)]
        self.hidden_now = [f for f in k.fields if f not in shown]

        def labx(text, column, on_remove, tip="Usuń to pole z formularza"):
            cell = ttk.Frame(g)
            cell.grid(row=r[0], column=column, sticky="ew", pady=(10, 3), padx=(0 if column == 0 else 10, 0))
            ttk.Label(cell, text=text.upper(), style="Field.TLabel").pack(side="left")
            x = ttk.Label(cell, text="✕", style="Small.TLabel", cursor="hand2")
            x.pack(side="right")
            x.bind("<Button-1>", lambda ev: on_remove())

        col = 0
        for f in shown:
            labx(f.label + ("" if f.kind != "date" else " (RRRR-MM-DD)"), col, lambda f=f: self._hide_field(f))
            v = var(f.key)
            if f.kind == "choice":
                w = ttk.Combobox(g, textvariable=v, values=list(f.choices))
                if not v.get() and f.key == "protocol" and k.protocol:
                    v.set(k.protocol)
            else:
                w = ttk.Entry(g, textvariable=v, show="•" if f.kind == "secret" and has_toggle and not ed["show_pw"] else "",
                              font=app.mono if f.mono else None)
                if f.kind == "secret":
                    self.secret_entries.append(w)
            put(w, col)
            if col == 1:
                next_row()
            col = 1 - col
        if col == 1:
            next_row()
        # własne pola
        for i, c in enumerate(ed["custom"]):
            col = i % 2
            labx(c["label"] + (" (ukryte)" if c.get("secret") else ""), col, lambda i=i: self._remove_custom(i),
                 "Usuń to pole z tego wpisu")
            cv = tk.StringVar(value=c.get("value", ""))
            self.custom_vars.append(cv)
            w = ttk.Entry(g, textvariable=cv, font=app.mono,
                          show="•" if c.get("secret") and has_toggle and not ed["show_pw"] else "")
            if c.get("secret"):
                self.secret_entries.append(w)
            put(w, col)
            if col == 1:
                next_row()
        if len(ed["custom"]) % 2 == 1:
            next_row()
        addrow = ttk.Frame(g)
        addrow.grid(row=r[0], column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.add_field_btn = ttk.Button(addrow, text="＋ Dodaj pole ▾", command=self._add_field_menu)
        self.add_field_btn.pack(side="left")
        if self.hidden_now:
            ttk.Label(addrow, text=f"Ukryte pola tego typu: {len(self.hidden_now)}", style="Small.TLabel").pack(side="left", padx=(10, 0))
        r[0] += 1
        if k.uses_url or val.get("url"):
            lab("Adres WWW / panel logowania", 0, 2)
            put(ttk.Entry(g, textvariable=var("url")), 0, 2)
            next_row()
        lab("Kategoria / grupa", 0)
        lab("Tagi (oddziel przecinkami)", 1)
        sid_cats = self._categories()
        put(ttk.Combobox(g, textvariable=var("category"), values=sid_cats), 0)
        put(ttk.Entry(g, textvariable=var("tags")), 1)
        next_row()
        lab("Notatki", 0, 2)
        c = app.colors
        self.notes = tk.Text(g, height=6, wrap="word", relief="flat", bd=0, padx=8, pady=6, bg=c["text_bg"],
                             fg=c["text_fg"], insertbackground=c["text_fg"], font=app.base_font,
                             highlightthickness=1, highlightbackground=c["empty"], highlightcolor=c["muted"])
        self.notes.insert("1.0", val.get("notes", ""))
        self.notes.grid(row=r[0] + 1, column=0, columnspan=2, sticky="ew")
        next_row()
        fav = tk.BooleanVar(value=bool(val.get("fav")))
        self.vars["fav"] = fav
        ttk.Checkbutton(g, text="Dodaj do ulubionych", variable=fav).grid(row=r[0], column=0, sticky="w", pady=(10, 0))
        btns = ttk.Frame(b)
        btns.pack(fill="x", pady=(16, 0))
        ttk.Button(btns, text="Zapisz", style="Accent.TButton", command=self.save).pack(side="left")
        ttk.Button(btns, text="Anuluj", command=self.cancel).pack(side="left", padx=(8, 0))
        ttk.Label(btns, text="Ctrl+S zapisuje, Esc anuluje", style="Muted.TLabel").pack(side="right")
        title.bind("<Return>", lambda ev: self.save())
        root = app.root
        root.bind("<Control-s>", lambda ev: self.save() if self.editing is not None else None)
        root.bind("<Escape>", lambda ev: self.cancel() if self.editing is not None and not app.dialogs else None)
        focus_later(title, 30)

    def _categories(self):
        ed = self.editing
        name = self.vars["target"].get() if "target" in self.vars else ""
        sid = next((s for s, n in ed["targets"] if n == name), ME)
        f = self.app.s.source(sid)
        return vault.categories(f.data) if f else []

    def _retype(self):
        before = BY_KEY.get(self.editing["values"].get("type"), BY_KEY["web"])
        self._collect()
        after = BY_KEY.get(self.editing["values"]["type"], BY_KEY["web"])
        val = self.editing["values"]
        if val.get("protocol", "") in ("", before.protocol):  # domyślny protokół podąża za typem
            val["protocol"] = after.protocol
        if not self.editing["id"]:
            self.editing["custom"] = [c for c in self.editing["custom"] if c.get("value")]
            self._apply_templates()
        self._render_form()

    def _use_generated(self, value, account: int | None = None):
        self._collect()
        if account is None:
            self.editing["values"]["password"] = value
        else:
            self.editing["accounts"][account]["password"] = value
        self.editing["show_pw"] = True
        self._render_form()

    def _apply_templates(self):
        ed = self.editing
        have = {c["label"].lower() for c in ed["custom"]}
        for t in vault.template_fields(self.app.s.data["settings"], ed["values"]["type"]):
            if t["label"].lower() not in have:
                ed["custom"].append(vault.new_custom(t["label"], t.get("secret", False)))

    def _hide_field(self, f):
        """Usuwa pole z formularza tego typu (u tej osoby). Wraca przez „＋ Dodaj pole”."""
        self._collect()
        val = self.editing["values"]
        if val.get(f.key):
            if not messagebox.askyesno("Usuń pole", f"Pole „{f.label}” ma wartość. Usunąć ją z tego wpisu i ukryć pole?",
                                       parent=self.app.root):
                return
            val[f.key] = ""
        vault.set_field_hidden(self.app.s.data["settings"], val["type"], f.key, True)
        self.app.changed(ME)
        self._render_form()
        self.app.flash(f"Ukryto pole „{f.label}”. Przywrócisz je przyciskiem „＋ Dodaj pole”.")

    def show_field(self, key):
        self._collect()
        vault.set_field_hidden(self.app.s.data["settings"], self.editing["values"]["type"], key, False)
        self.app.changed(ME)
        self._render_form()

    def restore_fields(self):
        self._collect()
        self.app.s.data["settings"].get("hiddenFields", {}).pop(self.editing["values"]["type"], None)
        self.app.changed(ME)
        self._render_form()

    def add_custom(self, label: str, secret: bool = False, template: bool = False):
        self._collect()
        ed = self.editing
        ed["custom"].append(vault.new_custom(label, secret))
        if template:
            vault.add_template_field(self.app.s.data["settings"], ed["values"]["type"], label, secret)
            self.app.changed(ME)
        self._render_form()

    def _remove_custom(self, i):
        self._collect()
        c = self.editing["custom"][i]
        if c.get("value") and not messagebox.askyesno("Usuń pole", f"Usunąć pole „{c['label']}” razem z wartością?",
                                                        parent=self.app.root):
            return
        del self.editing["custom"][i]
        settings = self.app.s.data["settings"]
        kind = self.editing["values"]["type"]
        if any(t["label"].lower() == c["label"].lower() for t in vault.template_fields(settings, kind)):
            if messagebox.askyesno("Usuń pole", f"Przestać dodawać pole „{c['label']}” do nowych wpisów tego typu?",
                                   parent=self.app.root):
                vault.remove_template_field(settings, kind, c["label"])
                self.app.changed(ME)
        self._render_form()

    def _add_field_menu(self):
        m = tk.Menu(self, tearoff=False)
        for f in self.hidden_now:
            m.add_command(label=f.label, command=lambda f=f: self.show_field(f.key))
        if self.hidden_now:
            m.add_separator()
            m.add_command(label="Przywróć wszystkie pola tego typu", command=self.restore_fields)
            m.add_separator()
        m.add_command(label="Własne pole…", command=self._custom_dialog)
        b = self.add_field_btn
        m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def _custom_dialog(self):
        from .dialogs import CustomFieldDialog
        k = BY_KEY.get(self.type_key(), BY_KEY["web"])
        d = CustomFieldDialog(self.app, k.group.lower()).show()
        self.app.root.wait_window(d)
        if d.result:
            self.add_custom(*d.result)

    def _add_account(self):
        self._collect()
        self.editing["accounts"].append(vault.new_account())
        self._render_form()
        self.after(50, lambda: self.sf.canvas.yview_moveto(1.0) if self.sf.winfo_exists() else None)

    def _remove_account(self, i: int):
        self._collect()
        del self.editing["accounts"][i]
        self._render_form()

    def save(self):
        if self.editing is None:
            return
        self._collect()
        ed = self.editing
        val = ed["values"]
        s = self.app.s
        k = BY_KEY[val["type"]]
        target = next((sid for sid, n in ed["targets"] if n == val["target"]), ME)
        extra = {f.key: val.get(f.key, "") for f in k.fields}
        old = s.find(ed["sid"], ed["id"]) if ed["id"] else None
        if old:  # pola innych typów zostają (np. po zmianie typu tam i z powrotem)
            extra = {**{kk: vv for kk, vv in (old.get("extra") or {}).items() if kk not in extra}, **extra}
        extra = kinds.clean_extra(k, extra)
        title = val["title"].strip() or kinds.address_of({"extra": extra, "url": val.get("url", "")}) or \
            val.get("username", "").strip() or k.label
        fields = {"type": k.key, "title": title, "username": val.get("username", "").strip(),
                  "password": val.get("password", ""), "url": val.get("url", "").strip(),
                  "category": val["category"].strip(), "tags": vault.parse_tags(val["tags"]), "notes": val["notes"],
                  "fav": bool(val["fav"]), "extra": extra,
                  "accounts": vault.clean_accounts(ed["accounts"]),
                  "custom": vault.clean_custom(ed["custom"])}
        if old:
            vault.update_entry(old, fields)
            e = old
            if target != ed["sid"]:
                s.move_entry(e, ed["sid"], target)
                self.app.changed(ed["sid"])
        else:
            e = vault.new_entry(**fields)
            s.source(target).data["entries"].append(e)
        data = s.source(target).data
        if fields["category"] and fields["category"] not in data.setdefault("categories", []):
            data["categories"].append(fields["category"])
        self.editing = None
        self.app.changed(target)
        self.main.refresh()
        self.main.select(target, e["id"])
        self.app.flash("Zapisano wpis.")

    def cancel(self):
        if self.editing is None:
            return
        ed = self.editing
        self.editing = None
        e = self.app.s.find(ed["sid"], ed["id"]) if ed["id"] else None
        if e:
            self.main.select(ed["sid"], e["id"])
        else:
            self.show_scope(self.main.scope())

    def confirm_discard(self) -> bool:
        if messagebox.askyesno("Niezapisane zmiany", "Porzucić zmiany w edytowanym wpisie?", parent=self.app.root):
            self.editing = None
            return True
        return False
