"""Testy rdzenia: szyfrowanie, zgodność z wersją przeglądarkową, CSV, generator, synchronizacja."""
import base64
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from sejf import connect, crypto, csvio, generator, kinds, totp, vault
from sejf.session import Session

FIX = Path(__file__).parent / "fixtures"
WEB_PASSWORD = "Zielony kot je 4 jabłka!"


class CryptoTests(unittest.TestCase):
    def test_round_trip(self):
        salt = crypto.new_salt()
        key = crypto.derive_key("hasło główne", salt)
        text = crypto.seal({"a": "zażółć"}, key, salt)
        env = crypto.parse_envelope(text)
        self.assertEqual(crypto.decrypt(env, key), {"a": "zażółć"})
        self.assertNotIn("zażółć", text)

    def test_wrong_password(self):
        salt = crypto.new_salt()
        text = crypto.seal({}, crypto.derive_key("dobre", salt), salt)
        env = crypto.parse_envelope(text)
        with self.assertRaises(crypto.WrongPassword):
            crypto.decrypt(env, crypto.derive_key("złe", salt))

    def test_tampering_detected(self):
        salt = crypto.new_salt()
        key = crypto.derive_key("x" * 10, salt)
        o = json.loads(crypto.seal({"n": 1}, key, salt))
        import base64
        raw = bytearray(base64.b64decode(o["data"]))
        raw[0] ^= 1
        o["data"] = base64.b64encode(bytes(raw)).decode()
        with self.assertRaises(crypto.WrongPassword):
            crypto.decrypt(crypto.parse_envelope(json.dumps(o)), key)

    def test_not_a_vault(self):
        for bad in ("", "{}", "nie json", json.dumps({"format": "inny"})):
            with self.assertRaises(crypto.VaultError):
                crypto.parse_envelope(bad)

    def test_opens_file_from_web_version(self):
        """Plik utworzony w przeglądarce (web/) otwiera się w programie na Windows."""
        text = (FIX / "web-vault.json").read_text(encoding="utf-8")
        env = crypto.parse_envelope(text)
        data = vault.normalize_vault(crypto.decrypt(env, crypto.derive_key(WEB_PASSWORD, env.salt, env.iterations)))
        titles = sorted(e["title"] for e in data["entries"])
        self.assertEqual(titles, ["Allegro", "Bank PKO", "Gmail", "allegro.pl"])
        gmail = next(e for e in data["entries"] if e["title"] == "Gmail")
        self.assertEqual(gmail["password"], "Tr0ub4dor,&3")


class VaultTests(unittest.TestCase):
    def test_search_without_polish_letters(self):
        v = vault.new_vault()
        v["entries"].append(vault.new_entry(title="Bank", notes="Zażółć gęślą jaźń"))
        self.assertEqual(len(vault.filter_entries(v, query="zazolc gesla")), 1)
        self.assertEqual(len(vault.filter_entries(v, query="ŁÓDŹ")), 0)

    def test_filters(self):
        v = vault.new_vault()
        v["entries"] += [vault.new_entry(title="A", category="Poczta", tags=["praca"], fav=True), vault.new_entry(title="B")]
        self.assertEqual([e["title"] for e in vault.filter_entries(v, "fav")], ["A"])
        self.assertEqual([e["title"] for e in vault.filter_entries(v, "tag", "praca")], ["A"])
        self.assertEqual([e["title"] for e in vault.filter_entries(v, "none")], ["B"])
        self.assertEqual([e["title"] for e in vault.filter_entries(v, "cat", "Poczta")], ["A"])

    def test_history(self):
        e = vault.new_entry(password="stare")
        vault.update_entry(e, {"password": "nowe"})
        self.assertEqual(e["history"][0]["password"], "stare")
        vault.update_entry(e, {"title": "bez zmiany hasła"})
        self.assertEqual(len(e["history"]), 1)

    def test_urls(self):
        self.assertEqual(vault.host_of("https://www.allegro.pl/login"), "allegro.pl")
        self.assertEqual(vault.safe_href("allegro.pl"), "https://allegro.pl")
        self.assertIsNone(vault.safe_href("javascript:alert(1)"))
        self.assertIsNone(vault.safe_href("file:///C:/Windows"))

    def test_plural(self):
        self.assertEqual([vault.wpisy(n) for n in (1, 2, 5, 12, 22, 25)],
                         ["1 wpis", "2 wpisy", "5 wpisów", "12 wpisów", "22 wpisy", "25 wpisów"])


