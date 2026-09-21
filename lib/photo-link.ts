const LEGACY_PHOTO_HASH_PREFIX = '#photo=';
const TIMESTAMP_ID = /^\d{8}-\d{6}(?:-[0-9a-f]{6})?$/;

export function photoHash(key: string) {
  return `#${encodeURIComponent(key)}`;
}

export function photoKeyFromHash(hash: string) {
  const encoded = hash.startsWith(LEGACY_PHOTO_HASH_PREFIX)
    ? hash.slice(LEGACY_PHOTO_HASH_PREFIX.length)
    : hash.startsWith('#')
      ? hash.slice(1)
      : '';
  if (!encoded) return null;
  try {
    const key = decodeURIComponent(encoded);
    return TIMESTAMP_ID.test(key) || key.includes('/') ? key : null;
  } catch {
    return null;
  }
}
