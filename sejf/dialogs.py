"""Okna dialogowe: generator, import, eksport, ustawienia, profile klientów, weryfikacja dwuetapowa."""
from __future__ import annotations

import getpass
import os
import re
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

from . import __version__, crypto, totp, vault
from .generator import generate
from .session import ME, PROFILE_EXT, Session
from .widgets import PROFILE_TYPES, Dialog, StrengthBar, focus_later, readonly

LOCK_CHOICES = [("1 minuta", 1), ("5 minut", 5), ("15 minut", 15), ("30 minut", 30), ("1 godzina", 60), ("Nigdy", 0)]
CLIP_CHOICES = [("15 sekundach", 15), ("30 sekundach", 30), ("1 minucie", 60), ("Nie czyść", 0)]
THEME_CHOICES = [("Taki jak w systemie", "system"), ("Jasny", "light"), ("Ciemny", "dark")]


def profile_password() -> str:
    """Hasło profilu proponowane domyślnie: długie, bez znaków łatwych do pomylenia przy dyktowaniu."""
    return generate(length=24, symbols=False, noAmb=True)


def slug(name: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]+", " ", name).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:60] or "klient"


def combo(parent, var, choices, current, on_change=None, width=30):
    names = [n for n, _ in choices]
    var.set(next((n for n, v in choices if v == current), names[0]))
    cb = ttk.Combobox(parent, textvariable=var, values=names, state="readonly", width=width)
    if on_change:
        cb.bind("<<ComboboxSelected>>", lambda e: on_change(dict(choices)[var.get()]))
    return cb


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
        ttk.Entry(row, textvariable=self.out, state="readonly", font=app.mono_big, width=34).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Losuj", command=self.regen).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Kopiuj", command=self.copy).pack(side="left", padx=(6, 0))
        self.meter = StrengthBar(b, app)
        self.meter.pack(anchor="w", pady=(8, 0))
        lr = ttk.Frame(b)
        lr.pack(fill="x", pady=(18, 0))
        ttk.Label(lr, text="DŁUGOŚĆ", style="Field.TLabel").pack(side="left")
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
            self.app.changed(ME)

    def copy(self):
        if self.out.get() and not self.out.get().startswith("Zaznacz"):
            self.app.copy(self.out.get(), "hasło", secret=True)

    def use(self):
        v = self.out.get()
        if v and not v.startswith("Zaznacz"):
            cb = self.use_cb
            self.close()
            cb(v)


# =============================================================================
@dataclass
class ImportPreview:
    path: str
    fmt: str
    found: int
    entries: list


class ImportDialog(Dialog):
    def __init__(self, app, preview: ImportPreview, target: str = ME):
        super().__init__(app, "Import haseł")
        self.preview = preview
        b = self.body
        ttk.Label(b, text="Import z pliku CSV", style="Title.TLabel").pack(anchor="w")
        box, info = app.card(b, 14)
        box.pack(fill="x", pady=(12, 0))
        self.info = info
        self.targets = [(ME, "Moje hasła")] + [(pid, p.name) for pid, p in app.s.profiles.items() if p.file]
        ttk.Label(b, text="IMPORTUJ DO", style="Field.TLabel").pack(anchor="w", pady=(16, 4))
        self.target = tk.StringVar(value=dict(self.targets).get(target, "Moje hasła"))
        cb = ttk.Combobox(b, textvariable=self.target, values=[n for _, n in self.targets], state="readonly")
        cb.pack(fill="x")
        cb.bind("<<ComboboxSelected>>", lambda e: self.update_summary())
        self.cat = tk.StringVar(value="Zaimportowane")
        if any(not e["category"] for e in preview.entries):
            ttk.Label(b, text="KATEGORIA DLA WPISÓW BEZ KATEGORII", style="Field.TLabel").pack(anchor="w", pady=(16, 4))
            ttk.Entry(b, textvariable=self.cat).pack(fill="x")
        ttk.Label(b, text="Po imporcie usuń plik CSV z dysku. Nie jest zaszyfrowany i każdy, kto go otworzy, "
                          "zobaczy Twoje hasła.", style="Warn.TLabel", wraplength=app.px(420), justify="left").pack(fill="x", pady=(14, 0))
        self.go_btn, _ = self.buttons(("Importuj", self.go, "Accent.TButton", "left"), ("Anuluj", self.close, None, "right"))
        self.update_summary()

    def sid(self):
        return next((s for s, n in self.targets if n == self.target.get()), ME)

    def update_summary(self):
        from .csvio import without_duplicates
        for w in self.info.winfo_children():
            w.destroy()
        p = self.preview
        self.fresh = without_duplicates(self.app.s.source(self.sid()).data["entries"], p.entries)
        dups = p.found - len(self.fresh)
        lines = [("Plik", os.path.basename(p.path)), ("Format", p.fmt), ("Znaleziono", vault.wpisy(p.found))]
        if dups:
            lines.append(("Pominę powtórzenia", str(dups)))
        lines.append(("Do dodania", vault.wpisy(len(self.fresh))))
        for i, (k, v) in enumerate(lines):
            ttk.Label(self.info, text=k, style="Muted.TLabel").grid(row=i, column=0, sticky="w", padx=(0, 18), pady=1)
            ttk.Label(self.info, text=v, style="Strong.TLabel").grid(row=i, column=1, sticky="w", pady=1)
        self.go_btn.configure(text=f"Importuj {vault.wpisy(len(self.fresh))}", state="normal" if self.fresh else "disabled")

    def go(self):
        n = self.app.apply_import(self.fresh, self.cat.get().strip(), self.sid())
        self.close()
        messagebox.showinfo("Import zakończony", f"Zaimportowano {vault.wpisy(n)}.\n\nUsuń teraz plik CSV z dysku.",
                            parent=self.app.root)


class ExportDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, "Eksport i kopia zapasowa")
        b = self.body
        box, card = app.card(b, 16)
        box.pack(fill="x", pady=(0, 12))
        ttk.Label(card, text="Zaszyfrowana kopia osobistego sejfu", style="Strong.TLabel").pack(anchor="w")
        ttk.Label(card, text="Kopia Twoich haseł i kluczy do profili klientów, chroniona hasłem głównym.\n"
                             "Profile klientów to osobne pliki; ich kopie zapiszesz w oknie „Udostępnij”.",
                  style="Muted.TLabel", justify="left").pack(anchor="w", pady=(4, 10))
        ttk.Button(card, text="Zapisz kopię…", style="Accent.TButton", command=lambda: (self.close(), app.export_backup())).pack(anchor="w")
        box, card = app.card(b, 16)
        box.pack(fill="x", pady=(0, 12))
        ttk.Label(card, text="Plik CSV bez szyfrowania", style="Strong.TLabel").pack(anchor="w")
        ttk.Label(card, text="Do przeniesienia haseł do innego programu albo arkusza. Każdy, kto\n"
                             "otworzy ten plik, zobaczy wszystkie hasła.", style="Muted.TLabel", justify="left").pack(anchor="w", pady=(4, 8))
        targets = [(ME, "Moje hasła")] + [(pid, p.name) for pid, p in app.s.profiles.items() if p.file]
        sel = tk.StringVar(value=targets[0][1])
        row = ttk.Frame(card)
        row.pack(fill="x")
        ttk.Combobox(row, textvariable=sel, values=[n for _, n in targets], state="readonly", width=28).pack(side="left")
        ttk.Button(row, text="Zapisz CSV…", command=lambda: (self.close(), app.export_csv(
            next(s for s, n in targets if n == sel.get())))).pack(side="left", padx=(8, 0))
        ttk.Button(b, text="Zamknij", command=self.close).pack(anchor="e")


class CustomFieldDialog(Dialog):
    """Własne pole wpisu, opcjonalnie dodawane do wszystkich nowych wpisów danego typu."""

    def __init__(self, app, group: str):
        super().__init__(app, "Własne pole")
        self.result = None
        b = self.body
        ttk.Label(b, text="NAZWA POLA", style="Field.TLabel").pack(anchor="w", pady=(0, 4))
        self.name = tk.StringVar()
        e = ttk.Entry(b, textvariable=self.name, width=36)
        e.pack(fill="x")
        e.bind("<Return>", lambda ev: self.ok())
        ttk.Label(b, text="np. Numer inwentarzowy, PIN do drukarki, Konto Google", style="Small.TLabel").pack(anchor="w", pady=(4, 0))
        self.secret = tk.BooleanVar()
        self.template = tk.BooleanVar()
        ttk.Checkbutton(b, text="Wartość tajna (ukrywana jak hasło)", variable=self.secret).pack(anchor="w", pady=(12, 0))
        ttk.Checkbutton(b, text=f"Dodawaj to pole do nowych wpisów: {group}", variable=self.template).pack(anchor="w", pady=(6, 0))
        self.err = ttk.Label(b, style="Error.TLabel")
        self.err.pack(anchor="w", pady=(6, 0))
        self.buttons(("Dodaj pole", self.ok, "Accent.TButton", "left"), ("Anuluj", self.close, None, "right"))
        focus_later(e, 30)

    def ok(self):
        name = self.name.get().strip()
        if not name:
            self.err.configure(text="Wpisz nazwę pola.")
            return
        self.result = (name, self.secret.get(), self.template.get())
        self.close()


