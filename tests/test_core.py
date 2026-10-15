"""Testy rdzenia: szyfrowanie, zgodność z wersją przeglądarkową, CSV, generator, synchronizacja."""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from sejf import crypto, csvio, generator, vault
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

    def _bump_mtime(self):
        st = os.stat(self.path)
        os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))

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

    def test_external_change_reloaded(self):
        a, b = Session(), Session()
        a.create(self.path, "wspólne hasło")
        b.unlock(self.path, "wspólne hasło")
        b.data["entries"].append(vault.new_entry(title="Z telefonu"))
        b.mark_changed()
        b.save()
        self._bump_mtime()
        self.assertEqual(a.check_external(), "reloaded")
        self.assertEqual(a.data["entries"][0]["title"], "Z telefonu")
        self.assertEqual(a.check_external(), "none")

    def test_conflict(self):
        a, b = Session(), Session()
        a.create(self.path, "wspólne hasło")
        b.unlock(self.path, "wspólne hasło")
        b.mark_changed(); b.save(); self._bump_mtime()
        a.data["entries"].append(vault.new_entry(title="Lokalnie"))
        a.mark_changed()
        self.assertEqual(a.check_external(), "conflict")
        self.assertEqual(a.save(), "conflict")
        self.assertEqual(a.save(force=True), "saved")

    def test_password_changed_elsewhere(self):
        a, b = Session(), Session()
        a.create(self.path, "pierwsze hasło")
        b.unlock(self.path, "pierwsze hasło")
        b.change_password("pierwsze hasło", "drugie hasło")
        self._bump_mtime()
        self.assertEqual(a.check_external(), "relock")
        self.assertFalse(a.unlocked)
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


if __name__ == "__main__":
    unittest.main()
