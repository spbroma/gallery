'use client';
/* eslint-disable @next/next/no-img-element -- Storage-neutral gallery thumbnails. */

import { useEffect, useMemo, useRef, useState } from 'react';
import { masonryLayout } from '../lib/masonry';

type GridPhoto = { id: string; albumId: string; thumb: string; thumbWidth: number; thumbHeight: number };
type Props = {
  items: { photo: GridPhoto; index: number }[];
  mobileView: 'feed' | 'grid';
  basePath: string;
  onOpen: (index: number) => void;
};

export function PhotoGrid({ items, mobileView, basePath, onOpen }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [geometry, setGeometry] = useState<{ width: number; columns: number; gap: number } | null>(null);

  useEffect(() => {
    const container = ref.current;
    if (!container) return;
    const measure = () => {
      const style = getComputedStyle(container);
      const next = {
        width: container.getBoundingClientRect().width,
        columns: Number(style.getPropertyValue('--photo-columns')),
        gap: parseFloat(style.columnGap),
      };
      setGeometry((current) => current?.width === next.width && current.columns === next.columns && current.gap === next.gap ? current : next);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    window.addEventListener('resize', measure);
    measure();
    return () => { observer.disconnect(); window.removeEventListener('resize', measure); };
  }, [mobileView]);

  const layout = useMemo(() => geometry ? masonryLayout(
    items.map(({ photo }) => ({ width: photo.thumbWidth, height: photo.thumbHeight })),
    geometry.width, geometry.columns, geometry.gap,
  ) : null, [items, geometry]);

  return (
    <div ref={ref} className={`photo-grid${layout ? ' positioned' : ''}`} style={layout ? { height: layout.height } : undefined}>
      {items.map(({ photo, index }, position) => (
        <button key={`${photo.albumId}-${photo.id}`} type="button" data-photo-index={index} aria-label="Open photo"
          style={layout?.positions[position]} onClick={() => onOpen(index)}>
          <img src={`${basePath}${photo.thumb}`} alt="" loading="lazy" width={photo.thumbWidth} height={photo.thumbHeight} />
        </button>
      ))}
    </div>
  );
}