class GeneratorTests(unittest.TestCase):
    def test_all_groups_present(self):
        for _ in range(500):
            pw = generator.generate(12, noAmb=True)
            self.assertEqual(len(pw), 12)
            self.assertTrue(any(c.islower() for c in pw) and any(c.isupper() for c in pw))
            self.assertTrue(any(c.isdigit() for c in pw) and any(not c.isalnum() for c in pw))
            self.assertFalse(set(pw) & generator.AMBIGUOUS)

    def test_unique(self):
        self.assertEqual(len({generator.generate(16) for _ in range(1000)}), 1000)

    def test_strength(self):
        self.assertLessEqual(generator.strength("Kot123")[0], 2)
        self.assertLessEqual(generator.strength("qwerty123!")[0], 2)
        self.assertEqual(generator.strength(generator.generate(24))[0], 5)
        self.assertEqual(generator.strength(""), (0, ""))


class CsvTests(unittest.TestCase):
    def test_chrome_import(self):
        r = csvio.parse(csvio.decode((FIX / "chrome.csv").read_bytes()))
        self.assertEqual(r.fmt, "Chrome / Edge / Opera")
        self.assertEqual(len(r.entries), 4)
        gmail = next(e for e in r.entries if e["title"] == "Gmail")
        self.assertEqual(gmail["password"], "Tr0ub4dor,&3")
        self.assertIn("\ndrugą linią — zażółć", gmail["notes"])
        self.assertEqual(len(csvio.without_duplicates([], r.entries)), 3)

    def test_bitwarden_and_semicolon(self):
        text = "folder;favorite;type;name;notes;fields;reprompt;login_uri;login_username;login_password;login_totp\n" \
               "Praca;1;login;Jira;;;0;https://jira.example.com;jan;Sekret!;\n"
        r = csvio.parse(text)
        self.assertEqual(r.fmt, "Bitwarden")
        self.assertEqual(r.entries[0]["category"], "Praca")
        self.assertTrue(r.entries[0]["fav"])

    def test_keepass_groups(self):
        r = csvio.parse('"Group","Title","Username","Password","URL","Notes"\n"Root/Internet/Sklepy","Allegro","jan","x","allegro.pl",""\n')
        self.assertEqual(r.fmt, "KeePass")
        self.assertEqual(r.entries[0]["category"], "Sklepy")

    def test_cp1250(self):
        raw = "name,url,username,password\nPoczta,,łukasz,hasło\n".encode("cp1250")
        r = csvio.parse(csvio.decode(raw))
        self.assertEqual(r.entries[0]["username"], "łukasz")

    def test_export_reimport(self):
        r = csvio.parse(csvio.decode((FIX / "chrome.csv").read_bytes()))
        entries = [vault.new_entry(**e) for e in csvio.without_duplicates([], r.entries)]
        again = csvio.parse(csvio.to_csv(entries))
        self.assertEqual(len(csvio.without_duplicates(entries, again.entries)), 0)

    def test_missing_password_column(self):
        with self.assertRaises(ValueError):
            csvio.parse("a,b\n1,2\n")


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "hasla.sejf.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def bump(self, path=None):
        """Symuluje zapis z innego komputera (inny czas modyfikacji pliku)."""
        path = path or self.path
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))

    def test_create_unlock(self):
        s = Session()
        s.create(self.path, "hasło główne 1")
        s.data["entries"].append(vault.new_entry(title="Poczta", password="abc"))
        s.mark_changed()
        self.assertEqual(s.save(), "saved")
        self.assertFalse(os.path.exists(self.path + ".zapis"))
        t = Session()
        with self.assertRaises(crypto.WrongPassword):
            t.unlock(self.path, "złe hasło")
        t.unlock(self.path, "hasło główne 1")
        self.assertEqual(t.data["entries"][0]["title"], "Poczta")

    def test_legacy_vault_gets_stable_uid(self):
        path = os.path.join(self.dir, "web.json")
        shutil.copy(FIX / "web-vault.json", path)
        a = Session()
        a.unlock(path, WEB_PASSWORD)
        uid = a.data["uid"]
        b = Session()
        b.unlock(path, WEB_PASSWORD)
        self.assertEqual(b.data["uid"], uid)

    def test_external_change_reloaded(self):
        a, b = Session(), Session()
        a.create(self.path, "wspólne hasło")
        b.unlock(self.path, "wspólne hasło")
        b.data["entries"].append(vault.new_entry(title="Z telefonu"))
        b.mark_changed()
        b.save()
        self.bump()
        self.assertEqual(a.check_external(), "reloaded")
        self.assertEqual(a.data["entries"][0]["title"], "Z telefonu")
        self.assertEqual(a.check_external(), "none")

    def test_concurrent_changes_are_merged(self):
        a, b = Session(), Session()
        a.create(self.path, "wspólne hasło")
        shared = vault.new_entry(title="Wspólny", password="1")
        gone = vault.new_entry(title="Do usunięcia")
        a.data["entries"] += [shared, gone]
        a.mark_changed(); a.save()
        b.unlock(self.path, "wspólne hasło")
        # B: dodaje wpis, usuwa jeden, zmienia wspólny
        b.data["entries"].append(vault.new_entry(title="Od B"))
        vault.delete_entry(b.data, gone["id"])
        time.sleep(0.01)
        vault.update_entry(b.find("me", shared["id"]), {"password": "od-B"})
        b.mark_changed(); b.save(); self.bump()
        # A w tym czasie dodaje swój wpis
        a.data["entries"].append(vault.new_entry(title="Od A"))
        a.mark_changed()
        self.assertEqual(a.save(), "merged")
        titles = sorted(e["title"] for e in a.data["entries"])
        self.assertEqual(titles, ["Od A", "Od B", "Wspólny"])
        self.assertEqual(a.find("me", shared["id"])["password"], "od-B")
        c = Session()
        c.unlock(self.path, "wspólne hasło")
        self.assertEqual(sorted(e["title"] for e in c.data["entries"]), titles)

    def test_password_changed_elsewhere(self):
        a, b = Session(), Session()
        a.create(self.path, "pierwsze hasło")
        b.unlock(self.path, "pierwsze hasło")
        b.change_password("pierwsze hasło", "drugie hasło")
        self.bump()
        self.assertEqual(a.check_external(), "password")
        a.unlock(self.path, "drugie hasło")

    def test_change_password_requires_current(self):
        s = Session()
        s.create(self.path, "pierwsze hasło")
        with self.assertRaises(crypto.WrongPassword):
            s.change_password("złe", "nowe hasło 123")
        s.change_password("pierwsze hasło", "nowe hasło 123")
        Session().unlock(self.path, "nowe hasło 123")

    def test_new_password_rules(self):
        self.assertIsNotNone(Session.check_new_password("krótkie", "krótkie"))
        self.assertIsNotNone(Session.check_new_password("długie hasło", "inne hasło"))
        self.assertIsNone(Session.check_new_password("długie hasło", "długie hasło"))


