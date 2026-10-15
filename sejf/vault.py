"""Zawartość sejfu: wpisy, kategorie, tagi, wyszukiwanie."""
from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

DEFAULT_CATEGORIES = ["Bank i finanse", "Poczta", "Praca", "Społeczności", "Sklepy", "Rozrywka", "Inne"]
HISTORY_LIMIT = 10


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def default_settings() -> dict:
    return {
        "autoLockMin": 5,
        "clipSec": 30,
        "gen": {"length": 20, "lower": True, "upper": True, "digits": True, "symbols": True, "noAmb": False},
    }


def new_vault() -> dict:
    t = now_iso()
    return {
        "version": 1,
        "created": t,
        "modified": t,
        "entries": [],
        "categories": list(DEFAULT_CATEGORIES),
        "settings": default_settings(),
    }


def new_entry(**fields) -> dict:
    t = now_iso()
    e = {
        "id": new_id(), "title": "", "username": "", "password": "", "url": "", "notes": "",
        "category": "", "tags": [], "fav": False, "created": t, "updated": t, "history": [],
    }
    e.update(fields)
    return e


def _s(v) -> str:
    return "" if v is None else str(v)


def normalize_vault(v: dict | None) -> dict:
    """Uzupełnia brakujące pola, żeby program działał także ze starszymi plikami."""
    base = new_vault()
    v = dict(v or {})
    out = {**base, **v}
    settings = default_settings()
    settings.update(v.get("settings") or {})
    gen = default_settings()["gen"]
    gen.update((v.get("settings") or {}).get("gen") or {})
    settings["gen"] = gen
    out["settings"] = settings
    out["categories"] = [str(c) for c in (v.get("categories") if isinstance(v.get("categories"), list) else []) if c]
    entries = []
    for e in v.get("entries") or []:
        if not isinstance(e, dict):
            continue
        created = e.get("created") or now_iso()
        entries.append({
            "id": e.get("id") or new_id(),
            "title": _s(e.get("title")), "username": _s(e.get("username")), "password": _s(e.get("password")),
            "url": _s(e.get("url")), "notes": _s(e.get("notes")), "category": _s(e.get("category")),
            "tags": [str(t) for t in (e.get("tags") or []) if t],
            "fav": bool(e.get("fav")),
            "created": created, "updated": e.get("updated") or created,
            "history": list(e.get("history") or [])[:HISTORY_LIMIT],
        })
    out["entries"] = entries
    return out


def norm(s: str) -> str:
    """Małe litery bez polskich znaków: „Zażółć” → „zazolc”."""
    s = (s or "").lower().replace("ł", "l")
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def sort_key(e: dict):
    return (norm(e["title"]), e["title"])


def matches(e: dict, query: str) -> bool:
    words = norm(query).split()
    if not words:
        return True
    hay = norm(" ".join([e["title"], e["username"], e["url"], e["notes"], e["category"], " ".join(e["tags"])]))
    return all(w in hay for w in words)


def categories(v: dict) -> list[str]:
    cats = set(v["categories"]) | {e["category"] for e in v["entries"] if e["category"]}
    return sorted(cats, key=lambda c: (norm(c), c))


def tag_counts(v: dict) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for e in v["entries"]:
        for t in e["tags"]:
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], norm(kv[0])))


def filter_entries(v: dict, kind: str = "all", value: str = "", query: str = "") -> list[dict]:
    out = []
    for e in v["entries"]:
        if kind == "fav" and not e["fav"]:
            continue
        if kind == "cat" and e["category"] != value:
            continue
        if kind == "none" and e["category"]:
            continue
        if kind == "tag" and value not in e["tags"]:
            continue
        if matches(e, query):
            out.append(e)
    return sorted(out, key=sort_key)


def parse_tags(text: str) -> list[str]:
    seen, out = set(), []
    for t in re.split(r"[,;]", text or ""):
        t = t.strip().lstrip("#").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def host_of(url: str) -> str:
    if not url:
        return ""
    u = url if re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I) else "https://" + url
    try:
        host = urlsplit(u).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def safe_href(url: str) -> str | None:
    """Adres do otwarcia w przeglądarce; tylko http i https."""
    if not url:
        return None
    u = url if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I) else "https://" + url
    try:
        p = urlsplit(u)
    except ValueError:
        return None
    return u if p.scheme in ("http", "https") and p.hostname else None


def dup_key(e: dict) -> tuple:
    return (host_of(e.get("url", "")) or e.get("title", "").lower(), e.get("username", "").lower(), e.get("password", ""))


def reused_by(v: dict, entry: dict) -> list[dict]:
    if not entry["password"]:
        return []
    return [x for x in v["entries"] if x is not entry and x["id"] != entry["id"] and x["password"] == entry["password"]]


def update_entry(e: dict, fields: dict) -> None:
    """Zmienia wpis; poprzednie hasło trafia do historii."""
    t = now_iso()
    new_pw = fields.get("password", e["password"])
    if e["password"] and new_pw != e["password"]:
        e["history"] = ([{"password": e["password"], "changed": t}] + e["history"])[:HISTORY_LIMIT]
    e.update(fields)
    e["updated"] = t


def plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def wpisy(n: int) -> str:
    return f"{n} {plural(n, 'wpis', 'wpisy', 'wpisów')}"


def fmt_date(iso: str) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return iso
    months = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]
    return f"{d.day} {months[d.month - 1]} {d.year}, {d:%H:%M}"
