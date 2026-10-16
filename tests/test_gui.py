"""Test okienkowego interfejsu na prawdziwym Tk (uruchamiany na Windows w GitHub Actions).

Ścieżka: nowy sejf → własny wpis → profil klienta → serwer, switch i VPN → import listy urządzeń →
udostępnienie → współpracownik dodaje wpis w tym samym pliku → weryfikacja dwuetapowa → blokada
→ odblokowanie z kodem → zmiana hasła profilu przez inną osobę. Po drodze zapisuje zrzuty ekranu
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
        from sejf.dialogs import NewProfileDialog, ProfilePasswordDialog, ShareDialog, TotpSetupDialog
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
        profile_pw = dlg.pw.get()
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
        self.pump()
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
        main.new_entry()
        self.form_fill(type_label=BY_KEY["vpn"].label)
        self.form_fill(title="VPN dla serwisu", host="vpn.acme.pl", vpn_type="WireGuard", username="serwis",
                       password="Vpn#2026", vpn_network="10.10.0.0/24")
        main.detail.save()
        self.pump()
        entries = app.s.profiles[pid].data["entries"]
        self.assertEqual(sorted(e["type"] for e in entries), ["server", "switch", "vpn"])
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
        self.assertEqual(len(app.s.profiles[pid].data["entries"]), 6)
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

        # udostępnienie
        sh = ShareDialog(app, pid).show()
        self.pump()
        shot(sh, "10-udostepnij")
        sh.close()

        # --- współpracownik pracuje na tym samym pliku ---------------------------------
        anna = Session({})
        anna.create(os.path.join(self.tmp, "anna.sejf.json"), "hasło Anny 2026")
        pa = anna.add_profile(prof_path, profile_pw)
        pa.file.data["entries"].append(vault.normalize_entry(vault.new_entry(
            type="wifi", title="Wi-Fi biuro", password="Biuro-WiFi-2026", extra={"ssid": "ACME-Biuro", "security": "WPA2-Personal"})))
        pa.file.touch()
        pa.file.save()
        self.bump(prof_path)
        app.check_external()
        self.pump(0.3)
        self.assertTrue(any(e["title"] == "Wi-Fi biuro" for e in app.s.profiles[pid].data["entries"]))

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

        # --- inna osoba zmienia hasło profilu -------------------------------------------------
        anna.change_profile_password(pa.id, "nowe hasło ACME 2026")
        self.bump(prof_path)
        app.check_external()
        self.pump(0.3)
        self.assertEqual(app.s.profiles[pid].error, "password")
        app.main.select_scope(f"c|{pid}")
        self.pump(0.3)
        shot(self.root, "14-profil-nowe-haslo")
        d = app.relink_password(pid)
        d.pw.set("nowe hasło ACME 2026")
        d.go()
        self.wait(lambda: app.s.profiles[pid].file is not None, msg="nowe hasło profilu")
        self.assertEqual(app.s.profile_password(pid), "nowe hasło ACME 2026")

        # dodanie istniejącego profilu przez Annę z jej programem: tu tylko ścieżka okna
        app.s.forget_profile(pid)
        app.main.refresh()
        d = ProfilePasswordDialog(app, prof_path).show()
        d.pw.set("złe hasło")
        d.go()
        self.wait(lambda: "Nieprawidłowe" in d.err.cget("text"), msg="złe hasło profilu")
        d.pw.set("nowe hasło ACME 2026")
        d.go()
        self.wait(lambda: pid in app.s.profiles and app.s.profiles[pid].file is not None, msg="ponowne dodanie profilu")

        # ciemny motyw na szczegółach switcha
        app.set_theme("dark")
        self.pump(0.3)
        app.main.select(pid, sw["id"])
        self.pump(0.3)
        shot(self.root, "15-ciemny")
        app.set_theme("light")
        self.saved()
        self.assertEqual(self.errors, [])

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
        app.lock()
        self.assertEqual(ME, "me")


if __name__ == "__main__":
    unittest.main()
