## Pobieranie

- **Sejf.exe**: program dla Windows 10 i 11. Nie wymaga instalacji, wystarczy go uruchomić.
- **Sejf-telefon.html**: wersja przeglądarkowa do otwierania osobistego sejfu na telefonie (bez profili klientów).

Przy pierwszym uruchomieniu Windows może pokazać okno „System Windows ochronił ten komputer”, bo program nie ma płatnego podpisu cyfrowego. Kliknij **Więcej informacji → Uruchom mimo to**.

## Nowości w 3.2: bezpieczeństwo

- **Argon2id** zamiast PBKDF2: zgadywanie hasła kartami graficznymi jest wielokrotnie trudniejsze. Sejf i profile przechodzą na nowy format same przy pierwszym otwarciu. Nowe hasło główne musi mieć co najmniej 10 znaków i ocenę „Silne”.
- **Osobny klucz dla każdej osoby w profilu**: współpracowników dodajesz ich kodem (Ustawienia → Mój kod), bez przekazywania hasła. „Odbierz dostęp” wymienia klucz profilu, więc ta osoba nie otworzy już aktualnej wersji. Dostęp hasłem profilu jest opcjonalny.
- **Dziennik zmian w profilu**: kto i kiedy dodał, zmienił, usunął wpis, skopiował lub wyświetlił hasło, połączył się z urządzeniem.
- **Blokada razem z Windows**: sejf blokuje się przy Win+L i po uśpieniu komputera.

**Ważne:** wszystkie osoby korzystające ze wspólnych profili muszą zaktualizować program do wersji 3.2. Starsze wersje nie otworzą przeniesionych plików.

### 3.2.1

- Poprawka: przy bardzo szybkiej pracy w formularzu wpisu przycisk „Usuń konto” mógł uruchomić się sam.
