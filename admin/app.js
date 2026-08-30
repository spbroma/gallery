const state = { shoots: [], photos: [], activeShoot: null };
const shootsNode = document.querySelector('#shoots');
const gridNode = document.querySelector('#grid');
const emptyNode = document.querySelector('#empty');
const titleNode = document.querySelector('#shoot-title');
const metaNode = document.querySelector('#shoot-meta');
const countNode = document.querySelector('#result-count');
const visibilityNode = document.querySelector('#visibility-filter');
const tagFilterNode = document.querySelector('#tag-filter');
const template = document.querySelector('#photo-template');
const editor = document.querySelector('#editor');
const editorName = document.querySelector('#editor-name');
const editorImage = document.querySelector('#editor-image');
const editorPublished = document.querySelector('#editor-published');
const editorDescription = document.querySelector('#editor-description');
const editorShot = document.querySelector('#editor-shot');
const editorPeople = document.querySelector('#editor-people');
const manualTagsNode = document.querySelector('#manual-tags');
const generatedTagsNode = document.querySelector('#generated-tags');
const newTagNode = document.querySelector('#new-tag');
const saveStatusNode = document.querySelector('#save-status');
let editingPhoto = null;
let draftManualTags = [];
let draftGeneratedTags = [];

function renderShoots() {
  shootsNode.replaceChildren(...state.shoots.map((shoot) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `shoot-button${state.activeShoot?.path === shoot.path ? ' active' : ''}`;
    button.innerHTML = `<span class="shoot-name"></span><span class="shoot-count"></span>`;
    button.querySelector('.shoot-name').textContent = shoot.name;
    button.querySelector('.shoot-count').textContent = `${shoot.photoCount} photos · folder ${shoot.sourceTier}`;
    button.addEventListener('click', () => selectShoot(shoot));
    return button;
  }));
}

function visiblePhotos() {
  const visibility = visibilityNode.value;
  const query = tagFilterNode.value.trim().toLowerCase();
  return state.photos.filter((photo) => {
    if (visibility === 'published' && !photo.published) return false;
    if (visibility === 'hidden' && photo.published) return false;
    const tags = [...photo.manualTags, ...photo.generatedTags];
    return !query || tags.some((tag) => tag.includes(query));
  });
}

function renderPhotos() {
  const photos = visiblePhotos();
  countNode.textContent = `${photos.length} photos`;
  emptyNode.hidden = photos.length > 0;
  if (state.activeShoot && photos.length === 0) emptyNode.textContent = 'no photos match the filters';
  gridNode.replaceChildren(...photos.map((photo) => {
    const card = template.content.firstElementChild.cloneNode(true);
    card.classList.toggle('published', photo.published);
    card.querySelector('img').src = photo.preview;
    card.querySelector('.photo-name').textContent = photo.file;
    const tags = [
      ...photo.manualTags.map((tag) => ({ tag, manual: true })),
      ...photo.generatedTags.filter((tag) => !photo.manualTags.includes(tag)).map((tag) => ({ tag, manual: false })),
    ];
    card.querySelector('.tag-list').replaceChildren(...tags.slice(0, 8).map(({ tag, manual }) => {
      const node = document.createElement('span');
      node.className = `tag${manual ? ' manual' : ''}`;
      node.textContent = tag;
      return node;
    }));
    card.addEventListener('click', () => openEditor(photo));
    return card;
  }));
}

function renderEditorTags() {
  manualTagsNode.replaceChildren(...draftManualTags.map((tag) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.title = 'Remove manual tag';
    button.textContent = `${tag} ×`;
    button.addEventListener('click', () => {
      draftManualTags = draftManualTags.filter((item) => item !== tag);
      renderEditorTags();
    });
    return button;
  }));
  generatedTagsNode.replaceChildren(...draftGeneratedTags.filter((tag) => !draftManualTags.includes(tag)).map((tag) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.title = 'Make this tag manual';
    button.textContent = tag;
    button.addEventListener('click', () => {
      draftManualTags = [...draftManualTags, tag];
      draftGeneratedTags = draftGeneratedTags.filter((item) => item !== tag);
      renderEditorTags();
    });
    return button;
  }));
}

function openEditor(photo) {
  editingPhoto = photo;
  draftManualTags = [...photo.manualTags];
  draftGeneratedTags = [...photo.generatedTags];
  editorName.textContent = photo.file;
  editorImage.src = photo.preview;
  editorPublished.checked = photo.published;
  editorDescription.value = photo.description || '';
  editorShot.value = photo.shotScale || 'unknown';
  editorPeople.value = photo.peopleCount ?? 0;
  newTagNode.value = '';
  saveStatusNode.textContent = photo.hasMetadata ? 'metadata exists' : 'metadata will be created on save';
  renderEditorTags();
  editor.showModal();
}

function addManualTag() {
  const tag = newTagNode.value.trim().toLowerCase();
  if (!tag) return;
  if (!draftManualTags.includes(tag)) draftManualTags.push(tag);
  draftGeneratedTags = draftGeneratedTags.filter((item) => item !== tag);
  newTagNode.value = '';
  renderEditorTags();
}

document.querySelector('#add-tag').addEventListener('click', addManualTag);
newTagNode.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    addManualTag();
  }
});
document.querySelector('#promote-all').addEventListener('click', () => {
  draftManualTags = [...new Set([...draftManualTags, ...draftGeneratedTags])];
  draftGeneratedTags = [];
  renderEditorTags();
});
document.querySelector('#save-photo').addEventListener('click', async () => {
  if (!editingPhoto || !state.activeShoot) return;
  saveStatusNode.textContent = 'saving';
  const response = await fetch('/api/photo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      shoot: state.activeShoot.path,
      id: editingPhoto.id,
      published: editorPublished.checked,
      manualTags: draftManualTags,
      generatedTags: draftGeneratedTags,
      description: editorDescription.value,
      shotScale: editorShot.value,
      peopleCount: editorPeople.value,
    }),
  });
  if (!response.ok) {
    saveStatusNode.textContent = 'could not save';
    return;
  }
  const { photo } = await response.json();
  state.photos = state.photos.map((item) => item.id === photo.id ? photo : item);
  state.activeShoot.metadataCount += editingPhoto.hasMetadata ? 0 : 1;
  state.activeShoot.publishedCount += Number(photo.published) - Number(editingPhoto.published);
  renderShoots();
  renderPhotos();
  editor.close();
});

async function selectShoot(shoot) {
  state.activeShoot = shoot;
  renderShoots();
  titleNode.textContent = shoot.name;
  metaNode.textContent = `folder ${shoot.sourceTier} · ${shoot.publishedCount} published · ${shoot.metadataCount} metadata files`;
  emptyNode.hidden = false;
  emptyNode.textContent = 'loading photos';
  gridNode.replaceChildren();
  const response = await fetch(`/api/photos?shoot=${encodeURIComponent(shoot.path)}`);
  state.photos = (await response.json()).photos;
  renderPhotos();
}

visibilityNode.addEventListener('change', renderPhotos);
tagFilterNode.addEventListener('input', renderPhotos);

fetch('/api/shoots')
  .then((response) => response.json())
  .then(({ shoots }) => {
    state.shoots = shoots;
    renderShoots();
    if (shoots.length) selectShoot(shoots[0]);
  })
  .catch(() => {
    emptyNode.textContent = 'could not read the archive';
    countNode.textContent = 'offline';
  });
