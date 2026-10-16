"""Zawartość sejfu i profili klientów: wpisy, kategorie, tagi, wyszukiwanie, łączenie zmian."""
from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from .kinds import BY_KEY, kind_of, searchable

DEFAULT_CATEGORIES = ["Bank i finanse", "Poczta", "Praca", "Społeczności", "Sklepy", "Rozrywka", "Inne"]
HISTORY_LIMIT = 10
TOMBSTONE_DAYS = 365
PROFILE_INFO_FIELDS = (
    ("company", "Pełna nazwa firmy"),
    ("nip", "NIP"),
    ("address", "Adres"),
    ("contact", "Osoba kontaktowa"),
    ("phone", "Telefon"),
    ("email", "E-mail"),
    ("support", "Umowa serwisowa / SLA"),
    ("notes", "Notatki"),
)


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
        "uid": new_id(),
        "created": t,
        "modified": t,
        "entries": [],
        "categories": list(DEFAULT_CATEGORIES),
        "settings": default_settings(),
        "profiles": [],
        "security": {},
        "deleted": {},
    }


def new_profile(name: str, info: dict | None = None) -> dict:
    t = now_iso()
    return {
        "kind": "profile",
        "version": 1,
        "id": new_id(),
        "name": name,
        "info": {**(info or {}), "updated": t},
        "created": t,
        "modified": t,
        "entries": [],
        "categories": [],
        "deleted": {},
    }


def new_entry(**fields) -> dict:
    t = now_iso()
    e = {
        "id": new_id(), "type": "web", "title": "", "username": "", "password": "", "url": "", "notes": "",
        "category": "", "tags": [], "fav": False, "extra": {}, "created": t, "updated": t, "history": [],
    }
    e.update(fields)
    return e


def _s(v) -> str:
    return "" if v is None else str(v)


def normalize_entry(e: dict) -> dict:
    created = e.get("created") or now_iso()
    out = dict(e)  # pola nieznane tej wersji zostają nietknięte
    typ = e.get("type") if e.get("type") in BY_KEY else "web"
    out.update({
        "id": e.get("id") or new_id(),
        "type": typ,
        "title": _s(e.get("title")), "username": _s(e.get("username")), "password": _s(e.get("password")),
        "url": _s(e.get("url")), "notes": _s(e.get("notes")), "category": _s(e.get("category")),
        "tags": [str(t) for t in (e.get("tags") or []) if t],
        "fav": bool(e.get("fav")),
        "extra": {str(k): _s(v) for k, v in (e.get("extra") or {}).items() if v not in ("", None)}
        if isinstance(e.get("extra"), dict) else {},
        "created": created, "updated": e.get("updated") or created,
        "history": list(e.get("history") or [])[:HISTORY_LIMIT],
    })
    return out


def _entries(v: dict) -> list[dict]:
    return [normalize_entry(e) for e in (v.get("entries") or []) if isinstance(e, dict)]


def _deleted(v: dict) -> dict:
    d = v.get("deleted")
    return {str(k): str(t) for k, t in d.items()} if isinstance(d, dict) else {}


def normalize_vault(v: dict | None) -> dict:
    """Uzupełnia brakujące pola, żeby program działał także ze starszymi plikami."""
    v = dict(v or {})
    base = new_vault()
    if not v.get("uid"):
        v.pop("uid", None)
    out = {**base, **v}
    settings = default_settings()
    settings.update(v.get("settings") or {})
    gen = default_settings()["gen"]
    gen.update((v.get("settings") or {}).get("gen") or {})
    settings["gen"] = gen
    out["settings"] = settings
    out["categories"] = [str(c) for c in (v.get("categories") if isinstance(v.get("categories"), list) else []) if c]
    out["entries"] = _entries(v)
    out["deleted"] = _deleted(v)
    out["profiles"] = [dict(p) for p in (v.get("profiles") or []) if isinstance(p, dict) and p.get("id")]
    out["security"] = dict(v.get("security") or {}) if isinstance(v.get("security"), dict) else {}
    return out


def normalize_profile(p: dict | None) -> dict:
    p = dict(p or {})
    base = new_profile(_s(p.get("name")) or "Klient")
    out = {**base, **p}
    out["name"] = _s(p.get("name")) or "Klient"
    out["id"] = p.get("id") or base["id"]
    info = p.get("info") if isinstance(p.get("info"), dict) else {}
    out["info"] = {k: _s(v) for k, v in info.items()}
    out["info"].setdefault("updated", out.get("created") or now_iso())
    out["categories"] = [str(c) for c in (p.get("categories") or []) if c]
    out["entries"] = _entries(p)
    out["deleted"] = _deleted(p)
    return out


# --- łączenie zmian z kilku komputerów ---------------------------------------------------------
def _newer(a: dict | None, b: dict | None, key: str = "updated") -> dict | None:
    if a is None:
        return b
    if b is None:
        return a
    return b if (b.get(key) or "") > (a.get(key) or "") else a


