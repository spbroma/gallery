const state = { shoots: [], photos: [], tags: [], activeShoot: null, selected: new Set(), draft: [], metadataDirty: [], releasePending: false, view: 'shoots' };
const $ = (selector) => document.querySelector(selector);
const shootsNode = $('#shoots');
const gridNode = $('#grid');
const emptyNode = $('#empty');
const titleNode = $('#shoot-title');
const metaNode = $('#shoot-meta');
const countNode = $('#result-count');
const visibilityNode = $('#visibility-filter');
const tagFilterNode = $('#tag-filter');
const template = $('#photo-template');
const editor = $('#editor');
const reviewDialog = $('#review-dialog');
const publishDialog = $('#publish-dialog');
let editingPhoto = null;
let draftManualTags = [];
let draftGeneratedTags = [];
const tagPhotoCache = new Map();
const expandedTags = new Set();

const keyFor = (photo) => `${photo.shoot}/${photo.id}`;

function renderViewTabs() {
  $('#view-shoots').classList.toggle('active', state.view === 'shoots');
  $('#view-all').classList.toggle('active', state.view === 'all');
  $('#view-issues').classList.toggle('active', state.view === 'issues');
  $('#view-tags').classList.toggle('active', state.view === 'tags');
  $('#shoots-panel').hidden = state.view !== 'shoots';
  $('#problem-count').textContent = state.shoots.reduce((sum, shoot) => sum + shoot.problemCount, 0);
}

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'request failed');
  return data;
}

async function post(path, body) {
  return request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

function renderShoots() {
  shootsNode.replaceChildren(...state.shoots.map((shoot) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `shoot-button${state.activeShoot?.path === shoot.path ? ' active' : ''}`;
    const name = document.createElement('span'); name.className = 'shoot-name'; name.textContent = shoot.name;
    const count = document.createElement('span'); count.className = 'shoot-count'; count.textContent = `${shoot.photoCount} photos · folder ${shoot.sourceTier}`;
    button.append(name, count);
    button.addEventListener('click', () => selectShoot(shoot));
    return button;
  }));
  renderViewTabs();
}

function visiblePhotos() {
  const visibility = visibilityNode.value;
  const query = tagFilterNode.value.trim().toLowerCase();
  return state.photos.filter((photo) => {
    if (visibility === 'published' && !photo.published) return false;
    if (visibility === 'hidden' && photo.published) return false;
    return !query || [...photo.manualTags, ...photo.generatedTags].some((tag) => tag.includes(query));
  });
}

function renderSelection() {
  $('#selection-actions').hidden = state.selected.size === 0;
  $('#selection-count').textContent = `${state.selected.size} selected`;
}

function renderPhotos() {
  const photos = visiblePhotos();
  countNode.textContent = `${photos.length} photos`;
  emptyNode.hidden = photos.length > 0;
  if (state.activeShoot && !photos.length) emptyNode.textContent = 'no photos match the filters';
  gridNode.replaceChildren(...photos.map((photo) => {
    const card = template.content.firstElementChild.cloneNode(true);
    const key = keyFor(photo);
    card.classList.toggle('published', photo.published);
    card.classList.toggle('pending', photo.pending || photo.metadataPending);
    card.classList.toggle('selected', state.selected.has(key));
    const open = card.querySelector('.photo-open');
    open.querySelector('img').src = photo.preview;
    open.querySelector('.photo-name').textContent = photo.file;
    const visibleIssues = photo.published ? photo.issues : [];
    open.querySelector('.issue-list').replaceChildren(...visibleIssues.map((issue) => {
      const node = document.createElement('span'); node.textContent = issue; return node;
    }));
    const tags = [
      ...photo.manualTags.map((tag) => ({ tag, manual: true })),
      ...photo.generatedTags.filter((tag) => !photo.manualTags.includes(tag)).map((tag) => ({ tag, manual: false })),
    ];
    open.querySelector('.tag-list').replaceChildren(...tags.slice(0, 8).map(({ tag, manual }) => {
      const node = document.createElement('span'); node.className = `tag${manual ? ' manual' : ''}`; node.textContent = tag; return node;
    }));
    open.addEventListener('click', () => openEditor(photo));
    const checkbox = card.querySelector('input');
    checkbox.checked = state.selected.has(key);
    checkbox.setAttribute('aria-label', `Select ${photo.file}`);
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) state.selected.add(key); else state.selected.delete(key);
      renderPhotos();
    });
    return card;
  }));
  renderSelection();
}

