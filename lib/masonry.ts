type Dimensions = { width: number; height: number };

/** Preserve input order, placing each item in the shortest column (ties go left). */
export function masonryLayout(items: Dimensions[], width: number, columns: number, gap: number) {
  const columnWidth = Math.max(0, (width - gap * (columns - 1)) / columns);
  const bottoms = Array<number>(columns).fill(0);
  const positions = items.map((item) => {
    const column = bottoms.indexOf(Math.min(...bottoms));
    const height = columnWidth * item.height / item.width;
    const position = { left: column * (columnWidth + gap), top: bottoms[column], width: columnWidth, height };
    bottoms[column] += height + gap;
    return position;
  });
  return { positions, height: Math.max(0, ...bottoms) - (items.length ? gap : 0) };
}
