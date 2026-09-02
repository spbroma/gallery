/** Map the ordered cards onto document height, splitting equal-height rows left to right. */
export function navigatorWeights(tops: number[], documentHeight: number): number[] {
  const weights: number[] = [];
  for (let first = 0; first < tops.length;) {
    let next = first + 1;
    while (next < tops.length && Math.abs(tops[next] - tops[first]) < 0.5) next++;
    const start = first === 0 ? 0 : tops[first];
    const end = next === tops.length ? documentHeight : tops[next];
    const weight = Math.max(0, end - start) / (next - first);
    for (let index = first; index < next; index++) weights.push(weight);
    first = next;
  }
  return weights;
}

export function scrollTarget(ratio: number, documentHeight: number, viewportHeight: number) {
  return Math.max(0, Math.min(documentHeight - viewportHeight, ratio * documentHeight - viewportHeight / 2));
}
