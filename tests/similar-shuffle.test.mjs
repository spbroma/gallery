import assert from 'node:assert/strict';
import test from 'node:test';

import { similarShuffle } from '../lib/similar-shuffle.ts';

const keyFor = (item) => item;

test('starts randomly and follows the nearest unvisited neighbors', () => {
  const neighbors = {
    a: ['b', 'c'],
    b: ['a', 'c'],
    c: ['b'],
    d: ['e'],
    e: ['d'],
  };

  assert.deepEqual(similarShuffle(['a', 'b', 'c', 'd', 'e'], neighbors, keyFor, () => 0), ['a', 'b', 'c', 'd', 'e']);
});

test('uses reverse semantic links before starting a new random chain', () => {
  const randomValues = [0.75, 0];
  const result = similarShuffle(
    ['a', 'b', 'c', 'd'],
    { a: ['b'], b: [], c: ['d'], d: [] },
    keyFor,
    () => randomValues.shift() ?? 0,
  );

  assert.deepEqual(result, ['d', 'c', 'a', 'b']);
});

test('ignores unknown and repeated neighbors and keeps every photo once', () => {
  const result = similarShuffle(
    ['a', 'b', 'c'],
    { a: ['missing', 'b', 'b'], b: ['a'], c: [] },
    keyFor,
    () => 0,
  );

  assert.deepEqual(result, ['a', 'b', 'c']);
});
