# Sejf

Menedżer haseł dla Windows dla osób, które obsługują sieci i komputery w firmach. Obok własnych haseł trzymasz w nim **profile klientów**: dane do serwerów, switchy, routerów, dysków sieciowych, VPN, drukarek i innych urządzeń w sieci. Każdy profil to osobny zaszyfrowany plik, który możesz przekazać współpracownikowi albo trzymać we wspólnym folderze zespołu.

Program nie łączy się z żadnym serwerem i nie wysyła nigdzie Twoich danych.

![Profil klienta w programie Sejf](docs/zrzut-klient.png)

## Pobieranie

Najnowszy **Sejf.exe** znajdziesz w zakładce [Releases](https://github.com/marpi1980/sejf/releases/latest). Program nie wymaga instalacji: pobierz plik, umieść go np. w `C:\Programy\Sejf` i uruchom.

Przy pierwszym uruchomieniu Windows może pokazać okno „System Windows ochronił ten komputer”, bo program nie ma płatnego podpisu cyfrowego. Kliknij **Więcej informacji → Uruchom mimo to**. Każdy plik `.exe` w wydaniach jest budowany automatycznie z kodu w tym repozytorium przez GitHub Actions.

## Jak to działa

```
 Twój sejf (hasla.sejf.json)          Wspólny folder zespołu
 hasło główne + Google Authenticator   ┌──────────────────────┐
 ┌─────────────────────────────┐       │ ACME.sejfklient      │◄── Ty
 │ Moje hasła                  │       │ Biuro Rachunkowe.…   │◄── Ty, Anna
 │ Hasła do profili klientów ──┼──────►│ Przychodnia.…        │◄── Anna
 └─────────────────────────────┘       └──────────────────────┘
```

- **Osobisty sejf** chroni hasło główne. Są w nim Twoje własne hasła oraz hasła do profili klientów.
- **Profil klienta** to osobny plik `.sejfklient` z własnym hasłem. Gdy dodasz profil, program zapisze jego hasło w Twoim sejfie, więc przy kolejnych uruchomieniach profil otwiera się sam.
- **Przekazanie profilu**: druga osoba dostaje plik (albo dostęp do wspólnego folderu) i hasło profilu. W swoim programie wybiera **＋ Klient → Dodaj profil z pliku** i raz wpisuje hasło.
- **Praca zespołowa**: gdy kilka osób pracuje na tym samym pliku we wspólnym folderze, program łączy zmiany. Wpis dodany przez Annę i wpis dodany przez Ciebie zostaną oba, a przy zmianie tego samego wpisu wygrywa nowsza zmiana.
- **Odebranie dostępu**: zmień hasło profilu (**Zmień hasło profilu…**). Osoby, które go używają, zostaną poproszone o nowe hasło. Kto wcześniej skopiował plik, nadal otworzy tę starą kopię starym hasłem, dlatego przy odejściu pracownika zmień też hasła do samych urządzeń.

## Co potrafi

**Typy wpisów** z polami dopasowanymi do rodzaju sprzętu i usług:

| Typ | Pola dodatkowe |
|---|---|
| Serwer | adres IP, protokół (RDP, SSH…), port, system, domena, rola, konsola iDRAC / iLO, model, numer seryjny, lokalizacja |
| Przełącznik (switch) | adres, protokół, port, model, numer seryjny, MAC, lokalizacja, firmware, hasło enable, SNMP community, VLAN-y |
| Router / firewall | jak wyżej oraz adres publiczny WAN i dostawca internetu |
| Dysk sieciowy (NAS) | jak wyżej oraz udział sieciowy `\\nas\udział` |
| VPN | serwer, rodzaj (OpenVPN, WireGuard, IPsec, FortiClient…), port, klucz PSK, sieć za VPN |
| Drukarka, punkt dostępowy, kamera / NVR, UPS, inne urządzenie | adres, protokół, model, numer seryjny, MAC, lokalizacja i pola typowe dla urządzenia |
| Sieć Wi-Fi | SSID, zabezpieczenia, hasło, VLAN, pasmo |
| Baza danych | adres, port, silnik, instancja, nazwa bazy |
| Konto (AD, Microsoft 365, Google), skrzynka e-mail, program | domena, tenant, serwery IMAP/SMTP, wersja |
| Licencja / klucz produktu | produkt, klucz, liczba stanowisk, data ważności (z ostrzeżeniem przed wygaśnięciem) |
| Strona / konto internetowe, notatka | |

Pola tajne (hasło enable, SNMP, PSK, klucze licencyjne) są ukryte i kopiowane tak samo bezpiecznie jak hasła.

**Połączenie jednym kliknięciem**: przycisk **Pulpit zdalny (RDP)**, **Terminal SSH**, **Otwórz w przeglądarce** albo **Otwórz udział sieciowy**, zależnie od protokołu. Hasło trafia wtedy do schowka, wystarczy je wkleić. Przycisk **Ping** otwiera `ping -t` do urządzenia.

<p>
<img src="docs/zrzut-switch.png" alt="Przełącznik z hasłem enable i SNMP" width="420">
<img src="docs/zrzut-udostepnij.png" alt="Udostępnianie profilu" width="300">
</p>

Pozostałe funkcje:

- **Wyszukiwarka** przeszukuje nazwy, adresy IP, loginy, modele, lokalizacje i notatki we wszystkich profilach naraz, także bez polskich znaków („serwerownia”, „10.10.0”, „aruba”).
- **Karta klienta**: pełna nazwa firmy, NIP, adres, osoba kontaktowa, telefon, umowa serwisowa i notatki.
- **Import list urządzeń** z arkusza CSV z kolumnami takimi jak Typ, Nazwa, IP, Login, Hasło, Model, Lokalizacja (także ze średnikami i z polskiego Excela) oraz import haseł z Chrome, Edge, Firefox, Bitwarden, KeePass i 1Password.
- **Weryfikacja dwuetapowa** kodem z Google Authenticator (lub Microsoft Authenticator, Authy). Program prosi o kod na każdym nowym komputerze i potem okresowo: przy każdym odblokowaniu, raz dziennie, raz w tygodniu, co 2 tygodnie albo co 30 dni. Do tego 8 jednorazowych kodów zapasowych.
- **Generator haseł** oraz ocena siły hasła i ostrzeżenie o tym samym haśle w kilku miejscach.
- **Schowek z auto-czyszczeniem**. Skopiowane hasła nie trafiają do historii schowka Windows (Win+V) ani do schowka w chmurze.
- **Historia poprzednich haseł** każdego wpisu, **automatyczna blokada**, jasny i ciemny motyw.

<img src="docs/zrzut-2fa.png" alt="Konfiguracja Google Authenticator" width="420">

## Pierwsze uruchomienie

1. Kliknij **Utwórz nowy sejf…**, ustaw hasło główne i zapisz plik sejfu.
2. Dodaj klienta: **＋ Klient → Nowy profil klienta…**. Program zaproponuje losowe hasło profilu i miejsce pliku obok Twojego sejfu. Jeśli profil ma być wspólny, wybierz folder zespołu.
3. W profilu dodawaj wpisy przyciskiem **＋ Nowy wpis**, wybierając typ (serwer, switch, VPN…).
4. W **Ustawieniach** włącz weryfikację dwuetapową i zapisz kody zapasowe.

Skróty klawiszowe: **Ctrl+N** nowy wpis, **Ctrl+F** wyszukiwanie, **Ctrl+L** blokada, **Ctrl+S** zapis edytowanego wpisu. Na liście: **dwuklik** lub **Ctrl+C** kopiuje hasło, **Ctrl+B** kopiuje login, **Delete** usuwa wpis, prawy przycisk myszy otwiera menu (także na profilu w drzewie po lewej).

> **Hasła głównego nie da się odzyskać.** Jeśli je zapomnisz, stracisz dostęp do swoich haseł i do zapamiętanych haseł profili (same profile otworzysz ponownie, jeśli znasz ich hasła). Zrób zaszyfrowaną kopię zapasową sejfu (**Eksport… → Zapisz kopię…**) i trzymaj ją poza chmurą.

## Bezpieczeństwo

| Element | Rozwiązanie |
|---|---|
| Szyfrowanie | AES-256-GCM, losowy 12-bajtowy IV przy każdym zapisie; osobny klucz dla sejfu i dla każdego profilu |
| Klucz | PBKDF2-HMAC-SHA256, 600 000 iteracji, losowa 16-bajtowa sól na plik |
| Hasła profili | Zapisane wyłącznie wewnątrz zaszyfrowanego osobistego sejfu |
| Integralność | Tag uwierzytelniający GCM wykrywa każdą zmianę pliku i złe hasło; pliku profilu nie da się otworzyć jako sejfu i odwrotnie |
| Zapis | Najpierw do pliku tymczasowego, potem podmiana, więc przerwany zapis nie uszkodzi pliku |
| Weryfikacja dwuetapowa | TOTP (RFC 6238); zapamiętanie komputera podpisane kluczem sejfu, więc nie da się go podrobić edycją pliku ustawień |
| Schowek | Hasła wykluczone z historii schowka i synchronizacji w chmurze; czyszczenie tylko wtedy, gdy w schowku nadal jest to samo hasło |
| Połączenia | Adresy i loginy sprawdzane przed uruchomieniem RDP/SSH, żeby wpis nie mógł wykonać innego polecenia |
| Sieć | Program nie wykonuje żadnych połączeń sieciowych |

Ograniczenia, o których warto wiedzieć:

- **Weryfikacja dwuetapowa chroni dostęp przez program**, a nie sam plik. Nie zatrzyma kogoś, kto ma plik sejfu, zna hasło główne i odszyfruje plik własnym narzędziem albo wersją przeglądarkową. Dlatego hasło główne nadal jest najważniejszą ochroną.
- Python nie pozwala na pewne wymazanie danych z pamięci. Po zablokowaniu program usuwa odwołania do kluczy i haseł, ale ich kopie mogą przez chwilę pozostać w pamięci procesu.
- To projekt hobbystyczny bez zewnętrznego audytu bezpieczeństwa.

### Format plików

Oba rodzaje plików to JSON, który można odszyfrować standardowymi narzędziami:

```json
{
 "format": "sejf-vault",
 "version": 1,
 "kdf": { "name": "PBKDF2-SHA256", "iterations": 600000, "salt": "<base64>" },
 "cipher": { "name": "AES-256-GCM", "iv": "<base64>" },
 "data": "<base64: szyfrogram + 16-bajtowy tag>"
}
```

Osobisty sejf ma `"format": "sejf-vault"` i dane dodatkowe (AAD) `sejf-vault/1`. Profil klienta ma `"format": "sejf-profile"` i AAD `sejf-profile/1`. Hasła są normalizowane do postaci Unicode NFC. Nazwa klienta i wszystkie dane są tylko w zaszyfrowanej części.

## Telefon

Wersja przeglądarkowa z folderu [`web/`](web/) (w wydaniach jako `Sejf-telefon.html`) otwiera osobisty sejf, czyli Twoje własne hasła. Profili klientów na telefonie na razie nie obsługuje. Przeglądarki na telefonach nie otwierają lokalnych plików HTML, więc tę wersję trzeba udostępnić pod adresem internetowym, np. przez GitHub Pages.

## Rozwój

```
sejf/            kod programu
  crypto.py      szyfrowanie i format plików
  session.py     otwarte pliki: zapis, łączenie zmian, profile klientów, 2FA
  vault.py       wpisy, kategorie, tagi, wyszukiwanie, łączenie wersji
  kinds.py       typy wpisów (serwer, switch, VPN…) i ich pola
  connect.py     RDP, SSH, przeglądarka, udział sieciowy, ping
  totp.py        kody z aplikacji Authenticator i kody zapasowe
  csvio.py       import i eksport CSV
  generator.py   generator i ocena siły haseł
  clipboard.py   schowek wykluczony z historii Windows
  gui.py         główna klasa programu
  views.py       ekran blokady, drzewo klientów, lista, szczegóły, formularz
  dialogs.py     okna dialogowe
tests/           testy rdzenia i interfejsu
web/             wersja przeglądarkowa (telefon)
Sejf.pyw         punkt wejścia
```

Uruchomienie z kodu (Python 3.12):

```sh
pip install -r requirements.txt
python Sejf.pyw
```

Testy i budowa pliku `.exe`:

```sh
pip install -r requirements-dev.txt
python -m unittest tests.test_core tests.test_gui
pyinstaller --onefile --windowed --name Sejf --icon assets/sejf.ico --collect-data sv_ttk --hidden-import darkdetect --hidden-import segno Sejf.pyw
```

Przy każdej zmianie GitHub Actions uruchamia testy na Linuksie i Windows, buduje `Sejf.exe` i sprawdza, czy zbudowany program działa. Test okien przechodzi całą ścieżkę: od założenia sejfu, przez profil klienta, wspólną pracę dwóch osób i weryfikację dwuetapową, po zmianę hasła profilu przez inną osobę. Nowe wydanie powstaje samo, gdy na gałąź `main` trafi nowy numer wersji w `sejf/__init__.py`.

## Licencja

MIT
