"""Okienkowy interfejs programu Sejf (tkinter + motyw Sun Valley w stylu Windows 11)."""
from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from datetime import date
from tkinter import filedialog, font as tkfont, messagebox, ttk

from . import connect, crypto, csvio, storage, vault
from .clipboard import Clipboard
from .dialogs import (AskStringDialog, ChangeProfilePasswordDialog, ExportDialog, GeneratorDialog, HistoryDialog, LogDialog,
                      MyCodeDialog,
                      ImportDialog, ImportPreview, NewProfileDialog, ProfileInfoDialog, ProfilePasswordDialog,
                      SettingsDialog, ShareDialog)
from .icon import ICON_PNG_B64
from .session import ME, PasswordChanged, Session
from .views import LockScreen, MainView
from .widgets import COLORS, CSV_TYPES, PROFILE_TYPES, VAULT_TYPES, Dialog, open_folder

try:
    import sv_ttk
except ImportError:  # program działa też bez motywu, tylko wygląda skromniej
    sv_ttk = None
try:
    import darkdetect
except ImportError:
    darkdetect = None

CHECK_EVERY = 3.0  # co ile sekund sprawdzać zmiany zrobione przez inne osoby


class App:
    def __init__(self, root: tk.Tk, open_path: str | None = None):
        self.root = root
        self.cfg = storage.load_config()
        self.s = Session(self.cfg)
        self.clip = Clipboard(root)
        self.dialogs: list[Dialog] = []
        self.view = None
        self.main: MainView | None = None
        self.save_jobs: dict[str, str] = {}
        self.flash_job = None
        self.clip_job = None
        self.clip_text = None
        self.saved_at = None
        self.errors: dict[str, str] = {}
        self.generation = 0
        self.last_act = time.monotonic()
        self.last_check = 0.0

        root.title("Sejf")
        root.minsize(980, 600)
        root.geometry(self.cfg.get("geometry") or "1320x800")
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

    # --- wygląd ------------------------------------------------------------------------
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
        if mode in ("dark", "light"):
            return mode == "dark"
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
        self.root.configure(background=self.bg())

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
        self.save_config()
        self.apply_theme(mode)
        if self.s.unlocked and self.main:
            scope, sel = self.main.scope_iid, self.main.selected()
            self.enter_main(keep=True)
            self.main.select_scope(scope)
            if sel:
                self.main.select(sel[0], sel[1]["id"])
        else:
            self.show_lock("unlock" if self.last_path else "home")

    def after_dialog(self, fn):
        for d in list(self.dialogs):
            d.close()
        self.root.after(10, fn)

    def save_config(self):
        storage.save_config(self.cfg)

    # --- widoki --------------------------------------------------------------------------
    def _swap(self, view):
        if self.view is not None:
            self.view.destroy()
        self.view = view
        view.pack(fill="both", expand=True)

    def show_lock(self, mode: str, message: str = ""):
        self.main = None
        self._swap(LockScreen(self, mode, message))
        self.root.title("Sejf")

    def after_unlock(self):
        """Po haśle głównym: kod z aplikacji, jeśli przyszedł czas, a potem główne okno."""
        self.last_path = self.s.path
        self.cfg["last_path"] = self.s.path
        self.save_config()
        if self.s.totp_due():
            self.show_lock("totp")
        else:
            self.enter_main()
        if self.s.upgraded and self.main:
            self.flash("Sejf przeniesiono na silniejsze zabezpieczenie hasła (Argon2id).", 8000)

    def enter_main(self, keep: bool = False):
        if not keep:
            self.saved_at = None
            self.errors = {}
            self.last_act = time.monotonic()
        self.main = MainView(self)
        self._swap(self.main)
        self.root.title(f"Sejf — {self.s.file_name}")
        self.refresh_status()
        if not keep:
            self.load_profiles()

    def load_profiles(self, only=None):
        """Otwiera profile klientów w tle (wyprowadzanie kluczy trwa chwilę)."""
        gen = self.generation
        s = self.s

        def done(_):
            if gen != self.generation or not s.unlocked:
                return
            if s.main.dirty:
                self.schedule_save(ME)
            if self.main:
                editing = self.main.detail.editing is not None
                self.main.refresh_nav()
                if not editing:
                    self.main.refresh_list(keep_detail=True)
            self.refresh_status()

        self.run_bg(lambda: s.open_profiles(only), done, lambda e: done(None))

    def create_vault(self, path, pw, lock_screen=None):
        if lock_screen:
            lock_screen.btn.configure(text="Tworzę sejf…", state="disabled")

        def done(_):
            self.saved_at = time.localtime()
            self.last_path = path
            self.cfg["last_path"] = path
            self.save_config()
            self.enter_main()

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

    # --- zapis ---------------------------------------------------------------------------
    def changed(self, sid: str = ME):
        f = self.s.source(sid)
        if not f:
            return
        f.touch()
        self.schedule_save(sid)

    def schedule_save(self, sid: str):
        job = self.save_jobs.pop(sid, None)
        if job:
            self.root.after_cancel(job)
        self.save_jobs[sid] = self.root.after(300, lambda: self.do_save(sid))
        self.refresh_status()

    def flush_save(self, sid: str | None = None):
        for key in [sid] if sid else list(self.save_jobs):
            job = self.save_jobs.pop(key, None)
            if job:
                self.root.after_cancel(job)
                self.do_save(key)

    def do_save(self, sid: str):
        self.save_jobs.pop(sid, None)
        f = self.s.source(sid) if self.s.unlocked else None
        if not f:
            return
        try:
            result = f.save()
            self.errors.pop(sid, None)
        except PasswordChanged:
            self.on_password_changed(sid)
            return
        except OSError as e:
            self.errors[sid] = f"Nie udało się zapisać pliku {f.file_name}: {e.strerror or e}"
            result = "error"
        if result in ("saved", "merged"):
            self.saved_at = time.localtime()
        if result == "merged" and self.main:
            self.main.refresh(keep_detail=self.main.detail.editing is None)
            self.flash("Połączono z zmianami zapisanymi w międzyczasie na innym komputerze.")
        self.refresh_status()

    def on_password_changed(self, sid: str):
        if sid == ME:
            self.lock(message="Hasło główne zmieniono na innym komputerze. Odblokuj sejf nowym hasłem.", save=False)
            return
        p = self.s.profiles.get(sid)
        if p:
            p.file, p.error = None, "password"
            p.message = ("Hasło do tego profilu zmieniono na innym komputerze. Twoje ostatnie zmiany w nim nie "
                         "zostały zapisane. Wpisz nowe hasło.")
        if self.main:
            self.main.refresh()

    def refresh_status(self):
        if not self.main:
            return
        if self.errors:
            text = next(iter(self.errors.values()))
        elif self.save_jobs or any(self.s.source(sid) and self.s.source(sid).dirty for sid in self.s.open_sources()):
            text = "Zapisywanie…"
        else:
            parts = [self.s.file_name]
            n = len(self.s.profiles)
            if n:
                opened = sum(1 for p in self.s.profiles.values() if p.file)
                parts.append(f"klienci: {opened} z {n}" if opened != n else f"klienci: {n}")
            if self.saved_at:
                parts.append(f"zapisano automatycznie o {time.strftime('%H:%M', self.saved_at)}")
            text = "  ·  ".join(parts)
        self.main.status.configure(text=text, style="Error.TLabel" if self.errors else "Muted.TLabel")

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

    # --- schowek i połączenia ----------------------------------------------------------------
    def copy(self, text: str, what: str, secret: bool = False, log=None):
        """Kopiuje do schowka. ``log=(sid, wpis)``: zapis w dzienniku profilu klienta."""
        try:
            self.clip.set(text, private=secret)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Schowek", f"Nie udało się skopiować: {e}", parent=self.root)
            return
        if log and log[0] != ME and secret:
            self.log(log[0], f"skopiował {what}", log[1])
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

    def log(self, sid, action, entry=None, detail=""):
        if sid != ME and self.s.unlocked and self.s.source(sid):
            self.s.log(sid, action, entry, detail)
            self.schedule_save(sid)

    def connect(self, e, action, sid=None):
        secret = e.get("password") if action.copy_key == "password" else (e.get("extra") or {}).get(action.copy_key)
        if sid:
            self.log(sid, f"połączył się: {action.label}", e)
        try:
            if action.copy_password and secret:
                self.copy(secret, "hasło", secret=True)
            connect.run(action)
            if action.copy_password and secret:
                self.flash("Hasło jest w schowku. Wklej je w oknie logowania (Ctrl+V).", 6000)
        except (OSError, FileNotFoundError) as err:
            messagebox.showerror(action.label, f"Nie udało się uruchomić: {err}", parent=self.root)

    def reveal(self, path):
        if os.path.exists(path):
            open_folder(path)
        else:
            messagebox.showerror("Plik", "Nie ma pliku w tym miejscu.", parent=self.root)

    # --- blokada i sprawdzanie zmian ------------------------------------------------------------
    def _activity(self, _e=None):
        self.last_act = time.monotonic()

    def system_locked(self) -> bool:
        """Czy ekran Windows jest zablokowany (Win+L)? Pulpit wejściowy jest wtedy niedostępny."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            h = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
            if not h:
                return True
            user32.CloseDesktop(h)
        except Exception:  # noqa: BLE001
            return False
        return False

    def tick(self):
        now = time.time()
        gap = now - getattr(self, "last_tick", now)
        self.last_tick = now
        try:
            if self.s.unlocked and self.main:
                minutes = int(self.s.data["settings"].get("autoLockMin", 0))
                on_system = self.s.data["settings"].get("lockOnSystem", True)
                if on_system and gap > 30:  # komputer spał albo był wstrzymany
                    self.lock(message="Sejf został zablokowany, bo komputer był uśpiony.")
                elif on_system and self.system_locked():
                    self.lock(message="Sejf został zablokowany razem z ekranem Windows.")
                elif minutes and time.monotonic() - self.last_act > minutes * 60:
                    self.lock(message="Sejf został zablokowany po okresie bezczynności.")
                elif time.monotonic() - self.last_check > CHECK_EVERY and not self.save_jobs:
                    self.last_check = time.monotonic()
                    self.check_external()
        finally:
            self.root.after(1000, self.tick)

    def check_external(self):
        s = self.s
        changed = False
        r = s.main.check_external()
        if r == "password":
            self.on_password_changed(ME)
            return
        if r in ("reloaded", "merged"):
            changed = True
            new = [pid for pid, p in s.profiles.items() if p.error == "loading"]
            if new:
                self.load_profiles(new)
        if r == "missing":
            self.errors[ME] = "Nie ma pliku sejfu w tym miejscu. Zostanie utworzony przy następnym zapisie."
        for pid, res in s.check_profiles().items():
            if res in ("reloaded", "merged", "password", "missing"):
                changed = True
        if s.main.dirty:
            self.schedule_save(ME)
        if changed and self.main:
            editing = self.main.detail.editing is not None
            self.main.refresh(keep_detail=not editing)
            self.flash("Wczytano zmiany z innego komputera.")
        self.refresh_status()

    def lock(self, message: str = "", save: bool = True):
        if save and self.s.unlocked:
            self.flush_save()
        for job in self.save_jobs.values():
            self.root.after_cancel(job)
        self.save_jobs = {}
        if self.clip_job:
            self.root.after_cancel(self.clip_job)
            self.clear_clip()
        for d in list(self.dialogs):
            d.close()
        self.root.unbind("<Control-s>")
        self.root.unbind("<Escape>")
        self.generation += 1
        self.s.lock()
        self.errors = {}
        self.save_config()
        self.show_lock("unlock" if self.last_path else "home", message)

    def quit(self):
        try:
            if self.s.unlocked:
                self.flush_save()
            if self.clip_text is not None:
                self.clip.clear_if(self.clip_text)
            if self.root.state() == "normal":
                self.cfg["geometry"] = self.root.geometry()
            self.save_config()
        finally:
            self.root.destroy()

    # --- profile klientów ----------------------------------------------------------------------
    def new_profile(self):
        return NewProfileDialog(self).show()

    def add_profile(self):
        path = filedialog.askopenfilename(parent=self.root, title="Wybierz plik profilu klienta",
                                          filetypes=PROFILE_TYPES, initialdir=os.path.dirname(self.s.path or "") or None)
        if not path:
            return None
        return self.add_profile_path(path)

    def add_profile_path(self, path):
        try:
            text, _ = storage.read_text(path)
            env = crypto.parse_envelope(text, "profile")
        except (OSError, crypto.VaultError) as e:
            messagebox.showerror("Profil klienta", str(e), parent=self.root)
            return None
        known = next((p for p in self.s.profiles.values() if os.path.abspath(p.path) == os.path.abspath(path)), None)
        if known and known.file:
            messagebox.showinfo("Profil klienta", f"Profil „{known.name}” jest już w programie.", parent=self.root)
            self.profile_ready(known.id)
            return None
        del env
        box = {}

        def fail(e):
            if isinstance(e, (crypto.NoAccess, PasswordChanged)):
                box["dlg"] = ProfilePasswordDialog(self, path).show()
            else:
                messagebox.showerror("Profil klienta", str(e), parent=self.root)

        self.run_bg(lambda: self.s.add_profile(path), lambda p: self.profile_ready(p.id, f"Dodano profil „{p.name}”."), fail)
        return box

    def after_profile_change(self, pid, message=""):
        self.schedule_save(ME)
        if self.main:
            self.main.refresh(keep_detail=self.main.detail.editing is None)
        if message:
            self.flash(message, 6000)

    def retry_profile(self, pid):
        p = self.s.profiles.get(pid)
        if p:
            p.error, p.message = "loading", ""
            if self.main:
                self.main.refresh()
            self.load_profiles([pid])

    def open_log(self, pid):
        self.flush_save(pid)
        return LogDialog(self, pid).show()

    def open_my_code(self):
        return MyCodeDialog(self).show()

    def profile_ready(self, pid, message=""):
        if self.main:
            self.main.scope_iid = f"c|{pid}"
            self.main.refresh()
            self.main.nav.item("clients", open=True)
        self.schedule_save(ME)
        if message:
            self.flash(message)

    def edit_profile_info(self, pid):
        return ProfileInfoDialog(self, pid).show()

    def share_profile(self, pid):
        self.flush_save(pid)
        return ShareDialog(self, pid).show()

    def change_profile_password(self, pid):
        return ChangeProfilePasswordDialog(self, pid).show()

    def relink_password(self, pid):
        return ProfilePasswordDialog(self, self.s.profiles[pid].path, pid).show()

    def relink_file(self, pid):
        p = self.s.profiles[pid]
        path = filedialog.askopenfilename(parent=self.root, title=f"Gdzie jest teraz plik profilu „{p.name}”?",
                                          filetypes=PROFILE_TYPES)
        if not path:
            return

        def fail(e):
            if isinstance(e, (PasswordChanged, crypto.WrongPassword)):
                p.path = path
                self.relink_password(pid)
            else:
                messagebox.showerror("Profil klienta", str(e), parent=self.root)

        self.run_bg(lambda: self.s.relink_profile(pid, path=path), lambda _: (self.save_config(),
                    self.profile_ready(pid, "Znaleziono profil.")), fail)

    def forget_profile(self, pid):
        p = self.s.profiles[pid]
        if not messagebox.askyesno("Usuń profil z programu",
                                   f"Usunąć „{p.name}” z programu?\n\nPlik profilu zostanie na dysku i nadal będą go "
                                   f"używać inne osoby. Żeby wrócić do profilu, dodasz go ponownie z pliku, "
                                   f"wpisując hasło profilu.", icon="warning", parent=self.root):
            return
        self.flush_save(pid)
        self.s.forget_profile(pid)
        self.save_config()
        if self.main:
            self.main.scope_iid = "clients"
            self.main.refresh()
        self.flash(f"Usunięto „{p.name}” z programu.")

    # --- okna dialogowe ---------------------------------------------------------------------------
    def ask_string(self, title, label):
        d = AskStringDialog(self, title, label).show()
        self.root.wait_window(d)
        return d.result

    def open_generator(self, use_cb=None):
        if not self.s.unlocked:
            return None
        return GeneratorDialog(self, use_cb).show()

    def open_settings(self):
        return SettingsDialog(self).show()

    def open_history(self, e):
        return HistoryDialog(self, e).show()

    def open_export(self):
        self.flush_save()
        return ExportDialog(self).show()

    def open_import(self):
        path = filedialog.askopenfilename(parent=self.root, title="Wybierz plik CSV z hasłami", filetypes=CSV_TYPES)
        if not path:
            return None
        return self.import_path(path)

    def import_path(self, path):
        try:
            preview = self.load_import(path)
        except (OSError, ValueError) as e:
            messagebox.showerror("Import", str(e), parent=self.root)
            return None
        target = self.main.default_target() if self.main else ME
        return ImportDialog(self, preview, target).show()

    def load_import(self, path) -> ImportPreview:
        with open(path, "rb") as f:
            res = csvio.parse(csvio.decode(f.read()))
        return ImportPreview(path, res.fmt, len(res.entries), res.entries)

    def apply_import(self, entries, category: str, sid: str = ME) -> int:
        data = self.s.source(sid).data
        for e in entries:
            cat = e["category"] or (category if sid == ME else "")
            data["entries"].append(vault.normalize_entry(vault.new_entry(**{**e, "category": cat})))
            if cat and cat not in data.setdefault("categories", []):
                data["categories"].append(cat)
        self.changed(sid)
        self.log(sid, f"zaimportował {vault.wpisy(len(entries))}")
        if self.main:
            self.main.scope_iid = ME if sid == ME else f"c|{sid}"
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

    def export_csv(self, sid=ME):
        if not messagebox.askyesno("Eksport bez szyfrowania",
                                   "Plik CSV nie jest zaszyfrowany. Każdy, kto go otworzy, zobaczy wszystkie hasła.\n\n"
                                   "Zapisać go mimo to? Usuń go zaraz po użyciu.", icon="warning", parent=self.root):
            return
        name = "hasla" if sid == ME else vault.norm(self.s.source_name(sid)).replace(" ", "-")[:40]
        path = filedialog.asksaveasfilename(parent=self.root, title="Zapisz CSV",
                                            initialfile=f"{name}-{date.today().isoformat()}.csv",
                                            defaultextension=".csv", filetypes=CSV_TYPES)
        if path:
            try:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(csvio.to_csv(self.s.source(sid).data["entries"]))
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
