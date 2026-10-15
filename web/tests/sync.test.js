const { chromium } = require('playwright'); const path = require('path');
const ok = (c, m) => { console.log(c ? 'ok  ' : 'FAIL', m); if (!c) process.exitCode = 1; };
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext();
  await ctx.addInitScript(() => {
    // udawany plik w folderze Dysku Google
    const F = window.__F = { text: '', mod: 0 };
    const handle = { name: 'hasla.sejf.json', kind: 'file',
      queryPermission: async () => 'granted', requestPermission: async () => 'granted',
      getFile: async () => ({ lastModified: F.mod, text: async () => F.text }),
      createWritable: async () => { let buf = ''; return { write: async t => { buf += t; }, close: async () => { F.text = buf; F.mod = Date.now() + Math.random(); } }; } };
    window.showSaveFilePicker = async () => handle; window.showOpenFilePicker = async () => [handle];
  });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.goto('file://' + path.resolve(__dirname, '../dist/Sejf.html'));
  ok(await p.evaluate(() => window.__sejf.S.fs), 'tryb pliku (Windows) wykryty');
  await p.click('#lk-new'); await p.fill('#lk-n1', 'Haslo glowne 123!'); await p.fill('#lk-n2', 'Haslo glowne 123!'); await p.click('#lk-create-go');
  await p.waitForSelector('#main:not([hidden])');
  ok(await p.evaluate(() => JSON.parse(__F.text).format === 'sejf-vault'), 'plik zapisany od razu po utworzeniu');
  await p.click('#btn-new'); await p.fill('#f-title', 'Poczta'); await p.fill('#f-pass', 'abc'); await p.click('form.form button[type=submit]');
  await p.waitForTimeout(800);
  ok(/zapisano automatycznie/.test(await p.textContent('#save-text')), 'autozapis: ' + await p.textContent('#save-text'));
  ok(await p.isHidden('#btn-save'), 'brak przycisku pobierania w trybie pliku');
  // zmiana z telefonu: ten sam klucz, nowy wpis
  await p.evaluate(async () => { const S = __sejf.S; const d = structuredClone(S.data); d.entries.push({ id: 'x', title: 'Z telefonu', password: 'p', tags: [] }); __F.text = await __sejf.seal(d, S.key, S.salt, S.iter); __F.mod += 5000; });
  await p.evaluate(() => window.dispatchEvent(new Event('focus'))); await p.waitForTimeout(400);
  ok((await p.$$('.list .row')).length === 2 && /innego urządzenia/.test(await p.textContent('#toast')), 'wczytano zmiany z innego urządzenia');
  // konflikt
  await p.evaluate(async () => { __F.mod += 5000; });
  await p.click('.row:has-text("Poczta")'); await p.click('#detail button[title="Dodaj do ulubionych"]'); await p.waitForTimeout(800);
  ok(await p.isVisible('#conflict'), 'wykryto konflikt wersji');
  await p.click('#conflict .btn.primary'); await p.waitForTimeout(500);
  ok(await p.isHidden('#conflict') && /zapisano/.test(await p.textContent('#save-text')), 'zachowano moją wersję');
  await p.click('#btn-lock'); await p.fill('#lk-pw', 'Haslo glowne 123!'); await p.click('#lk-go'); await p.waitForSelector('#main:not([hidden])');
  ok((await p.$$('.list .row')).length === 2, 'ponowne odblokowanie z pliku');
  ok(!errs.length, 'brak błędów ' + errs.join('|'));
  await b.close();
})();
