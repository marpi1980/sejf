"""Test okienkowego interfejsu na prawdziwym Tk (uruchamiany na Windows w GitHub Actions).

Ścieżka: nowy sejf → własny wpis → profil klienta → serwer, komputer, switch i VPN → import listy
urządzeń → dodanie współpracowniczki jej kodem → wspólna praca → weryfikacja dwuetapowa → odebranie
i przywrócenie dostępu → dostęp hasłem → dziennik → blokada razem z Windows. Po drodze zapisuje zrzuty ekranu
do katalogu test-results/.
"""
import os
import shutil
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import messagebox

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures"
OUT = ROOT / "test-results"
PW = "Zielony kot je 4 jabłka!"


def shot(widget, name):
    """Zrzut ekranu okna (tylko Windows; gdzie indziej pomijany)."""
    if sys.platform != "win32":
        return
    try:
        from PIL import ImageGrab
    except ImportError:
        return
    widget.update()
    time.sleep(0.4)
    widget.update()
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    w, h = widget.winfo_width(), widget.winfo_height()
    OUT.mkdir(exist_ok=True)
    try:
        ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(OUT / f"{name}.png")
    except Exception as e:  # noqa: BLE001
        print("zrzut nieudany:", name, e)


class GuiFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.shared = os.path.join(self.tmp, "Dysk zespołu")
        os.mkdir(self.shared)
        os.environ["SEJF_CONFIG_DIR"] = os.path.join(self.tmp, "cfg")
        self.path = os.path.join(self.tmp, "hasla.sejf.json")
        messagebox.askyesno = lambda *a, **k: True
        messagebox.showinfo = lambda *a, **k: "ok"
        messagebox.showwarning = lambda *a, **k: "ok"
        self.errors = []
        messagebox.showerror = lambda *a, **k: self.errors.append(a)
        from sejf.gui import App
        self.root = tk.Tk()
        self.root.geometry("1010x720+0+0")
        self.root.attributes("-topmost", True)
        self.app = App(self.root)
        self.pump()

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pump(self, t=0.15):
        end = time.time() + t
        while time.time() < end:
            self.root.update()
            time.sleep(0.01)

    def wait(self, cond, timeout=20, msg="warunek"):
        end = time.time() + timeout
        while time.time() < end:
            self.root.update()
            if cond():
                return
            time.sleep(0.02)
        self.fail(f"Przekroczono czas oczekiwania: {msg}")

    def saved(self):
        self.wait(lambda: not self.app.save_jobs and not any(
            self.app.s.source(s).dirty for s in self.app.s.open_sources()), msg="zapis")

    def form_fill(self, **values):
        d = self.app.main.detail
        for k, v in values.items():
            if k == "type_label":
                d.vars["type_label"].set(v)
                d._retype()
            elif k == "notes":
                d.notes.delete("1.0", "end")
                d.notes.insert("1.0", v)
            else:
                d.vars[k].set(v)

    def bump(self, path):
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 3_000_000_000))

    def test_full_flow(self):
        from sejf import totp, vault
        from sejf.dialogs import (ChangeProfilePasswordDialog, LogDialog, MyCodeDialog, NewProfileDialog,
                                  ShareDialog, TotpSetupDialog)
        from sejf.kinds import BY_KEY
        from sejf.session import ME, Session
        app = self.app
        shot(self.root, "01-start")

        # --- nowy sejf -------------------------------------------------------------
        lock = app.view
        lock.show_create()
        lock.n1.set(PW)
        lock.n2.set(PW)
        app.create_vault(self.path, PW, lock)
        self.wait(lambda: app.main is not None, msg="utworzenie sejfu")
        self.pump(0.3)
        shot(self.root, "02-pusty-sejf")

        # --- własny wpis ------------------------------------------------------------
        main = app.main
        main.new_entry()
        self.form_fill(title="Allegro", username="jan.kowalski", password="Kot123!!", url="allegro.pl")
        main.detail.save()
        self.pump()
        self.assertEqual(len(app.s.data["entries"]), 1)

        # --- nowy profil klienta ----------------------------------------------------
        dlg = NewProfileDialog(app).show()
        dlg.vars["name"].set("ACME")
        dlg.vars["company"].set("ACME Polska sp. z o.o.")
        dlg.vars["address"].set("ul. Przemysłowa 12, 30-001 Kraków")
        dlg.vars["phone"].set("+48 12 345 67 89")
        dlg.vars["contact"].set("Anna Nowak (kierownik biura)")
        prof_path = os.path.join(self.shared, "ACME.sejfklient")
        dlg.custom_path = True
        dlg.path.set(prof_path)
        self.assertFalse(dlg.use_pw.get())  # domyślnie bez dostępu hasłem
        self.pump()
        shot(dlg, "03-nowy-klient")
        dlg.create()
        self.wait(lambda: os.path.exists(prof_path) and app.s.profiles, msg="utworzenie profilu")
        self.pump(0.3)
        pid = next(iter(app.s.profiles))
        self.assertEqual(main.scope().profile, pid)

        # serwer przez formularz z typem
        main.new_entry()
        self.form_fill(type_label=BY_KEY["server"].label)
        self.form_fill(title="DC01 – kontroler domeny", username="ACME\\administrator", password="Srv!2026-x9",
                       host="10.10.0.10", os="Windows Server", domain="acme.local", role="AD, DNS, DHCP",
                       location="Serwerownia, szafa RACK 1")
        self.assertEqual(main.detail.vars["protocol"].get(), "RDP")
        self.form_fill(idrac="10.10.0.110", idrac_user="root", idrac_password="iDr@c-2026")
        # dwa dodatkowe konta, jedno puste zostanie pominięte
        for label, user, pw in (("Konto kopii zapasowych", "ACME\\svc_backup", "B@ckup-2026"),
                                ("Lokalny administrator", ".\\Administrator", "L0cal!Adm"), ("", "", "")):
            main.detail._add_account()
            row = main.detail.acc_vars[-1]
            row["label"].set(label); row["username"].set(user); row["password"].set(pw)
        main.detail._remove_account(2)
        main.detail._add_account()
        for _ in range(30):  # szybkie przebudowy formularza nie mogą niczego usunąć ani wyczyścić
            main.detail._collect()
            main.detail._render_form()
        self.pump(0.5)
        self.assertEqual([a.get("username") for a in main.detail.editing["accounts"]],
                         ["ACME\\svc_backup", ".\\Administrator", ""])
        shot(self.root, "04-formularz-serwer")
        main.detail.save()
        srv = next(e for e in app.s.profiles[next(iter(app.s.profiles))].data["entries"] if e["type"] == "server")
        self.assertEqual([a["username"] for a in srv["accounts"]], ["ACME\\svc_backup", ".\\Administrator"])
        self.assertEqual(srv["extra"]["idrac_password"], "iDr@c-2026")
        self.pump()
        main.new_entry()
        self.form_fill(type_label=BY_KEY["switch"].label)
        self.form_fill(title="SW-CORE", username="admin", password="Sw!tch-2026", host="10.10.0.2",
                       enable="En4ble!", snmp="acme-ro", model="HPE Aruba 2930F", vlans="10 biuro, 20 VoIP, 99 mgmt",
                       location="Szafa RACK 1, U40")
        main.detail.save()
        # komputer użytkownika: ukrycie zbędnego pola, przywrócenie, własne pole jako szablon
        main.new_entry()
        self.form_fill(type_label=BY_KEY["computer"].label)
        det = main.detail
        self.form_fill(title="Anna Nowak – laptop", person="Anna Nowak", department="Księgowość",
                       hostname="KSIEGOWOSC-01", host="10.10.0.31", username="anowak", password="Win!2026-an",
                       email="anna.nowak@acme.pl", email_password="Mail!2026", drive="Z: = \\\\srv01\\ksiegowosc",
                       drive_user="ACME\\anowak", drive_password="Dysk!2026", remote_tool="AnyDesk",
                       remote_id="123 456 789", remote_password="Any!2026", os="Windows 11 Pro", warranty="2027-03-31")
        pin = BY_KEY["computer"].fields[[f.key for f in BY_KEY["computer"].fields].index("pin")]
        det._hide_field(pin)
        self.assertNotIn("pin", det.vars)
        self.assertIn("pin", vault.hidden_fields(app.s.data["settings"], "computer"))
        det.add_custom("Numer inwentarzowy", False, template=True)
        det.custom_vars[-1].set("INW/2026/014")
        self.assertEqual(det.vars["person"].get(), "Anna Nowak")  # wartości przetrwały przebudowę formularza
        self.pump()
        shot(self.root, "04c-formularz-komputer")
        det.save()
        self.pump()
        pc = next(e for e in app.s.profiles[next(iter(app.s.profiles))].data["entries"] if e["type"] == "computer")
        self.assertEqual(pc["extra"]["hostname"], "KSIEGOWOSC-01")
        self.assertEqual(pc["custom"][0]["value"], "INW/2026/014")
        self.pump(0.3)
        shot(self.root, "07c-komputer")
        # następny komputer dostaje pole z szablonu, a ukryte pole można przywrócić
        main.new_entry()
        self.form_fill(type_label=BY_KEY["computer"].label)
        self.assertEqual([c["label"] for c in main.detail.editing["custom"]], ["Numer inwentarzowy"])
        main.detail.show_field("pin")
        self.assertIn("pin", main.detail.vars)
        main.detail.cancel()
        self.pump()

        main.new_entry()
        self.form_fill(type_label=BY_KEY["vpn"].label)
        self.form_fill(title="VPN dla serwisu", host="vpn.acme.pl", vpn_type="WireGuard", username="serwis",
                       password="Vpn#2026", vpn_network="10.10.0.0/24")
        main.detail.save()
        self.pump()
        entries = app.s.profiles[pid].data["entries"]
        self.assertEqual(sorted(e["type"] for e in entries), ["computer", "server", "switch", "vpn"])
        sw = next(e for e in entries if e["type"] == "switch")
        self.assertEqual(sw["extra"]["enable"], "En4ble!")
        self.assertEqual(sw["extra"]["protocol"], "SSH")

        # import listy urządzeń do profilu
        inv = os.path.join(self.tmp, "urzadzenia.csv")
        Path(inv).write_text("Typ;Nazwa;IP;Login;Hasło;Model;Lokalizacja\n"
                             "Drukarka;Recepcja;10.10.0.50;admin;Pr1nt!;Brother MFC-L8900;Parter\n"
                             "NAS;NAS01;10.10.0.20;admin;N@s-2026;Synology DS923+;Serwerownia\n"
                             "Router;Brama;10.10.0.1;admin;Rt!2026;MikroTik RB5009;Serwerownia\n", encoding="utf-8")
        imp = app.import_path(inv)
        self.pump()
        self.assertEqual(imp.target.get(), "ACME")
        shot(imp, "05-import-urzadzen")
        imp.go()
        self.pump(0.3)
        self.assertEqual(len(app.s.profiles[pid].data["entries"]), 7)
        self.saved()

        # karta klienta i szczegóły serwera
        main.select_scope(f"c|{pid}")
        self.pump(0.3)
        shot(self.root, "06-karta-klienta")
        srv = next(e for e in app.s.profiles[pid].data["entries"] if e["type"] == "server")
        main.select(pid, srv["id"])
        self.pump(0.3)
        shot(self.root, "07-serwer")
        main.detail.sf.canvas.yview_moveto(1.0)
        self.pump(0.2)
        shot(self.root, "07b-serwer-konta")
        # edycja zmienia hasło dodatkowego konta → historia
        main.detail.edit(pid, srv)
        main.detail.acc_vars[0]["password"].set("Nowe-B@ckup-2027")
        main.detail.save()
        self.pump()
        self.assertEqual(srv["history"][0]["login"], "ACME\\svc_backup")
        main.select(pid, sw["id"])
        self.pump(0.3)
        shot(self.root, "08-switch")

        # wyszukiwanie po lokalizacji we wszystkich źródłach
        main.select_scope("all")
        main.search_entry.focus_set()
        self.pump()
        main.search.set("serwerownia")
        self.pump()
        self.assertEqual(len(main.list.get_children()), 3)  # DC01, NAS01, Brama
        shot(self.root, "09-wyszukiwanie")
        main.search.set("")
        self.pump()

        # --- udostępnienie współpracowniczce jej kodem, bez hasła ------------------------------
        anna = Session({})
        anna.create(os.path.join(self.tmp, "anna.sejf.json"), "hasło Anny 2026")
        anna.set_my_name("Anna Nowak")
        with self.assertRaises(Exception):
            anna.add_profile(prof_path)  # jeszcze nie ma dostępu
        sh = ShareDialog(app, pid).show()
        sh.code.set(anna.my_code())
        sh.add()
        self.wait(lambda: len(app.s.members(pid)) == 2, msg="dodanie osoby")
        self.pump(0.3)
        sh = next(d for d in app.dialogs if isinstance(d, ShareDialog))
        shot(sh, "10-udostepnij")
        sh.close()
        self.saved()
        pa = anna.add_profile(prof_path)  # klucz Anny, bez hasła
        self.assertEqual(pa.file.opened_by, "identity")
        pa.file.data["entries"].append(vault.normalize_entry(vault.new_entry(
            type="wifi", title="Wi-Fi biuro", password="Biuro-WiFi-2026", extra={"ssid": "ACME-Biuro", "security": "WPA2-Personal"})))
        anna.log(pa.id, "dodał wpis", pa.file.data["entries"][-1])
        pa.file.touch()
        pa.file.save()
        self.bump(prof_path)
        app.check_external()
        self.pump(0.3)
        self.assertTrue(any(e["title"] == "Wi-Fi biuro" for e in app.s.profiles[pid].data["entries"]))
        md = MyCodeDialog(app).show()
        self.pump()
        shot(md, "10b-moj-kod")
        md.close()

        # --- weryfikacja dwuetapowa ---------------------------------------------------------
        ts = TotpSetupDialog(app).show()
        self.pump()
        shot(ts, "11-google-authenticator")
        ts.code.set(totp.code_at(ts.secret))
        ts.confirm()
        self.pump()
        rc = app.dialogs[-1]
        shot(rc, "12-kody-zapasowe")
        rc.ok.set(True)
        rc.close()
        self.saved()
        secret = app.s.totp["secret"]
        app.cfg["devices"] = {}  # jak na nowym komputerze
        app.lock()
        self.pump()
        self.assertIsNone(app.s.main)
        lock = app.view
        lock.pw.set(PW)
        lock.unlock()
        self.wait(lambda: hasattr(app.view, "code"), msg="ekran kodu")
        shot(self.root, "13-kod-przy-logowaniu")
        app.view.code.set("000000" if totp.code_at(secret) != "000000" else "111111")
        app.view.check_code()
        self.assertIn("Nieprawidłowy", app.view.err.cget("text"))
        app.view.code.set(totp.code_at(secret))
        app.view.check_code()
        self.wait(lambda: app.main is not None, msg="wejście po kodzie")
        self.wait(lambda: app.s.profiles[pid].file is not None, msg="otwarcie profilu bez hasła")
        main = app.main
        # ponowne odblokowanie na tym samym komputerze nie pyta o kod
        app.lock()
        app.view.pw.set(PW)
        app.view.unlock()
        self.wait(lambda: app.main is not None, msg="odblokowanie bez kodu")
        self.wait(lambda: app.s.profiles[pid].file is not None, msg="profil po odblokowaniu")

        # --- Anna odbiera dostęp, a potem przywraca --------------------------------------------
        anna.remove_member(pa.id, app.s.identity["kid"])
        self.bump(prof_path)
        app.check_external()
        self.pump(0.3)
        self.assertEqual(app.s.profiles[pid].error, "password")
        app.main.select_scope(f"c|{pid}")
        self.pump(0.3)
        shot(self.root, "14-brak-dostepu")
        anna.add_member(pa.id, app.s.my_code())
        self.bump(prof_path)
        app.retry_profile(pid)
        self.wait(lambda: app.s.profiles[pid].file is not None, msg="przywrócony dostęp")

        # --- dostęp hasłem: włączenie, osoba z hasłem dołącza, wyłączenie ------------------------
        d = ChangeProfilePasswordDialog(app, pid).show()
        d.pw.set("krótkie")
        d.go()
        self.assertIn("12 znaków", d.err.cget("text"))
        d.pw.set("Hasło-Profilu-ACME-2026")
        d.go()
        self.wait(lambda: app.s.password_access(pid), msg="włączenie dostępu hasłem")
        self.saved()
        kasia = Session({})
        kasia.create(os.path.join(self.tmp, "kasia.sejf.json"), "hasło Kasi 2026")
        kasia.add_profile(prof_path, "Hasło-Profilu-ACME-2026")
        self.bump(prof_path)
        app.check_external()
        self.wait(lambda: len(app.s.members(pid)) == 3, msg="Kasia na liście osób")

        # --- dodanie profilu z pliku po usunięciu z programu: kluczem, bez pytania o hasło ----------
        app.s.forget_profile(pid)
        app.main.refresh()
        app.add_profile_path(prof_path)
        self.wait(lambda: pid in app.s.profiles and app.s.profiles[pid].file is not None, msg="ponowne dodanie profilu")

        # --- dziennik zmian ---------------------------------------------------------------------
        bank = next(e for e in app.s.profiles[pid].data["entries"] if e["title"] == "NAS01")
        app.copy(bank["password"], "hasło", secret=True, log=(pid, bank))
        self.saved()
        actions = [x["action"] for x in app.s.profiles[pid].data["log"]]
        for expected in ("utworzył profil", "dodał wpis", "zaimportował 3 wpisy", "dodał osobę", "odebrał dostęp",
                         "dołączył do profilu (hasłem)", "skopiował hasło"):
            self.assertIn(expected, actions)
        self.assertIn("Anna Nowak", [x["who"] for x in app.s.profiles[pid].data["log"]])
        lg = LogDialog(app, pid).show()
        self.pump()
        shot(lg, "16-dziennik")
        lg.close()
        app.main.select_scope(f"c|{pid}")
        self.pump(0.3)
        shot(self.root, "06b-karta-klienta-osoby")

        # ciemny motyw na szczegółach switcha
        app.set_theme("dark")
        self.pump(0.3)
        app.main.select(pid, sw["id"])
        self.pump(0.3)
        shot(self.root, "15-ciemny")
        app.set_theme("light")
        self.saved()
        self.assertEqual(self.errors, [])

        # --- blokada razem z Windows i po uśpieniu ------------------------------------------------
        app.system_locked = lambda: True
        app.tick()
        self.assertIsNone(app.s.main)
        self.assertIn("ekranem Windows", app.view.message)
        del app.system_locked
        app.view.pw.set(PW)
        app.view.unlock()
        self.wait(lambda: app.main is not None, msg="odblokowanie po blokadzie Windows")
        app.last_tick = time.time() - 120
        app.tick()
        self.assertIn("uśpiony", app.view.message)
        app.view.pw.set(PW)
        app.view.unlock()
        self.wait(lambda: app.main is not None, msg="odblokowanie po uśpieniu")

        # plik z wersji przeglądarkowej nadal się otwiera
        app.lock()
        app.last_path = str(FIX / "web-vault.json")
        tmp_web = os.path.join(self.tmp, "web.json")
        shutil.copy(app.last_path, tmp_web)
        app.last_path = tmp_web
        app.show_lock("unlock")
        app.view.pw.set(PW)
        app.view.unlock()
        self.wait(lambda: app.main is not None, msg="otwarcie pliku z wersji web")
        self.assertEqual(len(app.s.data["entries"]), 4)
        self.assertTrue(app.s.upgraded)  # stary plik przeniesiony na Argon2id
        app.lock()
        self.assertEqual(ME, "me")


if __name__ == "__main__":
    unittest.main()
