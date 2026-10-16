"""Szybki test działania zbudowanego programu (Sejf.exe --selftest wynik.txt)."""
from __future__ import annotations

import os
import tempfile
import traceback


def run(out_path: str | None) -> int:
    lines = []
    ok = True
    try:
        with tempfile.TemporaryDirectory() as d:
            os.environ["SEJF_CONFIG_DIR"] = d
            import tkinter as tk

            from . import totp, vault
            from .gui import App
            from .session import Session

            path = os.path.join(d, "test.sejf.json")
            s = Session()
            s.create(path, "hasło testowe 123")
            s.data["entries"].append(vault.new_entry(title="Test", password="x"))
            p = s.create_profile(os.path.join(d, "klient.sejfklient"), "Klient", "hasło klienta 123")
            p.file.data["entries"].append(vault.new_entry(type="server", title="Serwer", extra={"host": "10.0.0.1"}))
            p.file.touch(); p.file.save()
            s.mark_changed(); s.save()
            lines.append("szyfrowanie i profile: OK")
            assert totp.verify(totp.new_secret() and "JBSWY3DPEHPK3PXP", totp.code_at("JBSWY3DPEHPK3PXP"))
            lines.append("weryfikacja dwuetapowa: OK")
            root = tk.Tk()
            app = App(root)
            app.s.unlock(path, "hasło testowe 123")
            app.s.open_profiles()
            app.enter_main(keep=True)
            root.update()
            assert len(app.main.list.get_children()) == 2, app.main.list.get_children()
            lines.append("okno: OK")
            import segno  # noqa: F401
            import sv_ttk  # noqa: F401
            lines.append("motyw i kody QR: OK")
            app.s.lock()
            root.destroy()
    except Exception:  # noqa: BLE001
        ok = False
        lines.append(traceback.format_exc())
    lines.append("WYNIK: OK" if ok else "WYNIK: BŁĄD")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    return 0 if ok else 1