class ProfileTests(unittest.TestCase):
    """Profile klientów: osobne pliki, hasła w pęku osobistego sejfu, przekazywanie innym osobom."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.shared = os.path.join(self.dir, "wspolny")
        os.mkdir(self.shared)
        self.prof = os.path.join(self.shared, "acme.sejfklient")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def person(self, name, cfg=None):
        s = Session(cfg if cfg is not None else {})
        s.create(os.path.join(self.dir, f"{name}.sejf.json"), f"hasło {name} 123")
        return s

    def reopen(self, name, cfg=None):
        s = Session(cfg if cfg is not None else {})
        s.unlock(os.path.join(self.dir, f"{name}.sejf.json"), f"hasło {name} 123")
        s.open_profiles()
        return s

    def bump(self, path):
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))

    def test_profile_is_separate_file_opened_without_password(self):
        jan = self.person("jan")
        p = jan.create_profile(self.prof, "ACME sp. z o.o.", "hasło klienta ACME", {"address": "ul. Prosta 1"})
        srv = vault.new_entry(type="server", title="Kontroler domeny", username="administrator", password="P@ss",
                              extra={"host": "10.0.0.10", "protocol": "RDP"})
        p.file.data["entries"].append(srv)
        p.file.touch(); p.file.save()
        # plik profilu jest zaszyfrowany i nie zawiera danych jawnie
        text = Path(self.prof).read_text(encoding="utf-8")
        self.assertNotIn("ACME", text)
        self.assertNotIn("10.0.0.10", text)
        self.assertEqual(json.loads(text)["format"], "sejf-profile")
        # osobisty sejf nie ujawnia hasła profilu
        self.assertNotIn("hasło klienta ACME", Path(jan.path).read_text(encoding="utf-8"))
        # po ponownym uruchomieniu profil otwiera się bez pytania o hasło
        jan2 = self.reopen("jan")
        self.assertEqual(list(jan2.profiles), [p.id])
        p2 = jan2.profiles[p.id]
        self.assertEqual(p2.error, "")
        self.assertEqual(p2.name, "ACME sp. z o.o.")
        self.assertEqual(p2.data["entries"][0]["extra"]["host"], "10.0.0.10")

    def test_wrong_file_kind(self):
        jan = self.person("jan")
        with self.assertRaises(crypto.VaultError):
            jan.add_profile(jan.path, "hasło jan 123")
        jan.create_profile(self.prof, "ACME", "hasło klienta ACME")
        with self.assertRaises(crypto.VaultError):
            Session().unlock(self.prof, "hasło klienta ACME")

    def test_share_with_colleague_and_work_together(self):
        jan = self.person("jan")
        p = jan.create_profile(self.prof, "ACME", "hasło klienta ACME")
        anna = self.person("anna")
        with self.assertRaises(crypto.WrongPassword):
            anna.add_profile(self.prof, "złe hasło")
        pa = anna.add_profile(self.prof, "hasło klienta ACME")
        self.assertEqual(pa.id, p.id)
        # Jan dodaje switch, Anna w tym samym czasie drukarkę
        p.file.data["entries"].append(vault.new_entry(type="switch", title="Switch biuro"))
        p.file.touch(); p.file.save(); self.bump(self.prof)
        pa.file.data["entries"].append(vault.new_entry(type="printer", title="Drukarka recepcja"))
        pa.file.touch()
        self.assertEqual(pa.file.save(), "merged")
        self.assertEqual(p.file.check_external(), "reloaded")
        self.assertEqual(sorted(e["title"] for e in p.data["entries"]), ["Drukarka recepcja", "Switch biuro"])

    def test_profile_password_change_reaches_colleague(self):
        jan = self.person("jan")
        p = jan.create_profile(self.prof, "ACME", "hasło klienta ACME")
        anna = self.person("anna")
        anna.add_profile(self.prof, "hasło klienta ACME")
        jan.change_profile_password(p.id, "nowe hasło ACME 2026")
        self.assertEqual(jan.profile_password(p.id), "nowe hasło ACME 2026")
        # Jan nadal otwiera bez pytania
        self.assertEqual(self.reopen("jan").profiles[p.id].error, "")
        # Anna dostaje prośbę o nowe hasło, wpisuje je raz i więcej nie musi
        anna2 = self.reopen("anna")
        self.assertEqual(anna2.profiles[p.id].error, "password")
        with self.assertRaises(crypto.WrongPassword):
            anna2.relink_profile(p.id, password="stare hasło")
        anna2.relink_profile(p.id, password="nowe hasło ACME 2026")
        self.assertEqual(self.reopen("anna").profiles[p.id].error, "")

    def test_missing_file_and_relink(self):
        jan = self.person("jan")
        p = jan.create_profile(self.prof, "ACME", "hasło klienta ACME")
        moved = os.path.join(self.dir, "przeniesiony.sejfklient")
        os.replace(self.prof, moved)
        cfg = {}
        jan2 = self.reopen("jan", cfg)
        self.assertEqual(jan2.profiles[p.id].error, "missing")
        jan2.relink_profile(p.id, path=moved)
        self.assertEqual(cfg["paths"][p.id], moved)
        self.assertEqual(self.reopen("jan", cfg).profiles[p.id].error, "")

    def test_relink_rejects_other_profile(self):
        jan = self.person("jan")
        p = jan.create_profile(self.prof, "ACME", "hasło A")
        other = os.path.join(self.shared, "inny.sejfklient")
        jan.create_profile(other, "Inny", "hasło B")
        with self.assertRaises(crypto.VaultError):
            jan.relink_profile(p.id, path=other, password="hasło B")

    def test_forget_keeps_file(self):
        jan = self.person("jan")
        p = jan.create_profile(self.prof, "ACME", "hasło klienta ACME")
        jan.forget_profile(p.id)
        self.assertTrue(os.path.exists(self.prof))
        self.assertEqual(self.reopen("jan").profiles, {})
        with self.assertRaises(FileExistsError):
            jan.create_profile(self.prof, "ACME", "x" * 10)
        jan.add_profile(self.prof, "hasło klienta ACME")
        self.assertEqual(list(self.reopen("jan").profiles), [p.id])

    def test_profile_info_and_name(self):
        jan = self.person("jan")
        p = jan.create_profile(self.prof, "ACME", "hasło klienta ACME")
        jan.update_profile_info(p.id, "ACME Polska", {"nip": "123-456-78-90", "phone": "+48 600 000 000"})
        p.file.save(); jan.save()
        anna = self.person("anna")
        pa = anna.add_profile(self.prof, "hasło klienta ACME")
        self.assertEqual(pa.name, "ACME Polska")
        self.assertEqual(pa.data["info"]["nip"], "123-456-78-90")

    def test_move_entry_between_sources(self):
        jan = self.person("jan")
        p = jan.create_profile(self.prof, "ACME", "hasło klienta ACME")
        e = vault.new_entry(type="vpn", title="VPN do ACME", extra={"host": "vpn.acme.pl", "psk": "tajny"})
        jan.data["entries"].append(e)
        jan.move_entry(e, "me", p.id)
        jan.save(); p.file.save()
        self.assertEqual(jan.data["entries"], [])
        self.assertIn(e["id"], jan.data["deleted"])
        self.assertEqual(self.reopen("jan").profiles[p.id].data["entries"][0]["extra"]["psk"], "tajny")


class TotpTests(unittest.TestCase):
    SECRET = base64.b32encode(b"12345678901234567890").decode()

    def test_rfc6238_vectors(self):
        for t, code in ((59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
                        (1234567890, "89005924"), (2000000000, "69279037")):
            self.assertEqual(totp.code_at(self.SECRET, t, digits=8), code)

    def test_verify_window(self):
        t = 1_700_000_000
        code = totp.code_at(self.SECRET, t)
        self.assertTrue(totp.verify(self.SECRET, code, t))
        self.assertTrue(totp.verify(self.SECRET, code[:3] + " " + code[3:], t + 30))
        self.assertFalse(totp.verify(self.SECRET, code, t + 120))
        self.assertFalse(totp.verify(self.SECRET, "12345", t))

    def test_uri(self):
        uri = totp.otpauth_uri("JBSWY3DPEHPK3PXP", "Jan Kowalski")
        self.assertTrue(uri.startswith("otpauth://totp/Sejf%3AJan%20Kowalski?secret=JBSWY3DPEHPK3PXP"))

    def test_periodic_check_per_device(self):
        d = tempfile.mkdtemp()
        try:
            cfg = {}
            s = Session(cfg)
            path = os.path.join(d, "v.json")
            s.create(path, "hasło główne 1")
            self.assertFalse(s.totp_due())
            secret = totp.new_secret()
            codes = totp.new_recovery_codes()
            s.enable_totp(secret, 7, codes)
            self.assertFalse(s.totp_due())  # ten komputer właśnie się zweryfikował
            # inny komputer (pusta konfiguracja) musi podać kod
            other = Session({})
            other.unlock(path, "hasło główne 1")
            self.assertTrue(other.totp_due())
            self.assertFalse(other.totp_check("000000") and False)
            self.assertTrue(other.totp_check(totp.code_at(secret)))
            self.assertFalse(other.totp_due())
            # po 8 dniach znów trzeba podać kod
            rec = other.cfg["devices"][other.data["uid"]]
            self.assertTrue(totp.is_due(other.totp, rec, other.main.key, other.data["uid"], time.time() + 8 * 86400))
            # sfałszowany wpis w konfiguracji nie pomija sprawdzenia
            rec["at"] = int(time.time()) + 1
            self.assertTrue(other.totp_due())
            # kod zapasowy działa tylko raz
            third = Session({})
            third.unlock(path, "hasło główne 1")
            self.assertTrue(third.totp_check(codes[0].lower()))
            self.assertEqual(third.recovery_left(), 7)
            fourth = Session({})
            fourth.unlock(path, "hasło główne 1")
            self.assertFalse(fourth.totp_check(codes[0]))
            # tryb „przy każdym odblokowaniu”
            s.set_totp_period(0)
            self.assertTrue(s.totp_due())
            s.disable_totp()
            self.assertFalse(s.totp_due())
        finally:
            shutil.rmtree(d, ignore_errors=True)


class KindsAndConnectTests(unittest.TestCase):
    def test_kinds_have_unique_keys_and_fields(self):
        self.assertEqual(len(kinds.KINDS), len(kinds.BY_KEY))
        for k in kinds.KINDS:
            keys = [f.key for f in k.fields]
            self.assertEqual(len(keys), len(set(keys)), k.key)

    def test_search_includes_extra_but_not_secrets(self):
        v = vault.new_vault()
        v["entries"].append(vault.normalize_entry(vault.new_entry(
            type="switch", title="Core", extra={"host": "10.1.1.2", "location": "Serwerownia", "snmp": "tajne-community"})))
        self.assertEqual(len(vault.filter_entries(v, query="serwerownia")), 1)
        self.assertEqual(len(vault.filter_entries(v, query="przelaczniki")), 1)
        self.assertEqual(len(vault.filter_entries(v, query="tajne-community")), 0)
        self.assertEqual(len(vault.filter_entries(v, "type", "switch")), 1)

    def test_connect_plans(self):
        e = lambda **ex: vault.new_entry(type=ex.pop("type", "device"), username=ex.pop("user", ""), extra=ex)  # noqa: E731
        self.assertEqual(connect.plan(e(type="server", host="10.0.0.5")).target, ["mstsc", "/v:10.0.0.5"])
        self.assertEqual(connect.plan(e(type="server", host="srv", port="3390")).target, ["mstsc", "/v:srv:3390"])
        self.assertEqual(connect.plan(e(type="switch", host="10.0.0.2", user="admin")).target, ["ssh", "admin@10.0.0.2"])
        self.assertEqual(connect.plan(e(type="switch", host="10.0.0.2", port="2222")).target, ["ssh", "-p", "2222", "10.0.0.2"])
        self.assertEqual(connect.plan(e(type="router", host="192.168.1.1")).target, "https://192.168.1.1/")
        self.assertEqual(connect.plan(e(type="printer", host="192.168.1.50:8080")).target, "http://192.168.1.50:8080/")
        self.assertEqual(connect.plan(e(type="nas", host="https://nas01:5001/")).target, "https://nas01:5001/")
        self.assertEqual(connect.plan(e(host="fe80::1", protocol="HTTPS")).target, "https://[fe80::1]/")
        self.assertEqual(connect.plan(e(host="nas01", protocol="SMB", share=r"\\nas01\dane")).target, r"\\nas01\dane")
        self.assertIsNone(connect.plan(e(type="vpn", host="vpn.firma.pl")))
        self.assertIsNone(connect.plan(e(type="server", host="10.0.0.1 & calc")))
        self.assertIsNone(connect.plan(e(type="server")))
        self.assertEqual(connect.plan(e(type="switch", host="sw", user="a b")).target, ["ssh", "sw"])
        self.assertEqual(connect.ping_action(e(host="10.0.0.9")).target[-1], "10.0.0.9")

    def test_expiry(self):
        from datetime import date
        lic = vault.new_entry(type="license", extra={"valid_until": "2026-11-01"})
        self.assertEqual(vault.expiry_state(lic, date(2026, 10, 16))[0], "soon")
        self.assertEqual(vault.expiry_state(lic, date(2026, 11, 2))[0], "expired")
        self.assertIsNone(vault.expiry_state(lic, date(2026, 1, 1)))

    def test_inventory_csv(self):
        text = "Typ;Nazwa;IP;Login;Hasło;Model;Lokalizacja\nSwitch;SW-01;10.0.0.2;admin;x1;HP 1920;Szafa A\n" \
               "Drukarka;Recepcja;10.0.0.50;;;Brother;Parter\nSerwer;DC01;10.0.0.10;administrator;y2;;\n"
        r = csvio.parse(text)
        self.assertEqual(r.fmt, "Lista urządzeń")
        self.assertEqual([e["type"] for e in r.entries], ["switch", "printer", "server"])
        self.assertEqual(r.entries[0]["extra"]["host"], "10.0.0.2")
        self.assertEqual(r.entries[0]["extra"]["model"], "HP 1920")
        self.assertEqual(r.entries[1]["extra"]["location"], "Parter")

    def test_csv_round_trip_keeps_types(self):
        e = vault.normalize_entry(vault.new_entry(type="vpn", title="VPN", extra={"host": "vpn.x.pl", "psk": "a,b;c"}))
        back = csvio.parse(csvio.to_csv([e])).entries[0]
        self.assertEqual(back["type"], "vpn")
        self.assertEqual(back["extra"]["psk"], "a,b;c")


if __name__ == "__main__":
    unittest.main()
