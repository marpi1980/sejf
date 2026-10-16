"""Typy wpisów: strony, a także urządzenia i usługi w sieci firmowej.

Każdy wpis ma pola wspólne (nazwa, login, hasło, adres WWW, notatki, kategoria, tagi)
oraz pola zależne od typu, zapisane w słowniku ``extra``.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"  # text | secret | choice | date
    choices: tuple = ()
    hint: str = ""
    mono: bool = True


PROTOCOLS = ("RDP", "SSH", "HTTPS", "HTTP", "Telnet", "SMB", "VNC", "Winbox", "inny")
DEFAULT_PORTS = {"RDP": "3389", "SSH": "22", "HTTPS": "443", "HTTP": "80", "Telnet": "23", "SMB": "445",
                 "VNC": "5900", "Winbox": "8291"}

HOST = Field("host", "Adres IP / nazwa hosta", hint="np. 192.168.1.10 albo srv01.firma.local")
PROTOCOL = Field("protocol", "Protokół", "choice", PROTOCOLS)
PORT = Field("port", "Port", hint="puste = domyślny")
MODEL = Field("model", "Producent i model", mono=False)
SERIAL = Field("serial", "Numer seryjny")
MAC = Field("mac", "Adres MAC")
LOCATION = Field("location", "Lokalizacja", hint="np. serwerownia, szafa RACK 1, U12", mono=False)
FIRMWARE = Field("firmware", "Wersja oprogramowania")
DOMAIN = Field("domain", "Domena")


@dataclass(frozen=True)
class Kind:
    key: str
    label: str        # liczba pojedyncza, w formularzu
    group: str        # liczba mnoga, w drzewie po lewej
    fields: tuple = ()
    protocol: str = ""        # domyślny protokół połączenia
    uses_url: bool = False    # czy pokazywać pole „Adres WWW”
    uses_login: bool = True
    extra_defaults: dict = field(default_factory=dict)


DEVICE = (HOST, PROTOCOL, PORT, MODEL, SERIAL, MAC, LOCATION, FIRMWARE)

KINDS: tuple[Kind, ...] = (
    Kind("web", "Strona / konto internetowe", "Strony i konta", (), uses_url=True),
    Kind("server", "Serwer", "Serwery",
         (HOST, PROTOCOL, PORT, Field("os", "System", "choice", ("Windows Server", "Linux", "VMware ESXi",
                                                                   "Proxmox", "Hyper-V", "inny"), mono=False),
          DOMAIN, Field("role", "Rola", hint="np. kontroler domeny, plików, ERP", mono=False),
          Field("idrac", "Konsola zarządzania (iDRAC / iLO / IPMI)", hint="adres, np. https://10.10.0.110"),
          Field("idrac_user", "Użytkownik konsoli"), Field("idrac_password", "Hasło konsoli", "secret"),
          MODEL, SERIAL, LOCATION), protocol="RDP"),
    Kind("switch", "Przełącznik (switch)", "Przełączniki",
         (*DEVICE, Field("enable", "Hasło enable", "secret"),
          Field("snmp", "SNMP community", "secret"), Field("vlans", "VLAN-y", hint="np. 10 biuro, 20 VoIP, 99 zarządzanie")),
         protocol="SSH"),
    Kind("router", "Router / firewall", "Routery i firewalle",
         (*DEVICE, Field("wan", "Adres publiczny (WAN)"), Field("isp", "Dostawca internetu", mono=False),
          Field("snmp", "SNMP community", "secret")), protocol="HTTPS"),
    Kind("nas", "Dysk sieciowy (NAS)", "Dyski sieciowe",
         (*DEVICE, Field("share", "Udział sieciowy", hint=r"np. \\nas01\dokumenty")), protocol="HTTPS"),
    Kind("vpn", "VPN", "VPN",
         (Field("host", "Serwer VPN", hint="adres lub nazwa serwera"),
          Field("vpn_type", "Rodzaj", "choice", ("OpenVPN", "WireGuard", "IPsec / IKEv2", "L2TP / IPsec", "SSTP",
                                                  "FortiClient", "Cisco AnyConnect", "GlobalProtect", "inny"), mono=False),
          PORT, Field("psk", "Klucz współdzielony (PSK)", "secret"), Field("vpn_network", "Sieć za VPN", hint="np. 192.168.10.0/24"))),
    Kind("printer", "Drukarka / urządzenie wielofunkcyjne", "Drukarki",
         (*DEVICE, Field("scan_to", "Skanowanie do", hint=r"np. \\srv01\skany albo skaner@firma.pl")), protocol="HTTP"),
    Kind("wifi", "Sieć Wi-Fi", "Sieci Wi-Fi",
         (Field("ssid", "Nazwa sieci (SSID)"),
          Field("security", "Zabezpieczenia", "choice", ("WPA2-Personal", "WPA3-Personal", "WPA2/WPA3", "WPA2-Enterprise",
                                                          "Otwarta"), mono=False),
          Field("vlan", "VLAN"), Field("band", "Pasmo", "choice", ("2,4 GHz", "5 GHz", "2,4 + 5 GHz", "6 GHz"), mono=False)),
         uses_login=False),
    Kind("ap", "Punkt dostępowy / kontroler Wi-Fi", "Punkty dostępowe", DEVICE, protocol="HTTPS"),
    Kind("camera", "Kamera / rejestrator (NVR)", "Kamery i rejestratory",
         (*DEVICE, Field("channels", "Liczba kanałów / kamer")), protocol="HTTP"),
    Kind("ups", "Zasilacz UPS", "Zasilacze UPS", (*DEVICE, Field("battery", "Wymiana baterii", "date")), protocol="HTTP"),
    Kind("database", "Baza danych", "Bazy danych",
         (HOST, PORT, Field("engine", "Silnik", "choice", ("SQL Server", "MySQL / MariaDB", "PostgreSQL", "Oracle",
                                                            "Firebird", "SQLite", "inny"), mono=False),
          Field("instance", "Instancja"), Field("database", "Nazwa bazy"))),
    Kind("account", "Konto (AD, Microsoft 365, Google)", "Konta",
         (DOMAIN, Field("tenant", "Dzierżawa / tenant", hint="np. firma.onmicrosoft.com"),
          Field("mfa", "Weryfikacja dwuetapowa", hint="np. aplikacja na telefonie administratora", mono=False)),
         uses_url=True),
    Kind("email", "Skrzynka e-mail", "Skrzynki e-mail",
         (Field("imap", "Serwer poczty przychodzącej (IMAP/POP3)"), Field("smtp", "Serwer poczty wychodzącej (SMTP)")),
         uses_url=True),
    Kind("software", "Program / aplikacja", "Programy", (HOST, PORT, Field("version", "Wersja")), uses_url=True),
    Kind("license", "Licencja / klucz produktu", "Licencje",
         (Field("product", "Produkt", mono=False), Field("license_key", "Klucz licencyjny", "secret"),
          Field("seats", "Liczba stanowisk"), Field("valid_until", "Ważna do", "date", hint="RRRR-MM-DD"),
          Field("invoice", "Faktura / zamówienie", mono=False)), uses_url=True, uses_login=False),
    Kind("device", "Inne urządzenie", "Inne urządzenia", DEVICE, protocol="HTTPS"),
    Kind("note", "Notatka", "Notatki", (), uses_login=False),
)

BY_KEY = {k.key: k for k in KINDS}


def kind_of(entry: dict) -> Kind:
    return BY_KEY.get(entry.get("type") or "web", BY_KEY["web"])


def label_of(entry: dict) -> str:
    return kind_of(entry).label


def has_accounts(kind: Kind) -> bool:
    """Czy wpis może mieć kilka kont (np. administrator, konto serwisowe, konto kopii zapasowych)."""
    return kind.uses_login and kind.key != "wifi"


def secret_fields(kind: Kind) -> list[Field]:
    return [f for f in kind.fields if f.kind == "secret"]


def address_of(entry: dict) -> str:
    """Adres do wyświetlenia na liście: host z portem albo adres strony."""
    ex = entry.get("extra") or {}
    host = (ex.get("host") or "").strip()
    if host:
        port = (ex.get("port") or "").strip()
        return f"{host}:{port}" if port else host
    if ex.get("ssid"):
        return ex["ssid"]
    return (entry.get("url") or "").strip()


def searchable(entry: dict) -> str:
    """Tekst przeszukiwany przez wyszukiwarkę (bez haseł i pól tajnych)."""
    k = kind_of(entry)
    secret = {f.key for f in secret_fields(k)}
    ex = entry.get("extra") or {}
    parts = [entry.get("title", ""), entry.get("username", ""), entry.get("url", ""), entry.get("notes", ""),
             entry.get("category", ""), " ".join(entry.get("tags") or []), k.label, k.group]
    parts += [str(v) for key, v in ex.items() if key not in secret and v]
    for a in entry.get("accounts") or []:
        parts += [a.get("label", ""), a.get("username", "")]
    return " ".join(parts)


def clean_extra(kind: Kind, extra: dict) -> dict:
    """Zostawia tylko niepuste pola; pola spoza typu też zachowuje, żeby zmiana typu nie gubiła danych."""
    return {k: v.strip() if isinstance(v, str) and not any(f.key == k and f.kind == "secret" for f in kind.fields) else v
            for k, v in (extra or {}).items() if v not in ("", None)}
