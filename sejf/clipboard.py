"""Schowek. Na Windows hasła są oznaczane tak, żeby nie trafiały do historii schowka (Win+V)
ani do schowka w chmurze; tak samo robią KeePass i inne menedżery haseł."""
from __future__ import annotations

import struct
import sys
import time

_win = None
if sys.platform == "win32":
    try:
        import ctypes
        from ctypes import wintypes as w

        class _Win:
            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002

            def __init__(self):
                self.u32 = ctypes.WinDLL("user32", use_last_error=True)
                self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                u, k = self.u32, self.k32
                u.OpenClipboard.argtypes = [w.HWND]; u.OpenClipboard.restype = w.BOOL
                u.CloseClipboard.argtypes = []; u.CloseClipboard.restype = w.BOOL
                u.EmptyClipboard.argtypes = []; u.EmptyClipboard.restype = w.BOOL
                u.SetClipboardData.argtypes = [w.UINT, w.HANDLE]; u.SetClipboardData.restype = w.HANDLE
                u.RegisterClipboardFormatW.argtypes = [w.LPCWSTR]; u.RegisterClipboardFormatW.restype = w.UINT
                u.IsClipboardFormatAvailable.argtypes = [w.UINT]; u.IsClipboardFormatAvailable.restype = w.BOOL
                k.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]; k.GlobalAlloc.restype = w.HGLOBAL
                k.GlobalLock.argtypes = [w.HGLOBAL]; k.GlobalLock.restype = w.LPVOID
                k.GlobalUnlock.argtypes = [w.HGLOBAL]; k.GlobalUnlock.restype = w.BOOL
                k.GlobalFree.argtypes = [w.HGLOBAL]; k.GlobalFree.restype = w.HGLOBAL
                self.private_formats = [
                    (u.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing"), b"\0\0\0\0"),
                    (u.RegisterClipboardFormatW("CanIncludeInClipboardHistory"), struct.pack("<I", 0)),
                    (u.RegisterClipboardFormatW("CanUploadToCloudClipboard"), struct.pack("<I", 0)),
                ]

            def _open(self):
                for _ in range(20):
                    if self.u32.OpenClipboard(None):
                        return
                    time.sleep(0.025)
                raise OSError("Schowek jest zajęty przez inny program.")

            def _put(self, fmt, data: bytes):
                h = self.k32.GlobalAlloc(self.GMEM_MOVEABLE, len(data))
                if not h:
                    raise OSError("Brak pamięci dla schowka.")
                p = self.k32.GlobalLock(h)
                ctypes.memmove(p, data, len(data))
                self.k32.GlobalUnlock(h)
                if not self.u32.SetClipboardData(fmt, h):
                    self.k32.GlobalFree(h)
                    raise OSError("Nie udało się skopiować do schowka.")

            def set_text(self, text: str, private: bool):
                self._open()
                try:
                    self.u32.EmptyClipboard()
                    self._put(self.CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))
                    if private:
                        for fmt, data in self.private_formats:
                            if fmt:
                                self._put(fmt, data)
                finally:
                    self.u32.CloseClipboard()

            def clear(self):
                self._open()
                try:
                    self.u32.EmptyClipboard()
                finally:
                    self.u32.CloseClipboard()

            def is_private(self) -> bool:
                fmt = self.private_formats[0][0]
                return bool(fmt and self.u32.IsClipboardFormatAvailable(fmt))

        _win = _Win()
    except Exception:  # noqa: BLE001 – w razie problemów zwykły schowek Tk
        _win = None


class Clipboard:
    def __init__(self, tk_root):
        self.root = tk_root

    def set(self, text: str, private: bool = False) -> None:
        if _win is not None:
            try:
                _win.set_text(text, private)
                return
            except OSError:
                pass
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

    def get(self) -> str | None:
        try:
            return self.root.clipboard_get()
        except Exception:  # noqa: BLE001 – pusty schowek albo inny format
            return None

    def clear_if(self, text: str) -> bool:
        """Czyści schowek tylko wtedy, gdy nadal jest w nim nasze hasło."""
        if self.get() != text:
            return False
        if _win is not None:
            try:
                _win.clear()
                return True
            except OSError:
                pass
        self.root.clipboard_clear()
        self.root.clipboard_append("")
        self.root.update()
        return True

    @staticmethod
    def is_private() -> bool:
        return bool(_win and _win.is_private())