class HistoryDialog(Dialog):
    def __init__(self, app, e):
        super().__init__(app, "Poprzednie hasła")
        b = self.body
        ttk.Label(b, text=e["title"], style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        for h in e["history"]:
            r = ttk.Frame(b)
            r.pack(fill="x", pady=3)
            readonly(r, h["password"], app, width=26).pack(side="left")
            who = h.get("label") or h.get("login") or ""
            ttk.Label(r, text=(who + "  ·  " if who else "") + vault.fmt_date(h.get("changed", "")),
                      style="Muted.TLabel").pack(side="left", padx=10)
            ttk.Button(r, text="Kopiuj", command=lambda p=h["password"]: app.copy(p, "hasło", secret=True)).pack(side="right")
        ttk.Button(b, text="Zamknij", command=self.close).pack(anchor="e", pady=(14, 0))


class AskStringDialog(Dialog):
    def __init__(self, app, title, label, button="OK", secret=False, note=""):
        super().__init__(app, title)
        self.result = None
        self.var = tk.StringVar()
        if note:
            ttk.Label(self.body, text=note, wraplength=app.px(380), justify="left").pack(anchor="w", pady=(0, 10))
        ttk.Label(self.body, text=label.upper(), style="Field.TLabel").pack(anchor="w", pady=(0, 4))
        e = ttk.Entry(self.body, textvariable=self.var, width=36, show="•" if secret else "")
        e.pack(fill="x")
        e.bind("<Return>", lambda ev: self.ok())
        self.buttons((button, self.ok, "Accent.TButton", "left"), ("Anuluj", self.close, None, "right"))
        focus_later(e, 30)

    def ok(self):
        self.result = self.var.get().strip()
        self.close()


# =============================================================================
class SettingsDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, "Ustawienia")
        b = self.body
        st = app.s.data["settings"]
        cols = ttk.Frame(b)
        cols.pack(fill="both")
        left = ttk.Frame(cols)
        left.pack(side="left", fill="y", anchor="n")
        right = ttk.Frame(cols)
        right.pack(side="left", fill="y", anchor="n", padx=(28, 0))

        def set_lock(v):
            st["autoLockMin"] = v
            app.changed(ME)

        def set_clip(v):
            st["clipSec"] = v
            app.changed(ME)

        for label, choices, cur, fn in (("BLOKUJ SEJF PO BEZCZYNNOŚCI", LOCK_CHOICES, st["autoLockMin"], set_lock),
                                        ("CZYŚĆ SKOPIOWANE HASŁO ZE SCHOWKA PO", CLIP_CHOICES, st["clipSec"], set_clip),
                                        ("MOTYW", THEME_CHOICES, app.cfg.get("theme", "system"),
                                         lambda v: app.after_dialog(lambda: app.set_theme(v)))):
            ttk.Label(left, text=label, style="Field.TLabel").pack(anchor="w", pady=(0, 4))
            combo(left, tk.StringVar(), choices, cur, fn).pack(anchor="w", pady=(0, 14))

        self.on_system = tk.BooleanVar(value=st.get("lockOnSystem", True))

        def set_on_system():
            st["lockOnSystem"] = bool(self.on_system.get())
            app.changed(ME)
        ttk.Checkbutton(left, text="Blokuj, gdy zablokuję Windows (Win+L)\nalbo komputer przejdzie w uśpienie",
                        variable=self.on_system, command=set_on_system).pack(anchor="w", pady=(0, 14))
        ttk.Separator(left).pack(fill="x", pady=(4, 14))
        ttk.Label(left, text="Zmiana hasła głównego", style="Strong.TLabel").pack(anchor="w")
        self.cur, self.n1, self.n2 = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for label, var in (("OBECNE HASŁO GŁÓWNE", self.cur), ("NOWE HASŁO GŁÓWNE", self.n1)):
            ttk.Label(left, text=label, style="Field.TLabel").pack(anchor="w", pady=(10, 4))
            ttk.Entry(left, textvariable=var, show="•", width=34).pack(fill="x")
        self.meter = StrengthBar(left, app)
        self.meter.pack(anchor="w", pady=(6, 0))
        self.n1.trace_add("write", lambda *a: self.meter.set(self.n1.get()))
        ttk.Label(left, text="POWTÓRZ NOWE HASŁO", style="Field.TLabel").pack(anchor="w", pady=(10, 4))
        ttk.Entry(left, textvariable=self.n2, show="•", width=34).pack(fill="x")
        self.err = ttk.Label(left, style="Error.TLabel", wraplength=app.px(300))
        self.err.pack(anchor="w", pady=(6, 0))
        self.btn = ttk.Button(left, text="Zmień hasło główne", command=self.change)
        self.btn.pack(anchor="w", pady=(4, 0))

        self.tf = ttk.Frame(right)
        self.tf.pack(fill="x", anchor="n")
        self.render_totp()
        ttk.Separator(right).pack(fill="x", pady=(16, 14))
        ttk.Label(right, text="Udostępnianie profili", style="Strong.TLabel").pack(anchor="w")
        ttk.Label(right, text=f"Jesteś widoczny jako: {app.s.identity.get('name', '')}\n"
                              f"Odcisk klucza: {crypto.fingerprint(app.s.identity['kid'])}", style="Muted.TLabel",
                  justify="left").pack(anchor="w", pady=(6, 8))
        ttk.Button(right, text="Mój kod…", command=lambda: (self.close(), app.open_my_code())).pack(anchor="w")
        bt = ttk.Frame(b)
        bt.pack(fill="x", pady=(18, 0))
        ttk.Label(bt, text=f"Sejf {__version__}", style="Muted.TLabel").pack(side="left")
        ttk.Button(bt, text="Zamknij", command=self.close).pack(side="right")

    def render_totp(self):
        app = self.app
        f = self.tf
        for w in f.winfo_children():
            w.destroy()
        ttk.Label(f, text="Weryfikacja dwuetapowa", style="Strong.TLabel").pack(anchor="w")
        t = app.s.totp
        if not t:
            ttk.Label(f, text="Oprócz hasła głównego program okresowo poprosi o kod z aplikacji Google Authenticator "
                              "na telefonie: na każdym nowym komputerze i potem co wybrany czas.",
                      style="Muted.TLabel", wraplength=app.px(300), justify="left").pack(anchor="w", pady=(6, 10))
            ttk.Button(f, text="Włącz…", style="Accent.TButton", command=self.enable_totp).pack(anchor="w")
            return
        ttk.Label(f, text="Włączona. Kod z aplikacji jest potrzebny na nowym komputerze i co wybrany czas.",
                  style="Muted.TLabel", wraplength=app.px(300), justify="left").pack(anchor="w", pady=(6, 10))
        ttk.Label(f, text="PYTAJ O KOD", style="Field.TLabel").pack(anchor="w", pady=(0, 4))

        def set_period(v):
            app.s.set_totp_period(v)
            app.changed(ME)

        combo(f, tk.StringVar(), totp.PERIODS, int(t.get("period", totp.DEFAULT_PERIOD)), set_period).pack(anchor="w")
        left = app.s.recovery_left()
        ttk.Label(f, text=f"Kody zapasowe: zostało {left}", style="Warn.TLabel" if left <= 3 else "Muted.TLabel").pack(anchor="w", pady=(12, 4))
        row = ttk.Frame(f)
        row.pack(anchor="w")
        ttk.Button(row, text="Nowe kody zapasowe…", command=self.new_codes).pack(side="left")
        ttk.Button(row, text="Wyłącz…", command=self.disable_totp).pack(side="left", padx=(6, 0))

    def _ask_code(self, title, button) -> bool:
        d = AskStringDialog(self.app, title, "Kod z aplikacji", button,
                            note="Wpisz aktualny 6-cyfrowy kod z aplikacji Google Authenticator.").show()
        self.app.root.wait_window(d)
        if not d.result:
            return False
        if totp.verify(self.app.s.totp["secret"], d.result):
            return True
        messagebox.showerror(title, "Nieprawidłowy kod.", parent=self)
        return False

    def enable_totp(self):
        d = TotpSetupDialog(self.app).show()
        self.wait_window(d)
        if self.winfo_exists():
            self.render_totp()

    def disable_totp(self):
        if self._ask_code("Wyłącz weryfikację dwuetapową", "Wyłącz"):
            self.app.s.disable_totp()
            self.app.save_config()
            self.render_totp()
            self.app.flash("Wyłączono weryfikację dwuetapową.")

    def new_codes(self):
        if self._ask_code("Nowe kody zapasowe", "Dalej"):
            codes = totp.new_recovery_codes()
            self.app.s.totp["recovery"] = [totp.hash_recovery(c) for c in codes]
            self.app.s._touch_security()
            self.app.flush_save(ME)
            RecoveryCodesDialog(self.app, codes).show()
            self.render_totp()

    def change(self):
        problem = Session.check_new_password(self.n1.get(), self.n2.get())
        if problem:
            self.err.configure(text=problem)
            return
        self.err.configure(text="")
        self.btn.configure(text="Zmieniam…", state="disabled")
        cur, new = self.cur.get(), self.n1.get()
        self.app.flush_save(ME)

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


class TotpSetupDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, "Weryfikacja dwuetapowa")
        self.secret = totp.new_secret()
        account = getpass.getuser() or "Sejf"
        self.uri = totp.otpauth_uri(self.secret, f"{account} ({app.s.file_name})")
        b = self.body
        ttk.Label(b, text="Dodaj Sejf do aplikacji na telefonie", style="Title.TLabel").pack(anchor="w")
        ttk.Label(b, text="1. Zainstaluj Google Authenticator (albo Microsoft Authenticator, Authy).\n"
                          "2. W aplikacji wybierz „Dodaj kod” → „Zeskanuj kod QR”.\n"
                          "3. Wpisz poniżej 6-cyfrowy kod, który pokaże aplikacja.",
                  justify="left").pack(anchor="w", pady=(8, 12))
        row = ttk.Frame(b)
        row.pack(fill="x")
        self.qr = self.qr_image()
        if self.qr is not None:
            tk.Label(row, image=self.qr, bg="#ffffff", bd=0).pack(side="left")
        side = ttk.Frame(row)
        side.pack(side="left", fill="both", expand=True, padx=(18, 0))
        ttk.Label(side, text="NIE MOŻESZ ZESKANOWAĆ? WPISZ KLUCZ RĘCZNIE", style="Field.TLabel").pack(anchor="w")
        readonly(side, totp.group(self.secret), app, width=26).pack(anchor="w", fill="x", pady=(4, 4))
        ttk.Button(side, text="Kopiuj klucz", command=lambda: app.copy(self.secret, "klucz", secret=True)).pack(anchor="w")
        ttk.Label(side, text="Rodzaj: na podstawie czasu", style="Small.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Label(side, text="PYTAJ O KOD", style="Field.TLabel").pack(anchor="w", pady=(16, 4))
        self.period = tk.StringVar()
        combo(side, self.period, totp.PERIODS, totp.DEFAULT_PERIOD, width=24).pack(anchor="w")
        ttk.Label(side, text="Na nowym komputerze program zawsze zapyta o kod.", style="Small.TLabel",
                  wraplength=app.px(240), justify="left").pack(anchor="w", pady=(4, 0))
        ttk.Label(b, text="KOD Z APLIKACJI", style="Field.TLabel").pack(anchor="w", pady=(16, 4))
        self.code = tk.StringVar()
        e = ttk.Entry(b, textvariable=self.code, font=app.mono_big, width=10, justify="center")
        e.pack(anchor="w")
        e.bind("<Return>", lambda ev: self.confirm())
        self.err = ttk.Label(b, style="Error.TLabel")
        self.err.pack(anchor="w", pady=(4, 0))
        self.buttons(("Włącz", self.confirm, "Accent.TButton", "left"), ("Anuluj", self.close, None, "right"))
        focus_later(e, 50)

    def qr_image(self):
        try:
            import segno
        except ImportError:
            return None
        uri = segno.make(self.uri, error="m").png_data_uri(scale=max(4, self.app.px(5)), border=2)
        return tk.PhotoImage(data=uri.split(",", 1)[1])

    def confirm(self):
        if not totp.verify(self.secret, self.code.get()):
            self.err.configure(text="Nieprawidłowy kod. Wpisz kod, który aktualnie pokazuje aplikacja.")
            return
        codes = totp.new_recovery_codes()
        period = dict(totp.PERIODS)[self.period.get()]
        self.app.s.enable_totp(self.secret, period, codes)
        self.app.save_config()
        self.close()
        RecoveryCodesDialog(self.app, codes).show()
        self.app.flash("Włączono weryfikację dwuetapową.")


class RecoveryCodesDialog(Dialog):
    def __init__(self, app, codes):
        super().__init__(app, "Kody zapasowe")
        b = self.body
        ttk.Label(b, text="Zapisz kody zapasowe", style="Title.TLabel").pack(anchor="w")
        ttk.Label(b, text="Gdy nie będziesz mieć telefonu, wpisz jeden z tych kodów zamiast kodu z aplikacji.\n"
                          "Każdy kod działa tylko raz. Zapisz je poza tym komputerem, np. wydrukuj albo\n"
                          "zachowaj w innym menedżerze haseł. Ten widok pokazuje je tylko teraz.",
                  justify="left").pack(anchor="w", pady=(8, 12))
        box, card = app.card(b, 14)
        box.pack(fill="x")
        for i, c in enumerate(codes):
            ttk.Label(card, text=c, style="Mono.TLabel").grid(row=i // 2, column=i % 2, padx=(0, 40), pady=3, sticky="w")
        self.ok = tk.BooleanVar()
        ttk.Button(b, text="Kopiuj kody", command=lambda: app.copy("\n".join(codes), "kody zapasowe")).pack(anchor="w", pady=(12, 0))
        ttk.Checkbutton(b, text="Zapisałem kody w bezpiecznym miejscu", variable=self.ok,
                        command=lambda: self.done.configure(state="normal" if self.ok.get() else "disabled")).pack(anchor="w", pady=(12, 0))
        self.done, = self.buttons(("Gotowe", self.close, "Accent.TButton", "right"))
        self.done.configure(state="disabled")
        self.protocol("WM_DELETE_WINDOW", lambda: self.close() if self.ok.get() else None)
        self.unbind("<Escape>")


# =============================================================================
class NewProfileDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, "Nowy profil klienta")
        b = self.body
        ttk.Label(b, text="Nowy profil klienta", style="Title.TLabel").pack(anchor="w")
        ttk.Label(b, text="Profil to osobny zaszyfrowany plik z hasłami do serwerów, urządzeń i kont klienta. "
                          "Możesz go później przekazać współpracownikowi razem z hasłem profilu.",
                  style="Muted.TLabel", wraplength=app.px(480), justify="left").pack(anchor="w", pady=(4, 6))
        self.vars = {k: tk.StringVar() for k in ("name", "company", "nip", "address", "contact", "phone", "email")}
        g = ttk.Frame(b)
        g.pack(fill="x")
        g.columnconfigure(0, weight=1, uniform="c")
        g.columnconfigure(1, weight=1, uniform="c")
        fields = [("name", "Nazwa klienta (krótka)", 0, 2), ("company", "Pełna nazwa firmy", 0, 1), ("nip", "NIP", 1, 1),
                  ("address", "Adres", 0, 2), ("contact", "Osoba kontaktowa", 0, 1), ("phone", "Telefon", 1, 1),
                  ("email", "E-mail", 0, 2)]
        r = 0
        for key, label, col, span in fields:
            ttk.Label(g, text=label.upper(), style="Field.TLabel").grid(row=r, column=col, columnspan=span, sticky="w",
                                                                          pady=(10, 3), padx=(0 if col == 0 else 10, 0))
            ttk.Entry(g, textvariable=self.vars[key]).grid(row=r + 1, column=col, columnspan=span, sticky="ew",
                                                           padx=(0 if col == 0 else 10, 0))
            if col + span == 2:
                r += 2
        self.vars["name"].trace_add("write", lambda *a: self.update_path())
        ttk.Label(b, text="DOSTĘP", style="Field.TLabel").pack(anchor="w", pady=(16, 3))
        ttk.Label(b, text="Ty masz dostęp swoim kluczem. Współpracowników dodasz później w oknie „Udostępnij” "
                          "ich kodami, bez przekazywania żadnego hasła.", style="Small.TLabel",
                  wraplength=app.px(480), justify="left").pack(anchor="w")
        self.use_pw = tk.BooleanVar(value=False)
        ttk.Checkbutton(b, text="Pozwól też otwierać profil hasłem (wygodne, ale mniej bezpieczne)", variable=self.use_pw,
                        command=self._toggle_pw).pack(anchor="w", pady=(8, 0))
        self.pr = ttk.Frame(b)
        self.pw = tk.StringVar(value=profile_password())
        ttk.Entry(self.pr, textvariable=self.pw, font=app.mono).pack(side="left", fill="x", expand=True)
        ttk.Button(self.pr, text="Losuj", command=lambda: self.pw.set(profile_password())).pack(side="left", padx=(6, 0))
        ttk.Button(self.pr, text="Kopiuj", command=lambda: app.copy(self.pw.get(), "hasło profilu", secret=True)).pack(side="left", padx=(6, 0))
        self.pr_anchor = ttk.Frame(b)
        self.pr_anchor.pack(fill="x")
        ttk.Label(b, text="PLIK PROFILU", style="Field.TLabel").pack(anchor="w", pady=(16, 3))
        fr = ttk.Frame(b)
        fr.pack(fill="x")
        self.path = tk.StringVar()
        self.folder = os.path.dirname(app.s.path or "") or os.path.expanduser("~")
        ttk.Entry(fr, textvariable=self.path, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(fr, text="Zmień…", command=self.pick).pack(side="left", padx=(6, 0))
        self.custom_path = False
        self.update_path()
        self.err = ttk.Label(b, style="Error.TLabel", wraplength=app.px(480))
        self.err.pack(anchor="w", pady=(6, 0))
        self.btn, _ = self.buttons(("Utwórz profil", self.create, "Accent.TButton", "left"), ("Anuluj", self.close, None, "right"))

    def _toggle_pw(self):
        if self.use_pw.get():
            self.pr.pack(in_=self.pr_anchor, fill="x", pady=(6, 0))
        else:
            self.pr.pack_forget()

    def update_path(self):
        if not self.custom_path:
            self.path.set(os.path.join(self.folder, slug(self.vars["name"].get()) + PROFILE_EXT))

    def pick(self):
        p = filedialog.asksaveasfilename(parent=self, title="Gdzie zapisać profil klienta?", filetypes=PROFILE_TYPES,
                                         initialdir=os.path.dirname(self.path.get()),
                                         initialfile=os.path.basename(self.path.get()), defaultextension=PROFILE_EXT)
        if p:
            self.custom_path = True
            self.folder = os.path.dirname(p)
            self.path.set(p)

    def create(self):
        name = self.vars["name"].get().strip()
        if not name:
            self.err.configure(text="Wpisz nazwę klienta.")
            return
        pw = self.pw.get() if self.use_pw.get() else None
        problem = Session.check_profile_password(pw) if pw is not None else None
        if problem:
            self.err.configure(text=problem)
            return
        path = self.path.get()
        if os.path.exists(path):
            self.err.configure(text="Plik o tej nazwie już istnieje. Zmień nazwę klienta albo wybierz inne miejsce. "
                                    "Jeśli to profil od współpracownika, użyj „Dodaj profil z pliku”.")
            return
        info = {k: v.get().strip() for k, v in self.vars.items() if k != "name" and v.get().strip()}
        self.btn.configure(text="Tworzę…", state="disabled")

        def done(p):
            self.close()
            self.app.profile_ready(p.id, f"Utworzono profil „{p.name}”.")

        def fail(e):
            if self.winfo_exists():
                self.err.configure(text=f"Nie udało się utworzyć profilu: {e}")
                self.btn.configure(text="Utwórz profil", state="normal")

        self.app.run_bg(lambda: self.app.s.create_profile(path, name, pw, info), done, fail)


class ProfilePasswordDialog(Dialog):
    """Hasło do profilu: przy dodawaniu pliku od współpracownika albo gdy hasło zmieniono."""

    def __init__(self, app, path: str, pid: str | None = None):
        super().__init__(app, "Hasło profilu")
        self.path, self.pid = path, pid
        b = self.body
        ttk.Label(b, text="Dodaj profil klienta" if pid is None else "Nowe hasło profilu", style="Title.TLabel").pack(anchor="w")
        ttk.Label(b, text=os.path.basename(path), style="Mono.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Label(b, text=os.path.dirname(path), style="Small.TLabel", wraplength=app.px(400)).pack(anchor="w")
        note = ("Nie masz jeszcze dostępu do tego profilu. Są dwie możliwości:" if pid is None else
                "Nie masz już dostępu do tego profilu: ktoś zmienił jego hasło albo odebrał Ci dostęp. Są dwie możliwości:")
        ttk.Label(b, text=note, wraplength=app.px(420), justify="left").pack(anchor="w", pady=(12, 0))
        box, card = app.card(b, 12)
        box.pack(fill="x", pady=(10, 0))
        ttk.Label(card, text="1. Wyślij swój kod osobie, która ma dostęp", style="Strong.TLabel").pack(anchor="w")
        ttk.Label(card, text="Doda Cię w oknie „Udostępnij”. Potem wybierz ten plik jeszcze raz, hasło nie będzie potrzebne.",
                  style="Small.TLabel", wraplength=app.px(400), justify="left").pack(anchor="w", pady=(2, 6))
        ttk.Button(card, text="Kopiuj mój kod", command=lambda: app.copy(app.s.my_code(), "Twój kod")).pack(anchor="w")
        ttk.Label(b, text="2. ALBO WPISZ HASŁO PROFILU", style="Field.TLabel").pack(anchor="w", pady=(14, 4))
        self.pw = tk.StringVar()
        e = ttk.Entry(b, textvariable=self.pw, show="•", font=app.mono)
        e.pack(fill="x")
        e.bind("<Return>", lambda ev: self.go())
        self.pw.trace_add("write", lambda *a: self.err.configure(text=""))
        self.err = ttk.Label(b, style="Error.TLabel", wraplength=app.px(400))
        self.err.pack(anchor="w", pady=(6, 0))
        self.btn, _ = self.buttons(("Otwórz hasłem", self.go, "Accent.TButton", "left"),
                                   ("Zamknij", self.close, None, "right"))
        focus_later(e, 50)

    def go(self):
        pw = self.pw.get()
        if not pw:
            self.err.configure(text="Wpisz hasło profilu.")
            return
        self.btn.configure(state="disabled")
        s = self.app.s

        def work():
            if self.pid is None:
                return s.add_profile(self.path, pw)
            return s.relink_profile(self.pid, password=pw)

        def done(p):
            self.close()
            self.app.profile_ready(p.id, f"Dodano profil „{p.name}”." if self.pid is None else "Odzyskano dostęp do profilu.")

        def fail(e):
            if self.winfo_exists():
                self.err.configure(text=str(e) if isinstance(e, crypto.VaultError) else f"Nie udało się otworzyć pliku: {e}")
                self.btn.configure(state="normal")

        self.app.run_bg(work, done, fail)


class ProfileInfoDialog(Dialog):
    def __init__(self, app, pid):
        super().__init__(app, "Dane klienta")
        self.pid = pid
        p = app.s.profiles[pid]
        info = p.data.get("info") or {}
        b = self.body
        ttk.Label(b, text="Dane klienta", style="Title.TLabel").pack(anchor="w")
        g = ttk.Frame(b)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)
        self.vars = {"name": tk.StringVar(value=p.name)}
        rows = [("name", "Nazwa klienta (krótka)")] + list(vault.PROFILE_INFO_FIELDS)
        for i, (key, label) in enumerate(rows):
            ttk.Label(g, text=label.upper(), style="Field.TLabel").grid(row=i, column=0, sticky="nw", pady=(10, 0), padx=(0, 14))
            if key == "notes":
                c = app.colors
                self.notes = tk.Text(g, height=5, width=46, wrap="word", relief="flat", bd=0, padx=8, pady=6,
                                     bg=c["text_bg"], fg=c["text_fg"], insertbackground=c["text_fg"], font=app.base_font,
                                     highlightthickness=1, highlightbackground=c["empty"], highlightcolor=c["muted"])
                self.notes.insert("1.0", info.get("notes", ""))
                self.notes.grid(row=i, column=1, sticky="ew", pady=(8, 0))
            else:
                v = self.vars.setdefault(key, tk.StringVar(value=info.get(key, "")))
                ttk.Entry(g, textvariable=v, width=46).grid(row=i, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(b, text="Zmiany zobaczą wszystkie osoby korzystające z tego profilu.", style="Small.TLabel").pack(anchor="w", pady=(10, 0))
        self.buttons(("Zapisz", self.save, "Accent.TButton", "left"), ("Anuluj", self.close, None, "right"))

    def save(self):
        name = self.vars["name"].get().strip() or "Klient"
        info = {k: v.get().strip() for k, v in self.vars.items() if k != "name" and v.get().strip()}
        notes = self.notes.get("1.0", "end-1c").strip()
        if notes:
            info["notes"] = notes
        self.app.s.update_profile_info(self.pid, name, info)
        self.app.changed(self.pid)
        self.app.changed(ME)
        self.close()
        self.app.profile_ready(self.pid, "Zapisano dane klienta.")


class ShareDialog(Dialog):
    """Osoby z dostępem do profilu, dostęp hasłem, plik."""

    def __init__(self, app, pid):
        super().__init__(app, "Udostępnij profil")
        self.pid = pid
        self.render()

    def render(self):
        app, pid = self.app, self.pid
        for w in self.body.winfo_children():
            w.destroy()
        p = app.s.profiles[pid]
        b = self.body
        me = app.s.identity["kid"]
        ttk.Label(b, text=f"Udostępnij „{p.name}”", style="Title.TLabel").pack(anchor="w")
        ttk.Label(b, text="Każda osoba ma własny klucz. Żeby dodać kogoś, poproś o jego kod (w jego programie: "
                          "Ustawienia → Mój kod) i wklej go poniżej. Odebranie dostępu wymienia klucz profilu.",
                  wraplength=app.px(500), justify="left").pack(anchor="w", pady=(6, 0))

        box, card = app.card(b, 12)
        box.pack(fill="x", pady=(12, 0))
        ttk.Label(card, text="OSOBY Z DOSTĘPEM", style="Field.TLabel").pack(anchor="w")
        lst = ttk.Frame(card)
        lst.pack(fill="x", pady=(6, 0))
        lst.columnconfigure(0, weight=1)
        for i, m in enumerate(sorted(app.s.members(pid), key=lambda m: (m["id"] != me, m.get("name", "").lower()))):
            name = m.get("name") or "Bez nazwy"
            ttk.Label(lst, text=name + ("  (Ty)" if m["id"] == me else ""), style="Strong.TLabel").grid(row=i, column=0, sticky="w", pady=3)
            ttk.Label(lst, text=crypto.fingerprint(m["id"]), style="Small.TLabel").grid(row=i, column=1, sticky="w", padx=(12, 12))
            if m["id"] != me:
                ttk.Button(lst, text="Odbierz dostęp…", command=lambda m=m: self.remove(m)).grid(row=i, column=2, sticky="e")
        row = ttk.Frame(card)
        row.pack(fill="x", pady=(10, 0))
        self.code = tk.StringVar()
        ttk.Entry(row, textvariable=self.code, font=app.mono).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Dodaj osobę", style="Accent.TButton", command=self.add).pack(side="left", padx=(6, 0))
        ttk.Label(card, text="Wklej kod osoby (zaczyna się od SEJF1.). Po dodaniu ta osoba wybiera w swoim programie "
                             "„＋ Klient → Dodaj profil z pliku” i wskazuje ten sam plik, bez hasła.",
                  style="Small.TLabel", wraplength=app.px(470), justify="left").pack(anchor="w", pady=(4, 0))
        self.err = ttk.Label(card, style="Error.TLabel", wraplength=app.px(470))
        self.err.pack(anchor="w")

        box, card = app.card(b, 12)
        box.pack(fill="x", pady=(10, 0))
        ttk.Label(card, text="DOSTĘP HASŁEM PROFILU", style="Field.TLabel").pack(anchor="w")
        if app.s.password_access(pid):
            pw = app.s.profile_password(pid)
            ttk.Label(card, text="Włączony: każdy, kto zna hasło, może otworzyć profil i zostaje dopisany do osób.",
                      style="Warn.TLabel", wraplength=app.px(470), justify="left").pack(anchor="w", pady=(4, 6))
            if pw:
                row = ttk.Frame(card)
                row.pack(fill="x")
                ent = readonly(row, pw, app, secret=True)
                ent.pack(side="left", fill="x", expand=True)
                show = ttk.Button(row, text="Pokaż")

                def toggle():
                    shown = ent.cget("show") == ""
                    ent.configure(show="•" if shown else "")
                    show.configure(text="Pokaż" if shown else "Ukryj")
                show.configure(command=toggle)
                show.pack(side="left", padx=(6, 0))
                ttk.Button(row, text="Kopiuj", command=lambda: app.copy(pw, "hasło profilu", secret=True)).pack(side="left", padx=(6, 0))
            row = ttk.Frame(card)
            row.pack(anchor="w", pady=(8, 0))
            ttk.Button(row, text="Wyłącz dostęp hasłem", command=self.disable_pw).pack(side="left")
            ttk.Button(row, text="Zmień hasło…", command=lambda: (self.close(), app.change_profile_password(pid))).pack(side="left", padx=(6, 0))
        else:
            ttk.Label(card, text="Wyłączony (zalecane): profil otwierają tylko osoby z listy.", style="Muted.TLabel").pack(anchor="w", pady=(4, 6))
            ttk.Button(card, text="Włącz z nowym hasłem…", command=lambda: (self.close(), app.change_profile_password(pid))).pack(anchor="w")

        box, card = app.card(b, 12)
        box.pack(fill="x", pady=(10, 0))
        ttk.Label(card, text="PLIK PROFILU", style="Field.TLabel").pack(anchor="w")
        readonly(card, p.path, app).pack(fill="x", pady=(4, 6))
        row = ttk.Frame(card)
        row.pack(anchor="w")
        ttk.Button(row, text="Pokaż w folderze", command=lambda: app.reveal(p.path)).pack(side="left")
        ttk.Button(row, text="Zapisz kopię pliku…", command=self.copy_file).pack(side="left", padx=(6, 0))
        ttk.Label(card, text="Najlepiej trzymać plik we wspólnym folderze (Dysk Google, OneDrive, serwer plików), "
                             "wtedy wszyscy widzą swoje zmiany.", style="Small.TLabel",
                  wraplength=app.px(470), justify="left").pack(anchor="w", pady=(6, 0))
        self.buttons(("Zamknij", self.close, None, "right"))

    def add(self):
        def done(m):
            self.app.flash(f"Dodano: {m['name']}.")
            if self.winfo_exists():
                self.render()

        def fail(e):
            if self.winfo_exists():
                self.err.configure(text=str(e))

        code = self.code.get()
        self.app.run_bg(lambda: self.app.s.add_member(self.pid, code), done, fail)

    def remove(self, m):
        name = m.get("name") or "ta osoba"
        if not messagebox.askyesno(
                "Odbierz dostęp",
                f"Odebrać dostęp: {name}?\n\nProfil dostanie nowy klucz, a dostęp hasłem zostanie wyłączony, bo ta "
                f"osoba mogła je znać. {name} nie otworzy już aktualnej wersji profilu.\n\nKopie pliku, które ta osoba "
                f"zrobiła wcześniej, nadal otworzy. Zmień hasła do urządzeń, które mogła poznać.",
                icon="warning", parent=self):
            return
        self.app.flush_save(self.pid)

        def done(_):
            self.app.after_profile_change(self.pid, f"Odebrano dostęp: {name}.")
            if self.winfo_exists():
                self.render()

        def fail(e):
            if self.winfo_exists():
                self.err.configure(text=str(e))

        self.app.run_bg(lambda: self.app.s.remove_member(self.pid, m["id"]), done, fail)

    def disable_pw(self):
        if not messagebox.askyesno("Dostęp hasłem", "Wyłączyć dostęp hasłem? Profil dostanie nowy klucz. Osoby z listy "
                                   "zachowają dostęp, a hasło profilu przestanie działać.", parent=self):
            return
        self.app.flush_save(self.pid)

        def done(_):
            self.app.after_profile_change(self.pid, "Wyłączono dostęp hasłem.")
            if self.winfo_exists():
                self.render()

        self.app.run_bg(lambda: self.app.s.set_password_access(self.pid, None), done,
                        lambda e: self.err.configure(text=str(e)) if self.winfo_exists() else None)

    def copy_file(self):
        p = self.app.s.profiles[self.pid]
        dst = filedialog.asksaveasfilename(parent=self, title="Zapisz kopię profilu", filetypes=PROFILE_TYPES,
                                           initialfile=os.path.basename(p.path), defaultextension=PROFILE_EXT)
        if not dst:
            return
        if os.path.abspath(dst) == os.path.abspath(p.path):
            messagebox.showerror("Kopia profilu", "Wybierz inne miejsce niż oryginalny plik.", parent=self)
            return
        try:
            self.app.flush_save(self.pid)
            from .storage import write_atomic
            write_atomic(dst, p.file.sealed())
            self.app.flash("Zapisano kopię profilu.")
        except OSError as e:
            messagebox.showerror("Kopia profilu", f"Nie udało się zapisać: {e}", parent=self)


class ChangeProfilePasswordDialog(Dialog):
    """Nowe hasło profilu (włącza dostęp hasłem albo zmienia hasło)."""

    def __init__(self, app, pid):
        super().__init__(app, "Hasło profilu")
        self.pid = pid
        p = app.s.profiles[pid]
        b = self.body
        on = app.s.password_access(pid)
        ttk.Label(b, text=f"{'Nowe hasło' if on else 'Dostęp hasłem'} dla „{p.name}”", style="Title.TLabel").pack(anchor="w")
        ttk.Label(b, text="Profil dostanie nowy klucz. Osoby z listy zachowają dostęp. Kto znał tylko stare hasło, "
                          "straci dostęp do aktualnej wersji.\n\nKażdy, kto pozna nowe hasło, otworzy profil i zostanie "
                          "dopisany do osób. Bezpieczniej dodawać osoby ich kodami.",
                  wraplength=app.px(440), justify="left").pack(anchor="w", pady=(8, 0))
        ttk.Label(b, text="NOWE HASŁO PROFILU", style="Field.TLabel").pack(anchor="w", pady=(14, 4))
        row = ttk.Frame(b)
        row.pack(fill="x")
        self.pw = tk.StringVar(value=profile_password())
        ttk.Entry(row, textvariable=self.pw, font=app.mono).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Losuj", command=lambda: self.pw.set(profile_password())).pack(side="left", padx=(6, 0))
        self.err = ttk.Label(b, style="Error.TLabel")
        self.err.pack(anchor="w", pady=(6, 0))
        self.btn, _ = self.buttons(("Zapisz hasło", self.go, "Accent.TButton", "left"), ("Anuluj", self.close, None, "right"))

    def go(self):
        pw = self.pw.get()
        problem = Session.check_profile_password(pw)
        if problem:
            self.err.configure(text=problem)
            return
        self.btn.configure(text="Zapisuję…", state="disabled")
        self.app.flush_save(self.pid)

        def done(_):
            self.close()
            self.app.after_profile_change(self.pid, "Zapisano nowe hasło profilu.")

        def fail(e):
            if self.winfo_exists():
                self.err.configure(text=f"Nie udało się zmienić hasła: {e}")
                self.btn.configure(text="Zapisz hasło", state="normal")

        self.app.run_bg(lambda: self.app.s.set_password_access(self.pid, pw), done, fail)


class LogDialog(Dialog):
    """Dziennik zmian profilu: kto i kiedy dodał, zmienił, usunął albo skopiował hasło."""

    def __init__(self, app, pid):
        super().__init__(app, "Dziennik zmian", resizable=True)
        p = app.s.profiles[pid]
        b = self.body
        ttk.Label(b, text=f"Dziennik zmian: {p.name}", style="Title.TLabel").pack(anchor="w")
        ttk.Label(b, text="Zapisy robi program każdej osoby z dostępem. Dziennik pokazuje uczciwe korzystanie z profilu; "
                          "nie chroni przed kimś, kto celowo obchodzi program.", style="Small.TLabel",
                  wraplength=app.px(640), justify="left").pack(anchor="w", pady=(4, 8))
        fr = ttk.Frame(b)
        fr.pack(fill="x")
        self.q = tk.StringVar()
        ttk.Entry(fr, textvariable=self.q, width=40).pack(side="left")
        ttk.Label(fr, text="filtr: osoba, czynność albo wpis", style="Small.TLabel").pack(side="left", padx=(8, 0))
        box = ttk.Frame(b)
        box.pack(fill="both", expand=True, pady=(8, 0))
        self.tree = ttk.Treeview(box, columns=("at", "who", "what", "item"), show="headings", height=16)
        for col, text, w in (("at", "Kiedy", 150), ("who", "Kto", 150), ("what", "Co", 220), ("item", "Wpis / szczegóły", 220)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=app.px(w), anchor="w")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.log = list(reversed(p.data.get("log") or []))
        self.q.trace_add("write", lambda *a: self.fill())
        self.fill()
        self.buttons(("Zamknij", self.close, None, "right"))

    def fill(self):
        q = vault.norm(self.q.get())
        self.tree.delete(*self.tree.get_children())
        for x in self.log:
            row = (vault.fmt_date(x.get("at", "")), x.get("who", ""), x.get("action", ""),
                   x.get("title") or x.get("detail", ""))
            if q and q not in vault.norm(" ".join(row)):
                continue
            self.tree.insert("", "end", values=row)


class MyCodeDialog(Dialog):
    """Twój kod do udostępniania profili i nazwa widoczna dla współpracowników."""

    def __init__(self, app):
        super().__init__(app, "Mój kod")
        b = self.body
        ident = app.s.identity
        ttk.Label(b, text="Mój kod dla współpracowników", style="Title.TLabel").pack(anchor="w")
        ttk.Label(b, text="Wyślij ten kod osobie, która ma dostęp do profilu klienta. Doda Cię w oknie „Udostępnij” i "
                          "nie będziecie musieli przekazywać sobie hasła. Kod nie jest tajny: zawiera tylko Twój klucz publiczny.",
                  wraplength=app.px(460), justify="left").pack(anchor="w", pady=(6, 10))
        ttk.Label(b, text="TWOJA NAZWA WIDOCZNA DLA INNYCH", style="Field.TLabel").pack(anchor="w", pady=(0, 4))
        self.name = tk.StringVar(value=ident.get("name", ""))
        row = ttk.Frame(b)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.name).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Zapisz nazwę", command=self.save_name).pack(side="left", padx=(6, 0))
        ttk.Label(b, text="KOD", style="Field.TLabel").pack(anchor="w", pady=(12, 4))
        self.code_entry = readonly(b, app.s.my_code(), app)
        self.code_entry.pack(fill="x")
        ttk.Label(b, text=f"Odcisk klucza do sprawdzenia przez telefon: {crypto.fingerprint(ident['kid'])}",
                  style="Small.TLabel").pack(anchor="w", pady=(6, 0))
        self.buttons(("Kopiuj kod", lambda: app.copy(app.s.my_code(), "Twój kod"), "Accent.TButton", "left"),
                     ("Zamknij", self.close, None, "right"))

    def save_name(self):
        self.app.s.set_my_name(self.name.get())
        self.app.changed(ME)
        for pid, p in self.app.s.profiles.items():
            if p.file and p.file.dirty:
                self.app.schedule_save(pid)
        self.code_entry.configure(state="normal")
        self.code_entry.delete(0, "end")
        self.code_entry.insert(0, self.app.s.my_code())
        self.code_entry.configure(state="readonly")
        self.app.flash("Zapisano nazwę.")
