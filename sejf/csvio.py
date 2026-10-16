"""Import i eksport haseł w formacie CSV (Chrome, Edge, Firefox, Bitwarden, KeePass, 1Password…)."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

import json

from .kinds import BY_KEY, KINDS
from .vault import dup_key, host_of, norm, parse_tags

COLUMNS = {
    "title": ["name", "title", "nazwa", "tytuł", "tytul", "account", "konto"],
    "url": ["url", "login_uri", "website", "web site", "adres", "uri", "login url", "adres www", "strona"],
    "username": ["username", "login_username", "user name", "login", "email", "e-mail", "user", "użytkownik",
                 "uzytkownik", "nazwa użytkownika"],
    "password": ["password", "login_password", "hasło", "haslo"],
    "notes": ["note", "notes", "extra", "notatki", "notatka", "comments", "uwagi"],
    "category": ["folder", "group", "grouping", "category", "kategoria", "grupa"],
    "fav": ["favorite", "fav", "ulubione"],
    "tags": ["tags", "tagi"],
    "type": ["type", "typ", "rodzaj", "rodzaj urządzenia", "typ urządzenia", "urządzenie"],
    "extra": ["extra", "dodatkowe"],
    "accounts": ["accounts", "konta"],
}
# kolumny z arkuszy inwentaryzacji IT → pola urządzeń
EXTRA_COLUMNS = {
    "host": ["host", "hostname", "ip", "adres ip", "ip address", "ip adres", "adres urządzenia", "nazwa hosta"],
    "port": ["port"],
    "protocol": ["protocol", "protokół", "protokol"],
    "model": ["model", "producent", "producent i model", "vendor"],
    "serial": ["serial", "sn", "s/n", "numer seryjny", "nr seryjny", "serial number"],
    "mac": ["mac", "adres mac", "mac address"],
    "location": ["location", "lokalizacja", "miejsce"],
    "domain": ["domain", "domena"],
    "ssid": ["ssid"],
    "license_key": ["license key", "klucz", "klucz licencyjny", "product key"],
    "valid_until": ["valid until", "ważna do", "wazna do", "data ważności"],
}


def kind_from_text(text: str) -> str | None:
    """„Serwer”, „switch”, „Przełączniki”, „NAS” → klucz typu."""
    t = norm(text).strip()
    if not t:
        return None
    if t in BY_KEY:
        return t
    for k in KINDS:
        if t in (norm(k.label), norm(k.group)) or norm(k.label).startswith(t):
            return k.key
    aliases = {"switch": "switch", "przelacznik": "switch", "router": "router", "firewall": "router", "nas": "nas",
               "drukarka": "printer", "printer": "printer", "wifi": "wifi", "wi-fi": "wifi", "ap": "ap",
               "kamera": "camera", "nvr": "camera", "ups": "ups", "baza": "database", "vpn": "vpn", "serwer": "server",
               "server": "server", "licencja": "license", "konto": "account", "poczta": "email", "e-mail": "email",
               "strona": "web", "www": "web"}
    for word, key in aliases.items():
        if word in t.split() or t.startswith(word):
            return key
    return None


@dataclass
class ImportResult:
    fmt: str
    entries: list[dict]


def decode(raw: bytes) -> str:
    """UTF-8 (z BOM lub bez), a dla plików z polskiego Excela Windows-1250."""
    for enc in ("utf-8-sig", "cp1250"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _delimiter(text: str) -> str:
    first = text.split("\n", 1)[0]
    counts = {d: first.count(d) for d in (",", ";", "\t")}
    return max(counts, key=lambda d: (counts[d], d == ","))


def parse(text: str) -> ImportResult:
    text = text.lstrip("﻿")
    rows = [r for r in csv.reader(io.StringIO(text, newline=""), delimiter=_delimiter(text)) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValueError("Plik jest pusty albo ma tylko nagłówek.")
    head = [h.strip().lower() for h in rows[0]]
    idx = {k: next((i for i, h in enumerate(head) if h in names), -1) for k, names in COLUMNS.items()}
    ex_idx = {k: next((i for i, h in enumerate(head) if h in names), -1) for k, names in EXTRA_COLUMNS.items()}
    if idx["password"] < 0 and ex_idx["host"] < 0:
        raise ValueError("Nie znaleziono kolumny z hasłami ani adresami. Plik musi mieć kolumnę „password”/„hasło” "
                         "albo „IP”/„host”.")
    if "login_password" in head:
        fmt = "Bitwarden"
    elif "httprealm" in head:
        fmt = "Firefox"
    elif "group" in head and "title" in head:
        fmt = "KeePass"
    elif "type" in head and "extra" in head:
        fmt = "Sejf"
    elif "name" in head and "url" in head:
        fmt = "Chrome / Edge / Opera"
    elif ex_idx["host"] >= 0:
        fmt = "Lista urządzeń"
    else:
        fmt = "CSV"

    def get(r, k, strip=True):
        i = idx[k]
        v = r[i] if 0 <= i < len(r) else ""
        return v.strip() if strip else v

    out = []
    for r in rows[1:]:
        e = {
            "title": get(r, "title"), "url": get(r, "url"), "username": get(r, "username"),
            "password": get(r, "password", strip=False), "notes": get(r, "notes"),
            "category": get(r, "category"), "fav": get(r, "fav").lower() in ("1", "true", "tak", "yes"),
            "tags": parse_tags(get(r, "tags")),
        }
        extra = {}
        raw_extra = get(r, "extra")
        if raw_extra.startswith("{"):
            try:
                extra = {str(k): str(v) for k, v in json.loads(raw_extra).items() if v not in ("", None)}
            except ValueError:
                extra = {}
        for key, i in ex_idx.items():
            if 0 <= i < len(r) and r[i].strip():
                extra.setdefault(key, r[i].strip())
        accounts = []
        raw_acc = get(r, "accounts")
        if raw_acc.startswith("["):
            try:
                accounts = [a for a in json.loads(raw_acc) if isinstance(a, dict)]
            except ValueError:
                accounts = []
        e["accounts"] = accounts
        typ = kind_from_text(get(r, "type"))
        if not typ:
            typ = "device" if extra.get("host") and not e["url"] else "web"
        e["type"], e["extra"] = typ, extra
        if not (e["password"] or e["username"] or e["notes"] or extra):
            continue
        parts = [p for p in e["category"].replace("\\", "/").split("/") if p]
        if parts and parts[0].lower() == "root":
            parts = parts[1:]
        e["category"] = parts[-1] if parts else ""
        if not e["title"]:
            e["title"] = host_of(e["url"]) or extra.get("host") or extra.get("ssid") or e["username"] or "Bez nazwy"
        out.append(e)
    return ImportResult(fmt, out)


def without_duplicates(existing: list[dict], incoming: list[dict]) -> list[dict]:
    have = {dup_key(e) for e in existing}
    out = []
    for e in incoming:
        k = dup_key(e)
        if k not in have:
            have.add(k)
            out.append(e)
    return out


def to_csv(entries: list[dict]) -> str:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["name", "url", "username", "password", "note", "category", "tags", "favorite", "type", "host", "extra",
                "accounts"])
    for e in entries:
        ex = e.get("extra") or {}
        w.writerow([e["title"], e["url"], e["username"], e["password"], e["notes"], e["category"],
                    ", ".join(e["tags"]), "1" if e["fav"] else "", e.get("type", "web"), ex.get("host", ""),
                    json.dumps(ex, ensure_ascii=False) if ex else "",
                    json.dumps([{k: a.get(k, "") for k in ("label", "username", "password")} for a in e.get("accounts") or []],
                               ensure_ascii=False) if e.get("accounts") else ""])
    return "﻿" + buf.getvalue()
