export function relatedKeys(neighbors: string[], current: string, previous: string | null, available: Set<string>) {
  return [...new Set(neighbors)].filter((key) => key !== current && key !== previous && available.has(key)).slice(0, 3);
}
