'use client';
/* eslint-disable @next/next/no-img-element -- URLs come from the storage-neutral gallery manifest. */

import { useEffect, useMemo, useRef, useState } from 'react';

type Photo = { id: string; albumId: string; src: string; thumb: string; date: string };
type Gallery = { photos: Photo[] };
type Visual = {
  brightness: number;
  colorfulness: number;
  colorProfile: Record<string, number>;
  dominantAverageColor: { hsv: { h: number; s: number; v: number } };
};
type Semantic = {
  shot_scale: string;
  people_count: number;
  semantic_tags: string[];
  composition_tags: string[];
};
type PhotoMetadata = { key: string; id: string; albumId: string; date: string; visual: Visual; semantic: Semantic; tags: string[] };
type FilterIndex = { photos: PhotoMetadata[] };
type LibraryPhoto = Photo & { metadata: PhotoMetadata };
type IndexedPhoto = { photo: LibraryPhoto; index: number };
type SortMode = 'date-desc' | 'date-asc' | 'dark-light' | 'light-dark' | 'muted-vivid' | 'vivid-muted' | 'hue' | 'people-asc' | 'people-desc';

const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? '';
const monthNames = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];
const shotScales = ['detail', 'extreme-close-up', 'close-up', 'medium', 'wide', 'extreme-wide'];
const peopleGroups = ['none', 'one', 'small-group', 'crowd'];
const colors = ['black', 'white', 'gray', 'red', 'orange', 'yellow', 'green', 'teal', 'blue', 'purple', 'pink', 'brown'];
const colorHex: Record<string, string> = {
  black: '#111', white: '#f4f4f0', gray: '#777', red: '#db3232', orange: '#df7628', yellow: '#e0c43a',
  green: '#4f9e55', teal: '#3c9991', blue: '#3976bd', purple: '#7956a8', pink: '#c56d91', brown: '#77513d',
};
const hiddenTags = new Set([...shotScales, 'unknown', 'no-people', 'one-person', 'small-group', 'crowd', ...colors, 'dark', 'bright', 'mid-brightness', 'muted', 'vivid', 'balanced-color', 'people', 'group']);

function dateLabel(date: string) {
  const [year, month, day] = date.split('-').map(Number);
  return `${monthNames[month - 1]} ${day}, ${year}`;
}

function label(value: string) {
  return value.replaceAll('-', ' ');
}

function peopleGroup(count: number) {
  if (count === 0) return 'none';
  if (count === 1) return 'one';
  if (count <= 5) return 'small-group';
  return 'crowd';
}

function toggle(items: string[], value: string) {
  return items.includes(value) ? items.filter((item) => item !== value) : [...items, value];
}