function renderTags() {
  const query = $('#tag-search').value.trim().toLowerCase();
  const tags = state.tags.filter((entry) => !query || entry.tag.includes(query));
  countNode.textContent = `${tags.length} tags`;
  $('#tag-status').textContent = `${tags.length} of ${state.tags.length} tags`;
  $('#tag-manager-list').replaceChildren(...tags.map((entry) => {
    const group = document.createElement('article'); group.className = 'tag-manager-group';
    const row = document.createElement('div'); row.className = 'tag-manager-row';
    const name = document.createElement('button'); name.type = 'button'; name.className = 'managed-tag'; name.title = 'Show related photos';
    const arrow = document.createElement('span'); arrow.className = 'tag-expand-arrow'; arrow.textContent = expandedTags.has(entry.tag) ? '−' : '+';
    const label = document.createElement('span'); label.textContent = entry.tag; name.append(arrow, label);
    const usage = document.createElement('div'); usage.className = 'tag-usage';
    usage.textContent = `${entry.count} photos · ${entry.publishedCount} published · ${entry.manualCount} manual · ${entry.generatedCount} generated`;
    const actions = document.createElement('div'); actions.className = 'tag-actions';
    const input = document.createElement('input'); input.value = entry.tag; input.setAttribute('aria-label', `Rename ${entry.tag}`);
    const rename = document.createElement('button'); rename.type = 'button'; rename.textContent = 'rename / merge';
    rename.addEventListener('click', () => manageTag('rename', entry.tag, input.value));
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'delete-tag'; remove.textContent = 'delete';
    remove.addEventListener('click', () => { if (window.confirm(`Delete “${entry.tag}” from ${entry.count} photos?`)) manageTag('delete', entry.tag); });
    actions.append(input, rename, remove); row.append(name, usage, actions);
    const photos = document.createElement('div'); photos.className = 'tag-photo-panel'; photos.hidden = !expandedTags.has(entry.tag);
    name.addEventListener('click', () => toggleTagPhotos(entry.tag, photos, arrow));
    group.append(row, photos);
    if (expandedTags.has(entry.tag)) loadTagPhotos(entry.tag, photos);
    return group;
  }));
}

function renderTagPhotos(photos, container) {
  container.replaceChildren(...photos.map((photo) => {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'tag-photo';
    const image = document.createElement('img'); image.src = photo.preview; image.alt = ''; image.loading = 'lazy';
    const caption = document.createElement('span'); caption.textContent = `${photo.file} · ${photo.shoot}`;
    button.append(image, caption); button.addEventListener('click', () => openEditor(photo)); return button;
  }));
}

async function loadTagPhotos(tag, container) {
  container.textContent = 'loading photos…';
  try {
    if (!tagPhotoCache.has(tag)) tagPhotoCache.set(tag, (await request(`/api/tag-photos?tag=${encodeURIComponent(tag)}`)).photos);
    renderTagPhotos(tagPhotoCache.get(tag), container);
  } catch (error) { container.textContent = error.message; }
}

async function toggleTagPhotos(tag, container, arrow) {
  if (expandedTags.has(tag)) {
    expandedTags.delete(tag); container.hidden = true; arrow.textContent = '+'; return;
  }
  expandedTags.add(tag); container.hidden = false; arrow.textContent = '−';
  await loadTagPhotos(tag, container);
}

async function loadTags() {
  state.tags = (await request('/api/tags')).tags; renderTags();
}

async function manageTag(action, tag, newTag = '') {
  $('#tag-status').textContent = `${action === 'delete' ? 'deleting' : 'renaming'} ${tag}…`;
  try {
    const result = await post('/api/tags/manage', { action, tag, newTag });
    tagPhotoCache.clear(); expandedTags.delete(tag);
    state.tags = result.tags; state.draft = result.draft; state.metadataDirty = result.metadataDirty; state.releasePending = result.releasePending;
    renderDraft(); renderTags();
    $('#tag-status').textContent = `${result.affectedCount} photos updated locally · Apply & publish to sync the site`;
  } catch (error) { $('#tag-status').textContent = error.message; }
}

