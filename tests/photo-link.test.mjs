import assert from 'node:assert/strict';
import test from 'node:test';

import { photoHash, photoKeyFromHash } from '../lib/photo-link.ts';

test('round-trips timestamp IDs through a minimal hash', () => {
  const key = '20260915-184207';
  const hash = photoHash(key);

  assert.equal(hash, '#20260915-184207');
  assert.equal(photoKeyFromHash(hash), key);
});

test('keeps old photo links readable', () => {
  assert.equal(photoKeyFromHash(photoHash('20260915-184207')), '20260915-184207');
  assert.equal(photoKeyFromHash('#photo=2026-09-15-berlin%2Fdsc00394'), '2026-09-15-berlin/dsc00394');
});

test('ignores unrelated and malformed hashes', () => {
  assert.equal(photoKeyFromHash('#date-2026-09-15'), null);
  assert.equal(photoKeyFromHash('#photo=%E0%A4%A'), null);
  assert.equal(photoKeyFromHash('#photo='), null);
});
