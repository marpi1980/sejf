"""Szybkie połączenie z urządzeniem: RDP, SSH, przeglądarka, udział sieciowy, ping.

Funkcja ``plan`` tylko opisuje, co zrobić (łatwo ją przetestować); ``run`` wykonuje to w Windows.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass

from .kinds import DEFAULT_PORTS, kind_of

HOST_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]%]+$")  # nazwa, IPv4, IPv6; bez spacji i znaków powłoki
USER_RE = re.compile(r"^[A-Za-z0-9._\-\\@]+$")


@dataclass(frozen=True)
class Action:
    kind: str           # "url" | "run" | "open"
    target: object      # adres URL, lista argumentów albo ścieżka
    label: str
    copy_password: bool = False
    copy_key: str = "password"   # które hasło skopiować: główne albo pole z ``extra``


def _split(entry: dict) -> tuple[str, str]:
    """Host i port z pola „Adres”; przyjmuje też zapis 10.0.0.1:8443 i https://router/."""
    ex = entry.get("extra") or {}
    h = (ex.get("host") or ex.get("hostname") or "").strip()
    h = re.sub(r"^[a-z]+://", "", h, flags=re.I).split("/")[0]
    port = ""
    if h.count(":") == 1:
        h, port = h.split(":")
    elif h.startswith("[") and "]:" in h:
        h, port = h[1:].split("]:")
    h = h.strip("[]")
    return (h if h and HOST_RE.match(h) else ""), port


def _host(entry: dict) -> str:
    return _split(entry)[0]


def _port(entry: dict) -> str:
    p = ((entry.get("extra") or {}).get("port") or "").strip() or _split(entry)[1]
    return p if p.isdigit() and 0 < int(p) < 65536 else ""


def protocol_of(entry: dict) -> str:
    return ((entry.get("extra") or {}).get("protocol") or kind_of(entry).protocol or "").strip()


ID_RE = re.compile(r"^[A-Za-z0-9@._\-]+$")


def remote_action(entry: dict) -> Action | None:
    """Program do zdalnej pomocy na komputerze użytkownika (RustDesk, AnyDesk, TeamViewer)."""
    ex = entry.get("extra") or {}
    tool = (ex.get("remote_tool") or "").strip()
    rid = re.sub(r"\s+", "", ex.get("remote_id") or "")
    if not rid or not ID_RE.match(rid):
        return None
    if tool == "RustDesk":
        return Action("open", f"rustdesk://{rid}", "Połącz przez RustDesk", True, "remote_password")
    if tool == "AnyDesk":
        return Action("open", f"anydesk:{rid}", "Połącz przez AnyDesk", True, "remote_password")
    if tool == "TeamViewer":
        return Action("open", f"teamviewer10://control?device={rid}", "Połącz przez TeamViewer", True, "remote_password")
    return None


def plan(entry: dict) -> Action | None:
    if kind_of(entry).key == "computer":
        ex = entry.get("extra") or {}
        act = remote_action(entry)
        if act:
            return act
        if (ex.get("remote_tool") or "") != "Pulpit zdalny (RDP)":
            return None
        host, port, proto = _host(entry), "", "RDP"
    else:
        host, port, proto = _host(entry), _port(entry), protocol_of(entry)
    user = (entry.get("username") or "").strip()
    if not host:
        return None
    if proto in ("HTTPS", "HTTP"):
        scheme = proto.lower()
        default = DEFAULT_PORTS[proto]
        hp = f"[{host}]" if ":" in host else host
        return Action("url", f"{scheme}://{hp}" + (f":{port}" if port and port != default else "") + "/",
                      "Otwórz w przeglądarce")
    if proto == "RDP":
        hp = f"[{host}]" if ":" in host else host
        return Action("run", ["mstsc", f"/v:{hp}" + (f":{port}" if port else "")], "Pulpit zdalny (RDP)", True)
    if proto == "SSH":
        args = ["ssh"] + (["-p", port] if port else []) + ([f"{user}@{host}"] if user and USER_RE.match(user) else [host])
        return Action("run", args, "Terminal SSH", True)
    if proto == "Telnet":
        return Action("run", ["telnet", host] + ([port] if port else []), "Telnet", True)
    if proto == "SMB":
        share = ((entry.get("extra") or {}).get("share") or "").strip()
        return Action("open", share if share.startswith("\\\\") else f"\\\\{host}", "Otwórz udział sieciowy", True)
    return None


def console_action(entry: dict) -> Action | None:
    """Konsola zarządzania serwerem (iDRAC, iLO, IPMI) w przeglądarce."""
    v = ((entry.get("extra") or {}).get("idrac") or "").strip()
    if not v:
        return None
    url = v if re.match(r"^https?://", v, re.I) else "https://" + v
    host = re.sub(r"^https?://", "", url, flags=re.I).split("/")[0]
    if not host or not HOST_RE.match(host.replace("[", "").replace("]", "")):
        return None
    return Action("url", url, "Konsola zarządzania", True, "idrac_password")


def share_action(entry: dict) -> Action | None:
    """Dla NAS-ów i drukarek z polem „Udział sieciowy” / „Skanowanie do”."""
    ex = entry.get("extra") or {}
    for key, secret in (("share", "password"), ("scan_to", "password"), ("drive", "drive_password")):
        v = (ex.get(key) or "").strip()
        m = re.search(r"\\\\[^\s=]+", v)  # „Z: = \\srv01\dane” → \\srv01\dane
        if m:
            return Action("open", m.group(0), "Otwórz udział" if key != "drive" else "Otwórz dysk", True, secret)
    return None


def ping_action(entry: dict) -> Action | None:
    host = _host(entry)
    if not host:
        return None
    return Action("run", ["ping", "-t", host] if sys.platform == "win32" else ["ping", host], "Ping")


def available() -> bool:
    return sys.platform == "win32"


def run(action: Action) -> None:
    if action.kind == "url":
        webbrowser.open(action.target)
    elif action.kind == "open":
        os.startfile(action.target)  # type: ignore[attr-defined]  # tylko Windows
    elif action.kind == "run":
        args = list(action.target)
        if args[0] == "mstsc":
            subprocess.Popen(args, close_fds=True)
            return
        # programy konsolowe w nowym oknie: Windows Terminal, a jeśli go nie ma, zwykła konsola
        wt = shutil.which("wt")
        if wt:
            subprocess.Popen([wt, "new-tab", "--title", action.label, *args], close_fds=True)
        else:
            subprocess.Popen(["cmd", "/k", *args], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                             close_fds=True)