function renderEditorTags() {
  $('#manual-tags').replaceChildren(...draftManualTags.map((tag) => {
    const button = document.createElement('button'); button.type = 'button'; button.title = 'Remove manual tag'; button.textContent = `${tag} ×`;
    button.addEventListener('click', () => { draftManualTags = draftManualTags.filter((item) => item !== tag); renderEditorTags(); });
    return button;
  }));
  $('#generated-tags').replaceChildren(...draftGeneratedTags.filter((tag) => !draftManualTags.includes(tag)).map((tag) => {
    const button = document.createElement('button'); button.type = 'button'; button.title = 'Make this tag manual'; button.textContent = tag;
    button.addEventListener('click', () => { draftManualTags = [...draftManualTags, tag]; draftGeneratedTags = draftGeneratedTags.filter((item) => item !== tag); renderEditorTags(); });
    return button;
  }));
}

function openEditor(photo) {
  editingPhoto = photo;
  draftManualTags = [...photo.manualTags]; draftGeneratedTags = [...photo.generatedTags];
  $('#editor-name').textContent = photo.file; $('#editor-image').src = photo.preview;
  $('#editor-published').checked = photo.published; $('#editor-description').value = photo.description || '';
  $('#editor-shot').value = photo.shotScale || 'unknown'; $('#editor-people').value = photo.peopleCount ?? 0;
  $('#new-tag').value = '';
  $('#save-status').textContent = photo.pending ? 'publication change pending; metadata saves immediately' : 'metadata saves locally; publication waits for apply';
  renderEditorTags(); editor.showModal();
}

function addManualTag() {
  const tag = $('#new-tag').value.trim().toLowerCase();
  if (!tag) return;
  if (!draftManualTags.includes(tag)) draftManualTags.push(tag);
  draftGeneratedTags = draftGeneratedTags.filter((item) => item !== tag);
  $('#new-tag').value = ''; renderEditorTags();
}

async function reloadPhotos() {
  if (state.view === 'tags') { await loadTags(); return; }
  if (state.view === 'shoots' && !state.activeShoot) return;
  const path = state.view === 'shoots'
    ? `/api/photos?shoot=${encodeURIComponent(state.activeShoot.path)}`
    : `/api/all-photos${state.view === 'issues' ? '?issues=1' : ''}`;
  state.photos = (await request(path)).photos;
  renderPhotos();
}

async function stagePublication(updates) {
  const result = await post('/api/draft', { updates });
  state.draft = result.draft; state.metadataDirty = result.metadataDirty;
  renderDraft();
  await reloadPhotos();
}

$('#add-tag').addEventListener('click', addManualTag);
$('#new-tag').addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); addManualTag(); } });
$('#promote-all').addEventListener('click', () => { draftManualTags = [...new Set([...draftManualTags, ...draftGeneratedTags])]; draftGeneratedTags = []; renderEditorTags(); });
$('#save-photo').addEventListener('click', async () => {
  if (!editingPhoto) return;
  const status = $('#save-status'); status.textContent = 'saving metadata';
  try {
    const metadataResult = await post('/api/photo', {
      shoot: editingPhoto.shoot, id: editingPhoto.id, manualTags: draftManualTags, generatedTags: draftGeneratedTags,
      description: $('#editor-description').value, shotScale: $('#editor-shot').value, peopleCount: $('#editor-people').value,
    });
    tagPhotoCache.clear();
    state.metadataDirty = metadataResult.metadataDirty;
    await stagePublication([{ shoot: editingPhoto.shoot, id: editingPhoto.id, published: $('#editor-published').checked }]);
    editor.close();
  } catch (error) { status.textContent = error.message; }
});

async function updateSelection(published) {
  const selected = state.photos.filter((photo) => state.selected.has(keyFor(photo)));
  if (!selected.length) return;
  try {
    await stagePublication(selected.map((photo) => ({ shoot: photo.shoot, id: photo.id, published })));
    state.selected.clear(); renderPhotos();
  } catch (error) { $('#selection-count').textContent = error.message; }
}
$('#select-publish').addEventListener('click', () => updateSelection(true));
$('#select-hide').addEventListener('click', () => updateSelection(false));
$('#clear-selection').addEventListener('click', () => { state.selected.clear(); renderPhotos(); });

