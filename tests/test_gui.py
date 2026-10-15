"""Test okienkowego interfejsu na prawdziwym Tk (uruchamiany na Windows w GitHub Actions).

Przechodzi typową ścieżkę: nowy sejf → wpis z wygenerowanym hasłem → import CSV →
wyszukiwanie → kopiowanie → blokada → odblokowanie. Po drodze zapisuje zrzuty ekranu
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
    try:
        from PIL import ImageGrab
    except ImportError:
        return
    if sys.platform != "win32":
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
        os.environ["SEJF_CONFIG_DIR"] = self.tmp
        self.path = os.path.join(self.tmp, "hasla.sejf.json")
        messagebox.askyesno = lambda *a, **k: True
        messagebox.showinfo = lambda *a, **k: "ok"
        from sejf.gui import App
        self.root = tk.Tk()
        self.root.geometry("1000x700+0+0")
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

    def wait(self, cond, timeout=15, msg="warunek"):
        end = time.time() + timeout
        while time.time() < end:
            self.root.update()
            if cond():
                return
            time.sleep(0.02)
        self.fail(f"Przekroczono czas oczekiwania: {msg}")

    def test_full_flow(self):
        app = self.app
        shot(self.root, "01-start")

        # nowy sejf przez ekran blokady
        lock = app.view
        lock.show_create()
        lock.n1.set("krótkie")
        lock.n2.set("krótkie")
        lock.create()
        self.assertIn("8 znaków", lock.err.cget("text"))
        lock.n1.set(PW)
        lock.n2.set(PW)
        self.pump()
        shot(self.root, "02-nowy-sejf")
        app.create_vault(self.path, PW, lock)
        self.wait(lambda: app.main is not None, msg="utworzenie sejfu")
        self.assertTrue(os.path.exists(self.path))
        self.pump(0.3)
        shot(self.root, "03-pusty-sejf")

        # nowy wpis z hasłem z generatora
        main = app.main
        main.new_entry()
        self.pump()
        f = main.detail.form
        f["title"].set("Allegro")
        f["username"].set("jan.kowalski")
        f["url"].set("allegro.pl")
        f["category"].set("Sklepy")
        f["tags"].set("zakupy, #2FA")
        gen = app.open_generator(lambda v: f["password"].set(v))
        gen.length.set(28)
        gen.regen()
        self.pump()
        shot(gen, "04-generator")
        generated = gen.out.get()
        self.assertEqual(len(generated), 28)
        gen.use()
        self.assertEqual(f["password"].get(), generated)
        shot(self.root, "05-edycja")
        main.detail.save()
        self.pump(0.5)
        self.assertEqual(len(app.s.data["entries"]), 1)
        self.wait(lambda: not app.s.dirty, msg="autozapis")

        # import CSV
        preview = app.load_import(str(FIX / "chrome.csv"))
        self.assertEqual(preview.found, 4)
        self.assertEqual(len(preview.fresh), 3)
        from sejf.gui import ImportDialog
        dlg = ImportDialog(app, preview).show()
        self.pump()
        shot(dlg, "06-import")
        dlg.go()
        self.pump(0.3)
        self.assertEqual(len(app.s.data["entries"]), 4)
        self.assertEqual(len(main.list.get_children()), 4)

        # wyszukiwanie bez polskich znaków
        main.search.set("zazolc")
        self.pump()
        self.assertEqual(len(main.list.get_children()), 1)
        main.search.set("")
        self.pump()

        # szczegóły i kopiowanie hasła
        bank = next(e for e in app.s.data["entries"] if e["title"] == "Bank PKO")
        main.select(bank["id"])
        self.pump(0.3)
        shot(self.root, "07-szczegoly")
        app.copy(bank["password"], "hasło", secret=True)
        self.pump()
        self.assertEqual(app.clip.get(), "Kot123")
        if sys.platform == "win32":
            self.assertTrue(app.clip.is_private(), "hasło powinno być wyłączone z historii schowka Windows")
        app.clear_clip()
        self.pump()
        self.assertNotEqual(app.clip.get(), "Kot123")

        # historia hasła
        main.detail.edit(bank)
        main.detail.form["password"].set("Nowe-Haslo-2026!")
        main.detail.save()
        self.pump(0.3)
        self.assertEqual(bank["history"][0]["password"], "Kot123")

        # filtr kategorii i ulubione
        main.toggle_fav(bank)
        main.nav.selection_set("fav")
        self.pump()
        self.assertEqual(list(main.list.get_children()), [bank["id"]])
        main.nav.selection_set("all")
        self.pump()

        # ustawienia, eksport, ciemny motyw
        sd = app.open_settings()
        self.pump()
        shot(sd, "08-ustawienia")
        sd.close()
        ed = app.open_export()
        self.pump()
        shot(ed, "09-eksport")
        ed.close()
        app.set_theme("dark")
        self.pump(0.3)
        main = app.main
        gmail = next(e for e in app.s.data["entries"] if e["title"] == "Gmail")
        main.select(gmail["id"])
        self.pump(0.3)
        shot(self.root, "10-ciemny")
        app.set_theme("light")
        self.pump()

        # zmiana pliku "na telefonie" jest wczytywana automatycznie
        from sejf import vault
        from sejf.session import Session
        self.wait(lambda: not app.s.dirty and app.save_job is None, msg="zapis przed synchronizacją")
        time.sleep(0.05)
        phone = Session()
        phone.unlock(self.path, PW)
        phone.data["entries"].append(vault.new_entry(title="Z telefonu"))
        phone.mark_changed()
        phone.save()
        st = os.stat(self.path)
        os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
        app.check_external()
        self.pump()
        self.assertTrue(any(e["title"] == "Z telefonu" for e in app.s.data["entries"]))

        # usuwanie
        main = app.main
        main.delete(next(e for e in app.s.data["entries"] if e["title"] == "Z telefonu"))
        self.pump(0.5)
        self.assertEqual(len(app.s.data["entries"]), 4)

        # blokada i odblokowanie
        app.lock()
        self.pump()
        self.assertFalse(app.s.unlocked)
        self.assertIsNone(app.s.key)
        lock = app.view
        lock.pw.set("złe hasło")
        lock.unlock()
        self.wait(lambda: "Nieprawidłowe" in lock.err.cget("text"), msg="odrzucenie złego hasła")
        shot(self.root, "11-blokada")
        lock.pw.set(PW)
        lock.unlock()
        self.wait(lambda: app.main is not None, msg="odblokowanie")
        self.assertEqual(len(app.main.list.get_children()), 4)

        # plik z wersji przeglądarkowej
        app.lock()
        app.last_path = str(FIX / "web-vault.json")
        app.show_lock("unlock")
        app.view.pw.set(PW)
        app.view.unlock()
        self.wait(lambda: app.main is not None, msg="otwarcie pliku z wersji web")
        self.assertEqual(len(app.main.list.get_children()), 4)
        app.s.lock()


if __name__ == "__main__":
    unittest.main()
