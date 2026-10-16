const { chromium } = require('playwright');
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const URL_ = 'file://' + path.resolve(__dirname, '../dist/Sejf.html');
const shots = path.resolve(__dirname, '../test-results'); fs.mkdirSync(shots, { recursive: true });
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 860 }, acceptDownloads: true });
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write']);
  // tryb przeglądarki (bez API plików)
  await ctx.addInitScript(() => { delete window.showOpenFilePicker; delete window.showSaveFilePicker; });
  const page = await ctx.newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message)); page.on('console', m => { if (m.type() === 'error' && !/fonts\.g|ERR_TUNNEL|ERR_NAME|ERR_INTERNET|ERR_PROXY/.test(m.text())) errors.push(m.text()); });
  await page.goto(URL_);
  await page.click('#lk-new');
  await page.fill('#lk-n1', 'krótkie');
  await page.fill('#lk-n2', 'krótkie');
  await page.click('#lk-create-go');
  ok(await page.isVisible('#lk-cerr'), 'odrzuca za krótkie hasło główne');
  await page.fill('#lk-n1', 'Zielony kot je 4 jabłka!');
  await page.fill('#lk-n2', 'Zielony kot je 4 jabłka!');
  await page.click('#lk-create-go');
  await page.waitForSelector('#main:not([hidden])');
  ok(true, 'utworzono sejf');
  await page.screenshot({ path: shots + '/1-empty.png' });

  // nowy wpis + generator
  await page.click('#btn-new');
  await page.fill('#f-title', 'Allegro');
  await page.fill('#f-user', 'jan.kowalski');
  await page.fill('#f-url', 'allegro.pl');
  await page.click('button[title="Wygeneruj hasło"]');
  await page.fill('#g-len', '32'); await page.dispatchEvent('#g-len', 'input');
  const gen = await page.inputValue('#g-out');
  ok(gen.length === 32, 'generator: długość 32 → ' + gen);
  await page.click('#g-use');
  ok(await page.inputValue('#f-pass') === gen, 'generator wstawia hasło do formularza');
  await page.fill('#f-cat', 'Sklepy'); await page.fill('#f-tags', 'zakupy, #2FA');
  await page.click('form.form button[type=submit]');
  await page.waitForTimeout(200); ok((await page.textContent('#detail h2')) === 'Allegro', 'zapisano i pokazano wpis: ' + await page.textContent('#detail h2'));

  // import
  await page.click('#btn-imp');
  await page.setInputFiles('#csv-in', path.join(__dirname, 'fixtures/chrome.csv'));
  await page.waitForFunction(() => /Do dodania/.test(document.querySelector('#i-sum').textContent));
  const sum = await page.textContent('#i-sum'); console.log('     podsumowanie:', sum);
  ok(/Chrome/.test(sum) && /Do dodania: 3 wpisy/.test(sum), 'import rozpoznaje format i pomija duplikaty');
  await page.click('#i-go');
  const S = () => page.evaluate(() => window.__sejf.S.data.entries.map(e => ({ t: e.title, p: e.password, n: e.notes, c: e.category })));
  const ents = await S();
  ok(ents.length === 4, 'po imporcie 4 wpisy');
  ok(ents.find(e => e.t === 'Gmail')?.n.includes('\ndrugą linią — zażółć'), 'wieloliniowa notatka z polskimi znakami');
  ok(ents.find(e => e.t === 'Gmail')?.p === 'Tr0ub4dor,&3', 'hasło z przecinkiem');

  // wyszukiwarka, szczegóły, kopiowanie
  await page.fill('#q', 'zazolc'); 
  ok((await page.$$('.list .row')).length === 1, 'szukanie bez polskich znaków znajduje notatkę');
  await page.fill('#q', '');
  await page.click('.row:has-text("Bank PKO")');
  ok(/Słabe|Bardzo słabe/.test(await page.textContent('#detail .meter')), 'słabe hasło oznaczone');
  await page.click('#detail button[title="Kopiuj hasło"]');
  ok(await page.evaluate(() => navigator.clipboard.readText()) === 'Kot123', 'kopiowanie do schowka');
  ok(/wyczyszczę za 30 s/.test(await page.textContent('#toast')), 'komunikat o czyszczeniu schowka');
  await page.screenshot({ path: shots + '/2-desktop.png' });
  // historia hasła
  await page.click('#detail button[title="Edytuj"]'); await page.fill('#f-pass', 'Nowe-Haslo-2026!'); await page.click('form.form button[type=submit]');
  ok(/Poprzednie hasła \(1\)/.test(await page.textContent('#detail')), 'historia poprzednich haseł');

  // zapis pliku (tryb przeglądarki)
  const [dl] = await Promise.all([page.waitForEvent('download'), page.click('#btn-save')]);
  const file = path.join(shots, 'vault.json'); await dl.saveAs(file);
  const text = fs.readFileSync(file, 'utf8');
  ok(!/Kot123|jan.kowalski|Gmail/.test(text), 'plik nie zawiera jawnych danych');
  // niezależne odszyfrowanie w Node
  const o = JSON.parse(text);
  const key = crypto.pbkdf2Sync(Buffer.from('Zielony kot je 4 jabłka!'.normalize('NFC')), Buffer.from(o.kdf.salt, 'base64'), o.kdf.iterations, 32, 'sha256');
  const raw = Buffer.from(o.data, 'base64');
  const d = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(o.cipher.iv, 'base64'));
  d.setAAD(Buffer.from('sejf-vault/1')); d.setAuthTag(raw.subarray(raw.length - 16));
  const plain = JSON.parse(Buffer.concat([d.update(raw.subarray(0, raw.length - 16)), d.final()]).toString());
  ok(plain.entries.length === 4 && o.kdf.iterations === 600000, 'Node odszyfrowuje plik (AES-256-GCM, PBKDF2 600k)');

  // eksport CSV i reimport
  await page.click('#btn-exp'); await page.check('#e-ack');
  const [dl2] = await Promise.all([page.waitForEvent('download'), page.click('#e-csv')]);
  const csvPath = path.join(shots, 'export.csv'); await dl2.saveAs(csvPath);
  await page.keyboard.press('Escape');

  // telefon
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: shots + '/3a-phone-open-detail.png' });
  await page.click('#detail .back');
  await page.screenshot({ path: shots + '/3b-phone-list.png' });
  await page.click('.row:has-text("Gmail")');
  await page.screenshot({ path: shots + '/3-phone-detail.png' });
  await page.click('#detail .back');
  await page.click('#btn-menu'); await page.screenshot({ path: shots + '/4-phone-side.png' }); await page.mouse.click(370, 500);
  const ov = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  ok(!ov, 'brak poziomego przewijania na telefonie');
  await page.setViewportSize({ width: 1360, height: 860 });

  // blokada i ponowne otwarcie z pliku
  await page.click('#btn-lock');
  ok(await page.evaluate(() => window.__sejf.S.data === null && window.__sejf.S.key === null), 'blokada czyści dane z pamięci');
  const p2 = await ctx.newPage(); p2.on('pageerror', e => errors.push(e.message));
  await p2.goto(URL_);
  await p2.click('#lk-open');
  await p2.setInputFiles('#file-in', file);
  await p2.fill('#lk-pw', 'złe hasło'); await p2.click('#lk-go');
  await p2.waitForSelector('#lk-err:not([hidden])');
  ok(/Nieprawidłowe/.test(await p2.textContent('#lk-err')), 'złe hasło odrzucone');
  await p2.fill('#lk-pw', 'Zielony kot je 4 jabłka!'); await p2.click('#lk-go');
  await p2.waitForSelector('#main:not([hidden])');
  ok((await p2.$$('.list .row')).length === 4, 'otwarto zapisany plik: 4 wpisy');
  await p2.click('#btn-imp'); await p2.setInputFiles('#csv-in', csvPath);
  await p2.waitForFunction(() => /Do dodania/.test(document.querySelector('#i-sum').textContent));
  ok(/Do dodania: 0/.test(await p2.textContent('#i-sum')), 'reimport własnego CSV nie dubluje wpisów');
  await p2.keyboard.press('Escape');
  // generator: wszystkie zestawy znaków obecne, losowość
  const g = await p2.evaluate(() => { const r = []; for (let i = 0; i < 2000; i++) r.push(window.__sejf.generate({ length: 12, lower: true, upper: true, digits: true, symbols: true, noAmb: true })); return r; });
  ok(g.every(x => /[a-z]/.test(x) && /[A-Z]/.test(x) && /\d/.test(x) && /[^a-zA-Z0-9]/.test(x) && !/[Il1O0o|]/.test(x)) && new Set(g).size === 2000, 'generator: każde hasło ma wszystkie rodzaje znaków, bez podobnych');
  // dark
  await p2.emulateMedia({ colorScheme: 'dark' }); await p2.click('.row:has-text("Allegro")'); await p2.screenshot({ path: shots + '/5-dark.png' });
  await p2.click('#btn-gen'); await p2.screenshot({ path: shots + '/6-gen-dark.png' }); await p2.keyboard.press('Escape');
  await p2.click('#btn-lock'); await p2.emulateMedia({ colorScheme: 'light' }); await p2.screenshot({ path: shots + '/7-lock.png' });

  ok(errors.length === 0, 'brak błędów w konsoli ' + errors.join(' | '));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
