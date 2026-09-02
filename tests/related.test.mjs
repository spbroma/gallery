import assert from 'node:assert/strict';
import test from 'node:test';
import { relatedKeys } from '../lib/related.ts';

test('shows only two available neighbors, skipping self, duplicates and previous photo', () => {
  assert.deepEqual(relatedKeys(['a', 'b', 'c', 'c', 'deleted', 'd', 'e'], 'a', 'b', new Set(['a', 'b', 'c', 'd', 'e'])), ['c', 'd']);
});

test('handles a small library or missing embeddings without random substitutes', () => {
  assert.deepEqual(relatedKeys([], 'a', null, new Set(['a'])), []);
  assert.deepEqual(relatedKeys(['b'], 'a', null, new Set(['a', 'b'])), ['b']);
  assert.deepEqual(relatedKeys(['b'], 'a', 'b', new Set(['a', 'b'])), []);
});
