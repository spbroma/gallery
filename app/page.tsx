'use client';
/* eslint-disable @next/next/no-img-element -- URLs come from the storage-neutral gallery manifest. */

import { useEffect, useMemo, useRef, useState } from 'react';

type Photo = { id: string; albumId: string; src: string; thumb: string; date: string };
type Gallery = { photos: Photo[] };
type IndexedPhoto = { photo: Photo; index: number };

const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? '';
const monthNames = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];

function dateLabel(date: string) {
  const [year, month, day] = date.split('-').map(Number);
  return `${monthNames[month - 1]} ${day}, ${year}`;
}

export default function Home() {
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const touchStart = useRef<number | null>(null);
  const activePhoto = activeIndex === null ? null : photos[activeIndex];

  useEffect(() => {
    fetch(`${basePath}/data/gallery.json`)
      .then((response) => response.ok ? response.json() as Promise<Gallery> : Promise.reject())
      .then((gallery) => setPhotos(gallery.photos))
      .catch(() => setPhotos([]));
  }, []);

  useEffect(() => {
    if (activeIndex === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setActiveIndex(null);
      if (event.key === 'ArrowRight') setActiveIndex((activeIndex + 1) % photos.length);
      if (event.key === 'ArrowLeft') setActiveIndex((activeIndex - 1 + photos.length) % photos.length);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [activeIndex, photos.length]);

  const groups = useMemo(() => {
    const result: { key: string; label: string; photos: IndexedPhoto[] }[] = [];
    photos.forEach((photo, index) => {
      const key = photo.date;
      const last = result[result.length - 1];
      const item = { photo, index };
      if (last?.key === key) last.photos.push(item);
      else result.push({ key, label: dateLabel(photo.date), photos: [item] });
    });
    return result;
  }, [photos]);

  const move = (direction: -1 | 1) => {
    if (activeIndex === null || photos.length === 0) return;
    setActiveIndex((activeIndex + direction + photos.length) % photos.length);
  };

  const onTouchEnd = (event: React.TouchEvent) => {
    if (touchStart.current === null) return;
    const distance = event.changedTouches[0].clientX - touchStart.current;
    if (Math.abs(distance) > 45) move(distance < 0 ? 1 : -1);
    touchStart.current = null;
  };

  return (
    <main>
      <header><h1>roma&apos;s photos</h1></header>
      <div className="timeline">
        <aside aria-label="Navigate by date">
          <nav>{groups.map((group) => <a key={group.key} href={`#date-${group.key}`}>{group.label}</a>)}</nav>
        </aside>

        <div className="dates">
          {groups.map((group) => (
            <section className="date-group" id={`date-${group.key}`} key={group.key}>
              <h2>{group.label}</h2>
              <div className="photo-grid">
                {group.photos.map(({ photo, index }) => (
                  <button key={`${photo.albumId}-${photo.id}`} type="button" aria-label="Open photo" onClick={() => setActiveIndex(index)}>
                    <img src={`${basePath}${photo.thumb}`} alt="" loading="lazy" />
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>

      {activePhoto && (
        <div
          className="lightbox"
          role="dialog"
          aria-modal="true"
          aria-label="Photo viewer"
          onClick={() => setActiveIndex(null)}
          onTouchStart={(event) => { touchStart.current = event.touches[0].clientX; }}
          onTouchEnd={onTouchEnd}
        >
          <button className="close" type="button" aria-label="Close" onClick={(event) => { event.stopPropagation(); setActiveIndex(null); }}>×</button>
          <button className="previous" type="button" aria-label="Previous photo" onClick={(event) => { event.stopPropagation(); move(-1); }}>‹</button>
          <img src={`${basePath}${activePhoto.src}`} alt="" onClick={(event) => event.stopPropagation()} />
          <button className="next" type="button" aria-label="Next photo" onClick={(event) => { event.stopPropagation(); move(1); }}>›</button>
        </div>
      )}
    </main>
  );
}
