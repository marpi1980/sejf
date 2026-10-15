"""Import i eksport haseł w formacie CSV (Chrome, Edge, Firefox, Bitwarden, KeePass, 1Password…)."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from .vault import dup_key, host_of, parse_tags

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
}


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
    if idx["password"] < 0:
        raise ValueError("Nie znaleziono kolumny z hasłami. Plik musi mieć kolumnę „password” albo „hasło”.")
    if "login_password" in head:
        fmt = "Bitwarden"
    elif "httprealm" in head:
        fmt = "Firefox"
    elif "group" in head and "title" in head:
        fmt = "KeePass"
    elif "name" in head and "url" in head:
        fmt = "Chrome / Edge / Opera"
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
        if not (e["password"] or e["username"] or e["notes"]):
            continue
        parts = [p for p in e["category"].replace("\\", "/").split("/") if p]
        if parts and parts[0].lower() == "root":
            parts = parts[1:]
        e["category"] = parts[-1] if parts else ""
        if not e["title"]:
            e["title"] = host_of(e["url"]) or e["username"] or "Bez nazwy"
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
    w.writerow(["name", "url", "username", "password", "note", "category", "tags", "favorite"])
    for e in entries:
        w.writerow([e["title"], e["url"], e["username"], e["password"], e["notes"], e["category"],
                    ", ".join(e["tags"]), "1" if e["fav"] else ""])
    return "﻿" + buf.getvalue()
