import assert from 'node:assert/strict';
import test from 'node:test';
import { masonryLayout } from '../lib/masonry.ts';

test('keeps filling the shorter column, resolving ties to the left', () => {
  const items = [3, 1, 1, 2, 1].map((height) => ({ width: 1, height }));
  const { positions, height } = masonryLayout(items, 200, 2, 0);
  assert.deepEqual(positions.map(({ left, top }) => [left, top]), [
    [0, 0], [100, 0], [100, 100], [100, 200], [0, 300],
  ]);
  assert.equal(height, 400);
});

test('preserves proportions, order and gaps for feed, two and three columns', () => {
  const items = Array.from({ length: 130 }, (_, i) => ({ width: 600 + i * 7, height: 400 + (i % 7) * 175 }));
  for (const width of [300, 390, 768, 1440]) {
    for (const columns of [1, 2, 3]) {
      const { positions, height } = masonryLayout(items, width, columns, 6);
      const bottoms = new Map();
      positions.forEach((position, index) => {
        assert.ok(Math.abs(position.width / position.height - items[index].width / items[index].height) < 1e-9);
        assert.ok(position.left + position.width <= width + 1e-9);
        assert.ok(position.top + position.height <= height + 1e-9);
        assert.ok(Math.abs(position.top - (bottoms.get(position.left) ?? 0)) < 1e-9);
        bottoms.set(position.left, position.top + position.height + 6);
        if (index > 0) {
          assert.ok(position.top >= positions[index - 1].top);
          if (position.top === positions[index - 1].top) assert.ok(position.left > positions[index - 1].left);
        }
      });
      assert.equal(bottoms.size, columns);
    }
  }
});

test('empty grid has zero height', () => {
  assert.deepEqual(masonryLayout([], 390, 2, 6), { positions: [], height: 0 });
});
