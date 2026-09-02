'use client';
/* eslint-disable @next/next/no-img-element -- URLs come from the storage-neutral gallery manifest. */

import { useEffect, useMemo, useRef, useState } from 'react';
import { shuffle } from '../lib/shuffle';
import { PhotoGrid } from './photo-grid';
import { navigatorWeights, scrollTarget } from '../lib/navigator';

type Photo = { id: string; albumId: string; src: string; thumb: string; date: string; thumbWidth: number; thumbHeight: number };
type Gallery = { photos: Photo[] };
type Visual = {
  brightness: number;
  dominantAverageColor: { hsv: { h: number; s: number; v: number } };
};
type PhotoMetadata = { key: string; id: string; albumId: string; date: string; visual: Visual };
type FilterIndex = { photos: PhotoMetadata[] };
type LibraryPhoto = Photo & { metadata: PhotoMetadata };
type IndexedPhoto = { photo: LibraryPhoto; index: number };
type Mode = 'date' | 'light' | 'color' | 'shuffle';
type Direction = 'asc' | 'desc';
type MobileView = 'feed' | 'grid';

const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? '';
const monthNames = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];

function dateLabel(date: string) {
  const [year, month, day] = date.split('-').map(Number);
  return `${monthNames[month - 1]} ${day}, ${year}`;
}

function directionLabel(mode: Mode, direction: Direction) {
  if (mode === 'shuffle') return 'random order';
  if (mode === 'date') return direction === 'asc' ? 'oldest first' : 'newest first';
  if (mode === 'light') return direction === 'asc' ? 'dark to light' : 'light to dark';
  return direction === 'asc' ? 'hue ascending' : 'hue descending';
}

function compareColor(a: LibraryPhoto, b: LibraryPhoto) {
  const first = a.metadata.visual.dominantAverageColor.hsv;
  const second = b.metadata.visual.dominantAverageColor.hsv;
  const firstNeutral = first.s < 0.12;
  const secondNeutral = second.s < 0.12;
  if (firstNeutral !== secondNeutral) return firstNeutral ? -1 : 1;
  if (firstNeutral) return first.v - second.v;
  return first.h - second.h || second.s - first.s;
}

function navigatorSegmentStyle(photo: LibraryPhoto, mode: 'light' | 'color') {
  if (mode === 'light') {
    const lightness = Math.round(photo.metadata.visual.brightness * 100);
    return { background: `hsl(0 0% ${lightness}%)` };
  }
  if (mode === 'color') {
    const { h, s, v } = photo.metadata.visual.dominantAverageColor.hsv;
    if (s < 0.12) return { background: `hsl(0 0% ${Math.round(v * 100)}%)` };
    return { background: `hsl(${h} ${Math.round(s * 100)}% ${Math.round(Math.max(0.18, v) * 60)}%)` };
  }
}

