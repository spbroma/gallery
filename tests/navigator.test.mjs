import assert from 'node:assert/strict';
import test from 'node:test';
import { navigatorWeights, scrollTarget } from '../lib/navigator.ts';

test('covers the full document including header and footer, splitting row ties', () => {
  const weights = navigatorWeights([100, 100, 300, 400, 700, 700], 1000);
  assert.deepEqual(weights, [150, 150, 100, 300, 150, 150]);
  assert.equal(weights.reduce((sum, value) => sum + value, 0), 1000);
});

test('works with feed, empty and single-photo galleries', () => {
  assert.deepEqual(navigatorWeights([100, 400, 900], 1200), [400, 500, 300]);
  assert.deepEqual(navigatorWeights([], 900), []);
  assert.deepEqual(navigatorWeights([100], 900), [900]);
});

test('click maps to native scrollbar thumb center and clamps at both ends', () => {
  assert.equal(scrollTarget(0, 10000, 1000), 0);
  assert.equal(scrollTarget(0.5, 10000, 1000), 4500);
  assert.equal(scrollTarget(1, 10000, 1000), 9000);
  assert.equal(scrollTarget(0.5, 500, 1000), 0);
});