def _merge_list(remote: list, local: list, tomb: dict) -> list:
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for item in (*remote, *local):
        iid = item["id"]
        if iid not in by_id:
            order.append(iid)
        by_id[iid] = _newer(by_id.get(iid), item)
    out = []
    for iid in order:
        item = by_id[iid]
        if iid in tomb and tomb[iid] >= (item.get("updated") or ""):
            continue
        out.append(item)
    return out


def _prune(tomb: dict) -> dict:
    limit = (datetime.now(timezone.utc) - timedelta(days=TOMBSTONE_DAYS)).isoformat().replace("+00:00", "Z")
    return {k: t for k, t in tomb.items() if t >= limit}


def merge(remote: dict, local: dict) -> dict:
    """Łączy dwie wersje tego samego pliku: nowsza zmiana każdego wpisu wygrywa, usunięcia są zachowane.

    Dzięki temu kilka osób może pracować na jednym profilu klienta we wspólnym folderze,
    a zmiany jednej osoby nie kasują zmian drugiej.
    """
    tomb = dict(remote.get("deleted") or {})
    for k, t in (local.get("deleted") or {}).items():
        tomb[k] = max(t, tomb.get(k, ""))
    out = dict(local)
    out["entries"] = _merge_list(remote.get("entries") or [], local.get("entries") or [], tomb)
    cats = list(remote.get("categories") or [])
    cats += [c for c in local.get("categories") or [] if c not in cats]
    out["categories"] = cats
    out["deleted"] = _prune(tomb)
    out["modified"] = max(remote.get("modified") or "", local.get("modified") or "")
    if "profiles" in local or "profiles" in remote:  # osobisty sejf
        out["profiles"] = _merge_list(remote.get("profiles") or [], local.get("profiles") or [], tomb)
        out["security"] = _newer(remote.get("security") or {}, local.get("security") or {}) or {}
    if "info" in local or "info" in remote:  # profil klienta
        r_info, l_info = remote.get("info") or {}, local.get("info") or {}
        out["info"] = _newer(r_info, l_info)
        out["name"] = (remote if out["info"] is r_info else local).get("name") or local.get("name") or remote.get("name")
    return out


def delete_entry(data: dict, entry_id: str) -> None:
    data["entries"] = [x for x in data["entries"] if x["id"] != entry_id]
    data.setdefault("deleted", {})[entry_id] = now_iso()


# --- wyszukiwanie i filtry -------------------------------------------------------------------
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
    hay = norm(searchable(e))
    return all(w in hay for w in words)


def categories(v: dict) -> list[str]:
    cats = set(v.get("categories") or []) | {e["category"] for e in v["entries"] if e["category"]}
    return sorted(cats, key=lambda c: (norm(c), c))


def tag_counts(v: dict) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for e in v["entries"]:
        for t in e["tags"]:
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], norm(kv[0])))


def type_counts(v: dict) -> list[tuple[str, int]]:
    from .kinds import KINDS
    counts: dict[str, int] = {}
    for e in v["entries"]:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    return [(k.key, counts[k.key]) for k in KINDS if counts.get(k.key)]


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
        if kind == "type" and e["type"] != value:
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
    host = host_of(e.get("url", "")) or (e.get("extra") or {}).get("host", "") or e.get("title", "").lower()
    return (host.lower(), e.get("username", "").lower(), e.get("password", ""))


def reused_by(entries: list[dict], entry: dict) -> list[dict]:
    if not entry["password"] or len(entry["password"]) < 4:
        return []
    return [x for x in entries if x["id"] != entry["id"] and x["password"] == entry["password"]]


def update_entry(e: dict, fields: dict) -> None:
    """Zmienia wpis; poprzednie hasło trafia do historii."""
    t = now_iso()
    new_pw = fields.get("password", e["password"])
    if e["password"] and new_pw != e["password"]:
        e["history"] = ([{"password": e["password"], "changed": t}] + e["history"])[:HISTORY_LIMIT]
    e.update(fields)
    e["updated"] = t


def expiry_state(e: dict, today=None) -> tuple[str, str] | None:
    """Dla licencji i baterii UPS: ('expired'|'soon', opis) gdy termin minął albo zbliża się."""
    k = kind_of(e)
    ex = e.get("extra") or {}
    for f in k.fields:
        if f.kind != "date" or not ex.get(f.key):
            continue
        try:
            d = datetime.strptime(ex[f.key].strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        today = today or datetime.now().date()
        days = (d - today).days
        if days < 0:
            return "expired", f"{f.label}: termin minął {fmt_day(d)}"
        if days <= 30:
            return "soon", f"{f.label}: {fmt_day(d)} (za {days} {plural(days, 'dzień', 'dni', 'dni')})"
    return None


def plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def wpisy(n: int) -> str:
    return f"{n} {plural(n, 'wpis', 'wpisy', 'wpisów')}"


MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]


def fmt_day(d) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def fmt_date(iso: str) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return iso
    return f"{fmt_day(d)}, {d:%H:%M}"