export default function Home() {
  const [photos, setPhotos] = useState<LibraryPhoto[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [mode, setMode] = useState<Mode>('date');
  const [shuffledPhotos, setShuffledPhotos] = useState<LibraryPhoto[]>([]);
  const [direction, setDirection] = useState<Direction>('desc');
  const [mobileView, setMobileView] = useState<MobileView>('grid');
  const [expandedSort, setExpandedSort] = useState(false);
  const [stripWeights, setStripWeights] = useState<number[]>([]);
  const controlsRef = useRef<HTMLDivElement>(null);
  const sortRef = useRef<HTMLDivElement>(null);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [lightboxControls, setLightboxControls] = useState(false);
  const touchStart = useRef<number | null>(null);
  const suppressTap = useRef(false);

  useEffect(() => {
    const controls = controlsRef.current;
    const sort = sortRef.current;
    if (!controls || !sort) return;
    const options = sort.querySelector<HTMLElement>('.sort-options')!;
    const label = sort.querySelector<HTMLElement>('.sort-label')!;
    const measure = () => {
      const siblings = [...controls.children].filter((element) => element !== sort && element.getBoundingClientRect().width > 0);
      const siblingWidth = siblings.reduce((sum, element) => sum + element.getBoundingClientRect().width, 0);
      const gaps = parseFloat(getComputedStyle(controls).columnGap) * siblings.length;
      const sortWidth = label.getBoundingClientRect().width + parseFloat(getComputedStyle(sort).columnGap) + options.getBoundingClientRect().width;
      setExpandedSort(siblingWidth + gaps + sortWidth <= controls.getBoundingClientRect().width);
    };
    const observer = new ResizeObserver(measure);
    [controls, ...controls.children, options, label].forEach((element) => observer.observe(element));
    window.addEventListener('resize', measure);
    measure();
    return () => { observer.disconnect(); window.removeEventListener('resize', measure); };
  }, []);

  useEffect(() => {
    Promise.all([
      fetch(`${basePath}/data/gallery.json`).then((response) => response.ok ? response.json() as Promise<Gallery> : Promise.reject()),
      fetch(`${basePath}/data/photo-filters.json`).then((response) => response.ok ? response.json() as Promise<FilterIndex> : Promise.reject()),
    ])
      .then(([gallery, index]) => {
        const metadata = new Map(index.photos.map((photo) => [`${photo.albumId}/${photo.id}`, photo]));
        setPhotos(gallery.photos.flatMap((photo) => {
          const match = metadata.get(`${photo.albumId}/${photo.id}`);
          return match ? [{ ...photo, metadata: match }] : [];
        }));
      })
      .catch(() => setPhotos([]))
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    const savedView = window.localStorage.getItem('roma-photos-mobile-view');
    if (savedView !== 'feed' && savedView !== 'grid') return;
    const frame = window.requestAnimationFrame(() => setMobileView(savedView));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  const sortedPhotos = useMemo(() => {
    if (mode === 'shuffle') return shuffledPhotos;
    const result = [...photos];
    return result.sort((a, b) => {
      let comparison = 0;
      if (mode === 'date') comparison = a.date.localeCompare(b.date);
      else if (mode === 'light') comparison = a.metadata.visual.brightness - b.metadata.visual.brightness;
      else comparison = compareColor(a, b);
      if (comparison === 0) comparison = a.date.localeCompare(b.date) || a.id.localeCompare(b.id);
      return direction === 'asc' ? comparison : -comparison;
    });
  }, [photos, mode, direction, shuffledPhotos]);

  const activePhoto = activeIndex === null ? null : sortedPhotos[activeIndex];

  // Shortest-column placement preserves the sorted top-to-bottom order,
  // with left-to-right ties. The strip and lightbox use that same sequence.
  const visualNavigatorOrder = sortedPhotos.map((_, index) => index);

  useEffect(() => {
    if (mode !== 'light' && mode !== 'color') return;
    const grid = document.querySelector<HTMLElement>('.sorted-results .photo-grid');
    if (!grid) return;
    let frame = 0;
    const measure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const tops = [...grid.querySelectorAll<HTMLElement>('[data-photo-index]')]
          .map((card) => card.getBoundingClientRect().top + window.scrollY);
        const weights = navigatorWeights(tops, document.documentElement.scrollHeight);
        setStripWeights((current) => current.length === weights.length && current.every((value, index) => Math.abs(value - weights[index]) < 0.01) ? current : weights);
      });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(grid);
    observer.observe(document.body);
    window.addEventListener('resize', measure);
    measure();
    return () => { cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener('resize', measure); };
  }, [mode, sortedPhotos, mobileView]);

  useEffect(() => {
    if (activeIndex === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setActiveIndex(null);
      if (event.key === 'ArrowRight') setActiveIndex((activeIndex + 1) % sortedPhotos.length);
      if (event.key === 'ArrowLeft') setActiveIndex((activeIndex - 1 + sortedPhotos.length) % sortedPhotos.length);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [activeIndex, sortedPhotos.length]);

  const groups = useMemo(() => {
    const result: { key: string; label: string; photos: IndexedPhoto[] }[] = [];
    sortedPhotos.forEach((photo, index) => {
      const key = photo.date;
      const last = result[result.length - 1];
      const item = { photo, index };
      if (last?.key === key) last.photos.push(item);
      else result.push({ key, label: dateLabel(photo.date), photos: [item] });
    });
    return result;
  }, [sortedPhotos]);

  const move = (direction: -1 | 1) => {
    if (activeIndex === null || sortedPhotos.length === 0) return;
    setActiveIndex((activeIndex + direction + sortedPhotos.length) % sortedPhotos.length);
  };

  const onTouchEnd = (event: React.TouchEvent) => {
    if (touchStart.current === null) return;
    const distance = event.changedTouches[0].clientX - touchStart.current;
    if (Math.abs(distance) > 45) {
      suppressTap.current = true;
      window.setTimeout(() => { suppressTap.current = false; }, 350);
      move(distance < 0 ? 1 : -1);
    }
    touchStart.current = null;
  };

  const onLightboxTap = () => {
    if (suppressTap.current) {
      suppressTap.current = false;
      return;
    }
    if (window.matchMedia('(max-width: 640px)').matches) {
      setLightboxControls((visible) => !visible);
    } else {
      setActiveIndex(null);
    }
  };

  const selectMobileView = (view: MobileView) => {
    setMobileView(view);
    window.localStorage.setItem('roma-photos-mobile-view', view);
  };

  const navigateFromStrip = (clientY: number, target: HTMLButtonElement) => {
    const track = target.querySelector<HTMLElement>('.mode-navigator-track');
    if (!track || sortedPhotos.length === 0) return;
    const rect = track.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    window.scrollTo({
      top: scrollTarget(ratio, document.documentElement.scrollHeight, document.documentElement.clientHeight),
      behavior: 'instant',
    });
  };

  const renderPhotos = (items: IndexedPhoto[]) => (
    <PhotoGrid items={items} mobileView={mobileView} basePath={basePath}
      onOpen={(index) => { setActiveIndex(index); setLightboxControls(false); }} />
  );

  return (
    <main className={`mobile-view-${mobileView}`}>
      <header>
        <h1>roma&apos;s photos</h1>
        <div className="library-controls" ref={controlsRef}>
          <span className="result-count">{loaded ? `${sortedPhotos.length} photos` : 'loading'}</span>
          <div className="view-toggle" role="group" aria-label="Photo layout">
            <button type="button" aria-pressed={mobileView === 'feed'} onClick={() => selectMobileView('feed')}>feed</button>
            <button type="button" aria-pressed={mobileView === 'grid'} onClick={() => selectMobileView('grid')}>grid</button>
          </div>
          <button className="shuffle-button" type="button" disabled={!loaded || photos.length < 2} aria-pressed={mode === 'shuffle'} onClick={() => {
            setShuffledPhotos(shuffle(photos));
            setMode('shuffle');
          }}><span>random shuffle</span></button>
          <div className={`mode-control${expandedSort ? ' expanded' : ''}`} ref={sortRef}>
            <span className="sort-label">sort</span>
            <div className="sort-options" role="group" aria-label="Sort">
              {(['date', 'light', 'color'] as const).map((option) => (
                <button key={option} type="button" aria-pressed={mode === option} onClick={() => setMode(option)}>{option}</button>
              ))}
            </div>
            <select aria-label="Sort" value={mode} onChange={(event) => setMode(event.target.value as Mode)}>
              <option value="date">date</option>
              <option value="light">light</option>
              <option value="color">color</option>
              {mode === 'shuffle' && <option value="shuffle" disabled>random</option>}
            </select>
          </div>
          <button className="direction-toggle" type="button" disabled={mode === 'shuffle'} aria-label={directionLabel(mode, direction)} title={directionLabel(mode, direction)} onClick={() => setDirection((current) => current === 'asc' ? 'desc' : 'asc')}>
            {direction === 'asc' ? '↑' : '↓'}
          </button>
        </div>
      </header>

      {mode === 'date' ? (
        <div className="timeline">
          <aside aria-label="Navigate by date">
            <nav>{groups.map((group) => <a key={group.key} href={`#date-${group.key}`}>{group.label}</a>)}</nav>
          </aside>
          <div className="dates">
            {groups.map((group) => (
              <section className="date-group" id={`date-${group.key}`} key={group.key}>
                <h2>{group.label}</h2>
                {renderPhotos(group.photos)}
              </section>
            ))}
            {loaded && sortedPhotos.length === 0 && <p className="empty-state">no photos</p>}
          </div>
        </div>
      ) : (
        <>
          <section className="sorted-results">
            {renderPhotos(sortedPhotos.map((photo, index) => ({ photo, index })))}
            {loaded && sortedPhotos.length === 0 && <p className="empty-state">no photos</p>}
          </section>
          {(mode === 'light' || mode === 'color') && sortedPhotos.length > 0 && (
            <button
              className="mode-navigator"
              type="button"
              aria-label={`Navigate ${mode} order`}
              title={`Navigate ${mode} order`}
              onPointerDown={(event) => {
                event.currentTarget.setPointerCapture(event.pointerId);
                navigateFromStrip(event.clientY, event.currentTarget);
              }}
              onPointerMove={(event) => {
                if (event.currentTarget.hasPointerCapture(event.pointerId)) navigateFromStrip(event.clientY, event.currentTarget);
              }}
            >
              <span className="mode-navigator-track" aria-hidden="true">
                {visualNavigatorOrder.map((photoIndex) => {
                  const photo = sortedPhotos[photoIndex];
                  return <span key={`${photo.albumId}-${photo.id}`} data-photo-index={photoIndex} style={{ ...navigatorSegmentStyle(photo, mode), flexGrow: stripWeights.length === sortedPhotos.length ? stripWeights[photoIndex] : 1 }} />;
                })}
              </span>
            </button>
          )}
        </>
      )}

      {activePhoto && (
        <div className={`lightbox${lightboxControls ? ' controls-visible' : ''}`} role="dialog" aria-modal="true" aria-label="Photo viewer" onClick={onLightboxTap} onTouchStart={(event) => { touchStart.current = event.touches[0].clientX; }} onTouchEnd={onTouchEnd}>
          <button className="close" type="button" aria-label="Close" onClick={(event) => { event.stopPropagation(); setActiveIndex(null); }}>×</button>
          <button className="previous" type="button" aria-label="Previous photo" onClick={(event) => { event.stopPropagation(); move(-1); }}>‹</button>
          <img src={`${basePath}${activePhoto.src}`} alt="" onClick={(event) => {
            event.stopPropagation();
            if (window.matchMedia('(max-width: 640px)').matches) onLightboxTap();
          }} />
          <span className="lightbox-date">{dateLabel(activePhoto.date)}</span>
          <button className="next" type="button" aria-label="Next photo" onClick={(event) => { event.stopPropagation(); move(1); }}>›</button>
        </div>
      )}
    </main>
  );
}
