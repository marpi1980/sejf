/* Argon2id (RFC 9106) w czystym JavaScripcie, bez zależności.
   Liczby 64-bitowe są przechowywane jako pary 32-bitowe (lo, hi) w Uint32Array.
   Używane przez wersję przeglądarkową do otwierania plików zaszyfrowanych w programie na Windows. */
const Argon2 = (() => {
  'use strict';
  // ---------- BLAKE2b ----------
  const IV = new Uint32Array([
    0xf3bcc908, 0x6a09e667, 0x84caa73b, 0xbb67ae85, 0xfe94f82b, 0x3c6ef372, 0x5f1d36f1, 0xa54ff53a,
    0xade682d1, 0x510e527f, 0x2b3e6c1f, 0x9b05688c, 0xfb41bd6b, 0x1f83d9ab, 0x137e2179, 0x5be0cd19]);
  const SIGMA = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
    [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4], [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
    [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13], [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
    [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11], [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
    [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5], [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3]];
  const v = new Uint32Array(32), m = new Uint32Array(32);

  function bG(a, b, c, d, x, y) {
    // v[a] = v[a] + v[b] + m[x]
    let lo = v[a] + v[b], hi = v[a + 1] + v[b + 1] + (lo / 0x100000000 >>> 0);
    lo = (lo >>> 0) + m[x]; hi = hi + m[x + 1] + (lo / 0x100000000 >>> 0);
    v[a] = lo; v[a + 1] = hi;
    // v[d] = rotr64(v[d] ^ v[a], 32)
    let dl = v[d] ^ v[a], dh = v[d + 1] ^ v[a + 1];
    v[d] = dh; v[d + 1] = dl;
    // v[c] += v[d]
    lo = v[c] + v[d]; v[c + 1] = v[c + 1] + v[d + 1] + (lo / 0x100000000 >>> 0); v[c] = lo;
    // v[b] = rotr64(v[b] ^ v[c], 24)
    let bl = v[b] ^ v[c], bh = v[b + 1] ^ v[c + 1];
    v[b] = (bl >>> 24) | (bh << 8); v[b + 1] = (bh >>> 24) | (bl << 8);
    // v[a] = v[a] + v[b] + m[y]
    lo = v[a] + v[b]; hi = v[a + 1] + v[b + 1] + (lo / 0x100000000 >>> 0);
    lo = (lo >>> 0) + m[y]; hi = hi + m[y + 1] + (lo / 0x100000000 >>> 0);
    v[a] = lo; v[a + 1] = hi;
    // v[d] = rotr64(v[d] ^ v[a], 16)
    dl = v[d] ^ v[a]; dh = v[d + 1] ^ v[a + 1];
    v[d] = (dl >>> 16) | (dh << 16); v[d + 1] = (dh >>> 16) | (dl << 16);
    // v[c] += v[d]
    lo = v[c] + v[d]; v[c + 1] = v[c + 1] + v[d + 1] + (lo / 0x100000000 >>> 0); v[c] = lo;
    // v[b] = rotr64(v[b] ^ v[c], 63)
    bl = v[b] ^ v[c]; bh = v[b + 1] ^ v[c + 1];
    v[b] = (bh >>> 31) | (bl << 1); v[b + 1] = (bl >>> 31) | (bh << 1);
  }
  function compress(h, block, t, last) {
    for (let i = 0; i < 16; i++) { v[i] = h[i]; v[i + 16] = IV[i]; }
    v[24] ^= t; v[25] ^= (t / 0x100000000) >>> 0;
    if (last) { v[28] = ~v[28]; v[29] = ~v[29]; }
    for (let i = 0; i < 32; i++) m[i] = block[i * 4] | (block[i * 4 + 1] << 8) | (block[i * 4 + 2] << 16) | (block[i * 4 + 3] << 24);
    for (let r = 0; r < 12; r++) {
      const s = SIGMA[r];
      bG(0, 8, 16, 24, s[0] * 2, s[1] * 2); bG(2, 10, 18, 26, s[2] * 2, s[3] * 2);
      bG(4, 12, 20, 28, s[4] * 2, s[5] * 2); bG(6, 14, 22, 30, s[6] * 2, s[7] * 2);
      bG(0, 10, 20, 30, s[8] * 2, s[9] * 2); bG(2, 12, 22, 24, s[10] * 2, s[11] * 2);
      bG(4, 14, 16, 26, s[12] * 2, s[13] * 2); bG(6, 8, 18, 28, s[14] * 2, s[15] * 2);
    }
    for (let i = 0; i < 16; i++) h[i] ^= v[i] ^ v[i + 16];
  }
  function blake2b(input, outLen) {
    const h = new Uint32Array(IV);
    h[0] ^= 0x01010000 ^ outLen;
    const block = new Uint8Array(128);
    let t = 0, pos = 0;
    const n = input.length;
    if (n === 0) { compress(h, block, 0, true); }
    while (pos < n) {
      const take = Math.min(128, n - pos);
      block.fill(0);
      block.set(input.subarray(pos, pos + take));
      pos += take; t += take;
      compress(h, block, t, pos >= n);
    }
    const out = new Uint8Array(outLen);
    for (let i = 0; i < outLen; i++) out[i] = h[i >> 2] >>> (8 * (i & 3));
    return out;
  }
  const le32 = n => new Uint8Array([n & 255, (n >>> 8) & 255, (n >>> 16) & 255, (n >>> 24) & 255]);
  function concat(parts) {
    const len = parts.reduce((a, p) => a + p.length, 0), out = new Uint8Array(len);
    let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
    return out;
  }
  // H' – BLAKE2b o zmiennej długości wyjścia
  function hPrime(input, outLen) {
    const inp = concat([le32(outLen), input]);
    if (outLen <= 64) return blake2b(inp, outLen);
    const out = new Uint8Array(outLen);
    let vv = blake2b(inp, 64);
    out.set(vv.subarray(0, 32), 0);
    let o = 32;
    const r = Math.ceil(outLen / 32) - 2;
    for (let i = 1; i < r; i++) { vv = blake2b(vv, 64); out.set(vv.subarray(0, 32), o); o += 32; }
    vv = blake2b(vv, outLen - 32 * r);
    out.set(vv, o);
    return out;
  }

  // ---------- permutacja P (BlaMka) na bloku 1 KiB ----------
  // blok = 128 słów 64-bitowych = 256 × uint32
  function GB(B, a, b, c, d) {
    // a = a + b + 2*lo(a)*lo(b)
    fBlaMka(B, a, b); rot(B, d, a, 32);
    fBlaMka(B, c, d); rot(B, b, c, 24);
    fBlaMka(B, a, b); rot(B, d, a, 16);
    fBlaMka(B, c, d); rot(B, b, c, 63);
  }
  function fBlaMka(B, x, y) {
    const xl = B[x], yl = B[y];
    // 2 * xl * yl jako 64 bity
    const xlh = xl >>> 16, xll = xl & 0xffff, ylh = yl >>> 16, yll = yl & 0xffff;
    const ll = xll * yll, lh = xll * ylh, hl = xlh * yll, hh = xlh * ylh;
    let lo = ll + ((lh & 0xffff) << 16 >>> 0) + ((hl & 0xffff) << 16 >>> 0);
    let hi = hh + (lh >>> 16) + (hl >>> 16) + Math.floor(lo / 0x100000000);
    lo = lo >>> 0; hi = hi >>> 0;
    // * 2
    hi = ((hi << 1) | (lo >>> 31)) >>> 0; lo = (lo << 1) >>> 0;
    // + x + y
    let s = B[x] + B[y];
    let sh = B[x + 1] + B[y + 1] + (s / 0x100000000 >>> 0);
    s = s >>> 0;
    let r = s + lo;
    B[x + 1] = sh + hi + (r / 0x100000000 >>> 0);
    B[x] = r;
  }
  function rot(B, d, a, n) { // B[d] = rotr64(B[d] ^ B[a], n)
    const l = B[d] ^ B[a], h = B[d + 1] ^ B[a + 1];
    if (n === 32) { B[d] = h; B[d + 1] = l; }
    else if (n === 63) { B[d] = (h >>> 31) | (l << 1); B[d + 1] = (l >>> 31) | (h << 1); }
    else { B[d] = (l >>> n) | (h << (32 - n)); B[d + 1] = (h >>> n) | (l << (32 - n)); }
  }
  // P na 16 słowach o podanych indeksach (indeksy słów 64-bitowych)
  function P(B, i) {
    GB(B, i[0], i[4], i[8], i[12]); GB(B, i[1], i[5], i[9], i[13]);
    GB(B, i[2], i[6], i[10], i[14]); GB(B, i[3], i[7], i[11], i[15]);
    GB(B, i[0], i[5], i[10], i[15]); GB(B, i[1], i[6], i[11], i[12]);
    GB(B, i[2], i[7], i[8], i[13]); GB(B, i[3], i[4], i[9], i[14]);
  }
  const ROWS = [], COLS = [];
  for (let r = 0; r < 8; r++) { const a = []; for (let k = 0; k < 16; k++) a.push(2 * (16 * r + k)); ROWS.push(a); }
  for (let c = 0; c < 8; c++) {
    const a = [];
    for (let r = 0; r < 8; r++) { a.push(2 * (16 * r + 2 * c)); a.push(2 * (16 * r + 2 * c + 1)); }
    COLS.push(a);
  }
  const R = new Uint32Array(256), Z = new Uint32Array(256);
  // G(X, Y) → dst (z XOR-em starej zawartości, gdy withXor)
  function G(mem, xOff, yOff, dOff, withXor) {
    for (let i = 0; i < 256; i++) R[i] = mem[xOff + i] ^ mem[yOff + i];
    Z.set(R);
    for (let r = 0; r < 8; r++) P(Z, ROWS[r]);
    for (let c = 0; c < 8; c++) P(Z, COLS[c]);
    if (withXor) for (let i = 0; i < 256; i++) mem[dOff + i] ^= R[i] ^ Z[i];
    else for (let i = 0; i < 256; i++) mem[dOff + i] = R[i] ^ Z[i];
  }
  function Gbuf(X, Y, D) { // na osobnych buforach (generator adresów)
    for (let i = 0; i < 256; i++) R[i] = X[i] ^ Y[i];
    Z.set(R);
    for (let r = 0; r < 8; r++) P(Z, ROWS[r]);
    for (let c = 0; c < 8; c++) P(Z, COLS[c]);
    for (let i = 0; i < 256; i++) D[i] = R[i] ^ Z[i];
  }

  // ---------- Argon2id ----------
  function argon2id({ password, salt, t, m, p, tagLength = 32, secret = new Uint8Array(0), ad = new Uint8Array(0) }) {
    const H0 = blake2b(concat([le32(p), le32(tagLength), le32(m), le32(t), le32(0x13), le32(2),
      le32(password.length), password, le32(salt.length), salt, le32(secret.length), secret, le32(ad.length), ad]), 64);
    const mBlocks = 4 * p * Math.floor(m / (4 * p));
    const q = mBlocks / p, segLen = q / 4;
    const mem = new Uint32Array(mBlocks * 256);
    const blockAt = (lane, col) => (lane * q + col) * 256;
    const toWords = (bytes, off) => {
      for (let i = 0; i < 256; i++) mem[off + i] = bytes[i * 4] | (bytes[i * 4 + 1] << 8) | (bytes[i * 4 + 2] << 16) | (bytes[i * 4 + 3] << 24);
    };
    for (let l = 0; l < p; l++) {
      toWords(hPrime(concat([H0, le32(0), le32(l)]), 1024), blockAt(l, 0));
      toWords(hPrime(concat([H0, le32(1), le32(l)]), 1024), blockAt(l, 1));
    }
    const input = new Uint32Array(256), addr = new Uint32Array(256), zero = new Uint32Array(256), tmp = new Uint32Array(256);
    for (let pass = 0; pass < t; pass++) {
      for (let slice = 0; slice < 4; slice++) {
        for (let lane = 0; lane < p; lane++) {
          const dataIndependent = pass === 0 && slice < 2;
          if (dataIndependent) {
            input.fill(0);
            input[0] = pass; input[2] = lane; input[4] = slice; input[6] = mBlocks; input[8] = t; input[10] = 2; input[12] = 0;
          }
          let start = 0;
          if (pass === 0 && slice === 0) {
            start = 2;
            if (dataIndependent) { input[12]++; Gbuf(zero, input, tmp); Gbuf(zero, tmp, addr); }
          }
          for (let idx = start; idx < segLen; idx++) {
            const col = slice * segLen + idx;
            const cur = blockAt(lane, col);
            const prev = col === 0 ? blockAt(lane, q - 1) : cur - 256;
            let j1, j2;
            if (dataIndependent) {
              if (idx % 128 === 0) { input[12]++; Gbuf(zero, input, tmp); Gbuf(zero, tmp, addr); }
              j1 = addr[2 * (idx % 128)]; j2 = addr[2 * (idx % 128) + 1];
            } else {
              j1 = mem[prev]; j2 = mem[prev + 1];
            }
            const refLane = (pass === 0 && slice === 0) ? lane : j2 % p;
            // obszar odniesienia
            let refArea;
            const sameLane = refLane === lane;
            if (pass === 0) {
              refArea = sameLane ? slice * segLen + idx - 1 : slice * segLen + (idx === 0 ? -1 : 0);
            } else {
              refArea = sameLane ? q - segLen + idx - 1 : q - segLen + (idx === 0 ? -1 : 0);
            }
            // x = j1^2 / 2^32 ; y = refArea * x / 2^32 ; zz = refArea - 1 - y
            const x = Math.floor((j1 * j1) / 0x100000000);
            const y = Math.floor((refArea * x) / 0x100000000);
            const rel = refArea - 1 - y;
            const startPos = pass === 0 ? 0 : ((slice + 1) * segLen) % q;
            const refCol = (startPos + rel) % q;
            G(mem, prev, blockAt(refLane, refCol), cur, pass > 0);
          }
        }
      }
    }
    // XOR ostatnich bloków wszystkich pasów
    const fin = new Uint32Array(256);
    for (let l = 0; l < p; l++) { const o = blockAt(l, q - 1); for (let i = 0; i < 256; i++) fin[i] ^= mem[o + i]; }
    const bytes = new Uint8Array(1024);
    for (let i = 0; i < 256; i++) { bytes[i * 4] = fin[i]; bytes[i * 4 + 1] = fin[i] >>> 8; bytes[i * 4 + 2] = fin[i] >>> 16; bytes[i * 4 + 3] = fin[i] >>> 24; }
    return hPrime(bytes, tagLength);
  }
  return { argon2id, blake2b };
})();
if (typeof module !== 'undefined') module.exports = Argon2;