export default function Home() {
  const [photos, setPhotos] = useState<LibraryPhoto[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sortMode, setSortMode] = useState<SortMode>('date-desc');
  const [selectedShots, setSelectedShots] = useState<string[]>([]);
  const [selectedPeople, setSelectedPeople] = useState<string[]>([]);
  const [selectedColors, setSelectedColors] = useState<string[]>([]);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const touchStart = useRef<number | null>(null);

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

  const tagOptions = useMemo(() => {
    const counts = new Map<string, number>();
    photos.forEach(({ metadata }) => {
      [...metadata.semantic.semantic_tags, ...metadata.semantic.composition_tags].forEach((tag) => {
        if (!hiddenTags.has(tag)) counts.set(tag, (counts.get(tag) ?? 0) + 1);
      });
    });
    return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [photos]);

  const filteredPhotos = useMemo(() => {
    const result = photos.filter(({ metadata }) => {
      const shotMatch = selectedShots.length === 0 || selectedShots.includes(metadata.semantic.shot_scale);
      const peopleMatch = selectedPeople.length === 0 || selectedPeople.includes(peopleGroup(metadata.semantic.people_count));
      const colorMatch = selectedColors.length === 0 || selectedColors.some((color) => (metadata.visual.colorProfile[color] ?? 0) >= 0.08);
      const sourceTags = [...metadata.semantic.semantic_tags, ...metadata.semantic.composition_tags];
      const tagMatch = selectedTags.length === 0 || selectedTags.some((tag) => sourceTags.includes(tag));
      return shotMatch && peopleMatch && colorMatch && tagMatch;
    });

    return result.sort((a, b) => {
      if (sortMode === 'date-asc') return a.date.localeCompare(b.date);
      if (sortMode === 'date-desc') return b.date.localeCompare(a.date);
      if (sortMode === 'dark-light') return a.metadata.visual.brightness - b.metadata.visual.brightness;
      if (sortMode === 'light-dark') return b.metadata.visual.brightness - a.metadata.visual.brightness;
      if (sortMode === 'muted-vivid') return a.metadata.visual.colorfulness - b.metadata.visual.colorfulness;
      if (sortMode === 'vivid-muted') return b.metadata.visual.colorfulness - a.metadata.visual.colorfulness;
      if (sortMode === 'hue') return a.metadata.visual.dominantAverageColor.hsv.h - b.metadata.visual.dominantAverageColor.hsv.h;
      if (sortMode === 'people-asc') return a.metadata.semantic.people_count - b.metadata.semantic.people_count;
      return b.metadata.semantic.people_count - a.metadata.semantic.people_count;
    });
  }, [photos, selectedShots, selectedPeople, selectedColors, selectedTags, sortMode]);

  const activePhoto = activeIndex === null ? null : filteredPhotos[activeIndex];
  const dateSorting = sortMode === 'date-desc' || sortMode === 'date-asc';
  const activeFilterCount = selectedShots.length + selectedPeople.length + selectedColors.length + selectedTags.length;

  useEffect(() => {
    if (activeIndex === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setActiveIndex(null);
      if (event.key === 'ArrowRight') setActiveIndex((activeIndex + 1) % filteredPhotos.length);
      if (event.key === 'ArrowLeft') setActiveIndex((activeIndex - 1 + filteredPhotos.length) % filteredPhotos.length);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [activeIndex, filteredPhotos.length]);

  const groups = useMemo(() => {
    const result: { key: string; label: string; photos: IndexedPhoto[] }[] = [];
    filteredPhotos.forEach((photo, index) => {
      const key = photo.date;
      const last = result[result.length - 1];
      const item = { photo, index };
      if (last?.key === key) last.photos.push(item);
      else result.push({ key, label: dateLabel(photo.date), photos: [item] });
    });
    return result;
  }, [filteredPhotos]);

  const clearFilters = () => {
    setSelectedShots([]);
    setSelectedPeople([]);
    setSelectedColors([]);
    setSelectedTags([]);
  };

  const move = (direction: -1 | 1) => {
    if (activeIndex === null || filteredPhotos.length === 0) return;
    setActiveIndex((activeIndex + direction + filteredPhotos.length) % filteredPhotos.length);
  };

  const onTouchEnd = (event: React.TouchEvent) => {
    if (touchStart.current === null) return;
    const distance = event.changedTouches[0].clientX - touchStart.current;
    if (Math.abs(distance) > 45) move(distance < 0 ? 1 : -1);
    touchStart.current = null;
  };

  const renderPhotos = (items: IndexedPhoto[]) => (
    <div className="photo-grid">
      {items.map(({ photo, index }) => (
        <button key={`${photo.albumId}-${photo.id}`} type="button" aria-label="Open photo" onClick={() => setActiveIndex(index)}>
          <img src={`${basePath}${photo.thumb}`} alt="" loading="lazy" />
        </button>
      ))}
    </div>
  );

  return (
    <main>
      <header>
        <h1>roma&apos;s photos</h1>
        <div className="library-controls">
          <span className="result-count">{loaded ? `${filteredPhotos.length} photos` : 'loading'}</span>
          <label className="sort-control">
            <span>sort</span>
            <select value={sortMode} onChange={(event) => setSortMode(event.target.value as SortMode)}>
              <option value="date-desc">newest first</option>
              <option value="date-asc">oldest first</option>
              <option value="dark-light">dark to light</option>
              <option value="light-dark">light to dark</option>
              <option value="muted-vivid">muted to vivid</option>
              <option value="vivid-muted">vivid to muted</option>
              <option value="hue">by hue</option>
              <option value="people-asc">few to many people</option>
              <option value="people-desc">many to few people</option>
            </select>
          </label>
          <button className="filter-toggle" type="button" aria-expanded={filtersOpen} onClick={() => setFiltersOpen((open) => !open)}>
            filters{activeFilterCount > 0 ? ` · ${activeFilterCount}` : ''}
          </button>
        </div>
      </header>

      {filtersOpen && (
        <section className="filter-panel" aria-label="Photo filters">
          <div className="filter-group">
            <h2>framing</h2>
            <div className="options">{shotScales.map((item) => (
              <button key={item} type="button" aria-pressed={selectedShots.includes(item)} onClick={() => setSelectedShots(toggle(selectedShots, item))}>{label(item)}</button>
            ))}</div>
          </div>
          <div className="filter-group">
            <h2>people</h2>
            <div className="options">{peopleGroups.map((item) => (
              <button key={item} type="button" aria-pressed={selectedPeople.includes(item)} onClick={() => setSelectedPeople(toggle(selectedPeople, item))}>{label(item)}</button>
            ))}</div>
          </div>
          <div className="filter-group color-group">
            <h2>color</h2>
            <div className="options">{colors.map((item) => (
              <button className="color-option" key={item} type="button" aria-pressed={selectedColors.includes(item)} onClick={() => setSelectedColors(toggle(selectedColors, item))}>
                <span className="swatch" style={{ background: colorHex[item] }} />{item}
              </button>
            ))}</div>
          </div>
          <div className="filter-group tag-group">
            <h2>tags</h2>
            <div className="options">{tagOptions.map(([item, count]) => (
              <button key={item} type="button" aria-pressed={selectedTags.includes(item)} onClick={() => setSelectedTags(toggle(selectedTags, item))}>{label(item)} <span>{count}</span></button>
            ))}</div>
          </div>
          <button className="clear-filters" type="button" disabled={activeFilterCount === 0} onClick={clearFilters}>clear</button>
        </section>
      )}

      {dateSorting ? (
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
            {loaded && filteredPhotos.length === 0 && <p className="empty-state">no photos match these filters</p>}
          </div>
        </div>
      ) : (
        <section className="sorted-results">
          {renderPhotos(filteredPhotos.map((photo, index) => ({ photo, index })))}
          {loaded && filteredPhotos.length === 0 && <p className="empty-state">no photos match these filters</p>}
        </section>
      )}

      {activePhoto && (
        <div className="lightbox" role="dialog" aria-modal="true" aria-label="Photo viewer" onClick={() => setActiveIndex(null)} onTouchStart={(event) => { touchStart.current = event.touches[0].clientX; }} onTouchEnd={onTouchEnd}>
          <button className="close" type="button" aria-label="Close" onClick={(event) => { event.stopPropagation(); setActiveIndex(null); }}>×</button>
          <button className="previous" type="button" aria-label="Previous photo" onClick={(event) => { event.stopPropagation(); move(-1); }}>‹</button>
          <img src={`${basePath}${activePhoto.src}`} alt="" onClick={(event) => event.stopPropagation()} />
          <button className="next" type="button" aria-label="Next photo" onClick={(event) => { event.stopPropagation(); move(1); }}>›</button>
        </div>
      )}
    </main>
  );
}