const valueText = (value) => value ? 'published' : 'not published';
function renderDraft() {
  const changedKeys = new Set([...state.draft.map((entry) => entry.key), ...state.metadataDirty.map((entry) => entry.key)]);
  const hasPending = changedKeys.size > 0 || state.releasePending;
  $('#draft-count').textContent = changedKeys.size || (state.releasePending ? '•' : '0');
  $('#review-button').disabled = !hasPending;
  const publicationRows = state.draft.map((entry) => {
    const article = document.createElement('article'); article.className = 'review-entry';
    article.classList.add(entry.after.published ? 'publication-add' : 'publication-remove');
    const image = document.createElement('img'); image.src = entry.preview; image.alt = '';
    const content = document.createElement('div'); content.className = 'review-content';
    const title = document.createElement('div'); title.className = 'review-title'; title.textContent = `${entry.file} · ${entry.shoot}`;
    const change = document.createElement('div'); change.className = 'change-row';
    const label = document.createElement('span'); label.textContent = 'website';
    const before = document.createElement('del'); before.textContent = valueText(entry.before.published);
    const after = document.createElement('ins'); after.textContent = valueText(entry.after.published);
    change.append(label, before, after); content.append(title, change);
    const metadata = state.metadataDirty.find((item) => item.key === entry.key);
    if (metadata) {
      const note = document.createElement('div'); note.className = 'metadata-note'; note.textContent = `${metadata.fields.join(', ')} saved locally · pending site sync`;
      content.append(note);
    }
    const discard = document.createElement('button'); discard.type = 'button'; discard.className = 'discard-change'; discard.textContent = 'discard';
    discard.addEventListener('click', async () => { const result = await post('/api/draft/discard', { keys: [entry.key] }); state.draft = result.draft; state.metadataDirty = result.metadataDirty; renderDraft(); await reloadPhotos(); });
    article.append(image, content, discard); return article;
  });
  const publicationKeys = new Set(state.draft.map((entry) => entry.key));
  const metadataRows = state.metadataDirty.filter((entry) => !publicationKeys.has(entry.key)).map((entry) => {
    const article = document.createElement('article'); article.className = 'review-entry metadata-entry';
    const image = document.createElement('img'); image.src = entry.preview; image.alt = '';
    const content = document.createElement('div'); content.className = 'review-content';
    const title = document.createElement('div'); title.className = 'review-title'; title.textContent = `${entry.file} · ${entry.shoot}`;
    const note = document.createElement('div'); note.className = 'metadata-note'; note.textContent = `${entry.fields.join(', ')} saved locally · pending site sync`;
    content.append(title, note); article.append(image, content); return article;
  });
  $('#review-list').replaceChildren(...publicationRows, ...metadataRows);
  $('#apply-status').textContent = changedKeys.size ? `${state.draft.length} publication changes · ${state.metadataDirty.length} metadata updates.` : (state.releasePending ? 'Repository changes are rebuilt and waiting to publish.' : 'No changes waiting for site sync.');
  $('#apply-changes').disabled = !hasPending; $('#discard-all').hidden = !state.draft.length;
}

$('#review-button').addEventListener('click', () => { renderDraft(); reviewDialog.showModal(); });
$('#close-review').addEventListener('click', () => reviewDialog.close());
$('#discard-all').addEventListener('click', async () => { const result = await post('/api/draft/discard', { keys: state.draft.map((entry) => entry.key) }); state.draft = result.draft; state.metadataDirty = result.metadataDirty; renderDraft(); await reloadPhotos(); });
function appendPublishLog(message, type = 'status') {
  const line = document.createElement('span'); line.className = `log-${type}`; line.textContent = message;
  $('#publish-log').append(line, '\n'); $('#publish-log').scrollTop = $('#publish-log').scrollHeight;
}

