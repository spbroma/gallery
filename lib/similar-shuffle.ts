/**
 * Build a walk through a nearest-neighbor graph.
 *
 * The first photo is random. Each next photo is the nearest unvisited neighbor
 * of the current one. If its outgoing list is exhausted, the walk can also use
 * a reverse edge: an unvisited photo that considers the current photo one of
 * its nearest neighbors. When both directions are exhausted, a new random seed
 * starts the next component so every photo still appears exactly once.
 */
export function similarShuffle<T>(
  items: readonly T[],
  neighbors: Readonly<Record<string, readonly string[]>>,
  keyFor: (item: T) => string,
  random: () => number = Math.random,
): T[] {
  const itemsByKey = new Map(items.map((item) => [keyFor(item), item]));
  const unvisited = new Set(itemsByKey.keys());
  const result: T[] = [];
  const reverseNeighbors = new Map<string, { key: string; rank: number }[]>();
  let currentKey: string | null = null;

  Object.entries(neighbors).forEach(([key, nearest]) => {
    nearest.forEach((neighbor, rank) => {
      const reverse = reverseNeighbors.get(neighbor) ?? [];
      reverse.push({ key, rank });
      reverseNeighbors.set(neighbor, reverse);
    });
  });
  reverseNeighbors.forEach((reverse) => reverse.sort((a, b) => a.rank - b.rank));

  const randomUnvisitedKey = (): string => {
    const keys = [...unvisited];
    return keys[Math.floor(random() * keys.length)]!;
  };

  while (unvisited.size > 0) {
    const directNeighbor = currentKey === null
      ? undefined
      : neighbors[currentKey]?.find((key) => unvisited.has(key));
    const reverseNeighbor = currentKey === null || directNeighbor
      ? undefined
      : reverseNeighbors.get(currentKey)?.find(({ key }) => unvisited.has(key))?.key;
    const nextKey: string = directNeighbor ?? reverseNeighbor ?? randomUnvisitedKey();
    const item = itemsByKey.get(nextKey);

    // Duplicate item keys are collapsed by the map, so this also guards
    // against malformed neighbor data without risking an infinite loop.
    if (!item) {
      unvisited.delete(nextKey);
      currentKey = null;
      continue;
    }

    result.push(item);
    unvisited.delete(nextKey);
    currentKey = nextKey;
  }

  return result;
}
