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
    h = ((entry.get("extra") or {}).get("host") or "").strip()
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


def plan(entry: dict) -> Action | None:
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
    for key in ("share", "scan_to"):
        v = (ex.get(key) or "").strip()
        if v.startswith("\\\\") and "\n" not in v:
            return Action("open", v, "Otwórz udział sieciowy", True)
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
