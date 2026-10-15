"""Generator haseł i ocena ich siły."""
from __future__ import annotations

import math
import re
import secrets

from .vault import norm

SETS = {
    "lower": "abcdefghijklmnopqrstuvwxyz",
    "upper": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "digits": "0123456789",
    "symbols": "!@#$%^&*()-_=+[]{};:,.?/~",
}
AMBIGUOUS = set("Il1O0o|")


def generate(length: int = 20, lower: bool = True, upper: bool = True, digits: bool = True,
             symbols: bool = True, noAmb: bool = False) -> str:
    """Losowe hasło z kryptograficznie bezpiecznego źródła; zawiera co najmniej jeden znak z każdej wybranej grupy."""
    chosen = {"lower": lower, "upper": upper, "digits": digits, "symbols": symbols}
    groups = []
    for name, on in chosen.items():
        if on:
            chars = SETS[name]
            if noAmb:
                chars = "".join(c for c in chars if c not in AMBIGUOUS)
            groups.append(chars)
    if not groups:
        return ""
    length = max(int(length), len(groups))
    alphabet = "".join(groups)
    out = [secrets.choice(g) for g in groups]
    out += [secrets.choice(alphabet) for _ in range(length - len(out))]
    for i in range(len(out) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        out[i], out[j] = out[j], out[i]
    return "".join(out)


COMMON = ["haslo", "password", "qwerty", "123456", "111111", "admin", "polska", "zaq12wsx", "1qaz2wsx", "abc123",
          "iloveyou", "kocham", "zxcvbn", "asdfgh", "letmein", "welcome", "monkey", "dragon"]
LEVELS = [(28, "Bardzo słabe"), (40, "Słabe"), (60, "Średnie"), (80, "Silne"), (math.inf, "Bardzo silne")]


def strength(pw: str) -> tuple[int, str]:
    """Ocena od 1 (bardzo słabe) do 5 (bardzo silne); 0 dla pustego hasła."""
    if not pw:
        return 0, ""
    pool = 0
    if re.search(r"[a-z]", pw):
        pool += 26
    if re.search(r"[A-Z]", pw):
        pool += 26
    if re.search(r"\d", pw):
        pool += 10
    if re.search(r"[^a-zA-Z0-9]", pw):
        pool += 33
    n, uniq = len(pw), len(set(pw))
    bits = math.log2(max(pool, 2)) * n * min(1, uniq / min(n, 10))
    low = norm(pw)
    if any(c in low for c in COMMON):
        bits = min(bits, 24)
    if re.search(r"(0123|1234|2345|3456|4567|5678|6789|abcd|bcde|qwer|asdf|zxcv)", pw, re.I):
        bits -= 12
    if pw.isdigit():
        bits = min(bits, 30)
    for i, (limit, label) in enumerate(LEVELS):
        if bits < limit:
            return i + 1, label
    return 5, LEVELS[-1][1]