async function streamApply() {
  const response = await fetch('/api/apply', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  if (!response.ok || !response.body) throw new Error(`Publication request failed (${response.status})`);
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
  while (true) {
    const { value, done } = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split('\n'); buffer = lines.pop() || '';
    for (const raw of lines) {
      if (!raw.trim()) continue;
      const event = JSON.parse(raw); appendPublishLog(event.message, event.type);
      if (event.type === 'error') throw new Error(event.message);
      if (event.type === 'complete') return event.result;
    }
    if (done) break;
  }
  throw new Error('Publication stream ended unexpectedly.');
}

function finishPublish() { if (!$('#finish-publish').disabled) publishDialog.close(); }
$('#close-publish').addEventListener('click', finishPublish);
$('#finish-publish').addEventListener('click', finishPublish);

$('#apply-changes').addEventListener('click', async () => {
  const button = $('#apply-changes'); button.disabled = true; $('#discard-all').disabled = true;
  $('#publish-log').replaceChildren(); $('#publish-title').textContent = 'publishing…';
  $('#publish-result').textContent = 'Please keep this window open.';
  $('#close-publish').disabled = true; $('#finish-publish').disabled = true;
  publishDialog.showModal();
  $('#apply-status').textContent = 'rebuilding, committing, and pushing…';
  try {
    const result = await streamApply();
    state.draft = []; state.metadataDirty = []; state.selected.clear(); state.releasePending = false;
    $('#apply-status').textContent = `${result.appliedCount} publication changes and ${result.metadataCount} metadata updates published.`;
    $('#publish-title').textContent = 'published'; $('#publish-result').textContent = 'The push completed and GitHub Pages deployment was triggered.';
    $('#close-publish').disabled = false; $('#finish-publish').disabled = false;
    renderDraft(); await loadShoots(state.activeShoot?.path);
  } catch (error) {
    appendPublishLog(error.message, 'error'); $('#apply-status').textContent = error.message;
    $('#publish-title').textContent = 'publication failed'; $('#publish-result').textContent = 'Changes were kept. Fix the error and try Apply again.';
    state.releasePending = true; button.disabled = false; $('#discard-all').disabled = false;
  } finally { $('#close-publish').disabled = false; $('#finish-publish').disabled = false; }
});

async function selectShoot(shoot) {
  state.view = 'shoots'; state.activeShoot = shoot; state.selected.clear(); renderShoots();
  $('.toolbar-actions').hidden = false; $('#tag-manager').hidden = true; gridNode.hidden = false;
  titleNode.textContent = shoot.name;
  metaNode.textContent = `folder ${shoot.sourceTier} · ${shoot.publishedCount} on current site · ${shoot.metadataCount} metadata files`;
  emptyNode.hidden = false; emptyNode.textContent = 'loading photos'; gridNode.replaceChildren();
  await reloadPhotos();
}

async function selectCollection(view) {
  state.view = view; state.activeShoot = null; state.selected.clear(); renderShoots();
  const tagsMode = view === 'tags';
  titleNode.textContent = tagsMode ? 'tag manager' : (view === 'issues' ? 'problem photos' : 'all photos');
  metaNode.textContent = tagsMode ? 'rename, merge, or remove tags across the source library' : (view === 'issues' ? 'missing analysis, embeddings, visual metrics, tags, or descriptions' : `${state.shoots.reduce((sum, shoot) => sum + shoot.photoCount, 0)} photos across ${state.shoots.length} shoots`);
  $('.toolbar-actions').hidden = tagsMode; $('#tag-manager').hidden = !tagsMode; gridNode.hidden = tagsMode;
  emptyNode.hidden = tagsMode; emptyNode.textContent = 'loading photos'; gridNode.replaceChildren();
  if (tagsMode) { await loadTags(); return; }
  await reloadPhotos();
}

$('#view-shoots').addEventListener('click', () => selectShoot(state.shoots[0]));
$('#view-all').addEventListener('click', () => selectCollection('all'));
$('#view-issues').addEventListener('click', () => selectCollection('issues'));
$('#view-tags').addEventListener('click', () => selectCollection('tags'));
$('#tag-search').addEventListener('input', renderTags);

async function loadShoots(preferred = null) {
  state.shoots = (await request('/api/shoots')).shoots; renderShoots();
  if (state.view !== 'shoots') { await selectCollection(state.view); return; }
  const shoot = state.shoots.find((item) => item.path === preferred) || state.shoots[0];
  if (shoot) await selectShoot(shoot);
}

visibilityNode.addEventListener('change', renderPhotos);
tagFilterNode.addEventListener('input', renderPhotos);
Promise.all([request('/api/draft'), request('/api/shoots')]).then(async ([draft, shoots]) => {
  state.draft = draft.draft; state.metadataDirty = draft.metadataDirty; state.releasePending = draft.releasePending; state.shoots = shoots.shoots; renderDraft(); renderShoots();
  if (state.shoots.length) await selectShoot(state.shoots[0]);
}).catch(() => { emptyNode.textContent = 'could not read the archive'; countNode.textContent = 'offline'; });
