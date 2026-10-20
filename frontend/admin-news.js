const API = '/api/admin/news';

const $ = (sel) => document.querySelector(sel);
const listView = $('#listView');
const editorView = $('#editorView');
const listStatus = $('#listStatus');
const editorStatus = $('#editorStatus');
const postsTable = $('#postsTable');
const postsBody = $('#postsBody');
const form = $('#newsForm');
const primaryBtn = $('#primaryBtn');
const secondaryBtn = $('#secondaryBtn');
const deleteBtn = $('#deleteBtn');
const viewLink = $('#viewLink');

let posts = [];
let current = null; // the post being edited (null = new article)
let statusTimer = null;

// ------------------------------------------------------------ helpers ---
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString('bg-BG', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function flash(el, text, isError = false, resetText = '') {
  clearTimeout(statusTimer);
  el.classList.toggle('error', isError);
  el.classList.toggle('saved', !isError);
  el.textContent = text;
  statusTimer = setTimeout(() => {
    el.classList.remove('error', 'saved');
    el.textContent = resetText;
  }, isError ? 5000 : 2500);
}

async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options
  });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

// --------------------------------------------------------------- list ---
function totalText() {
  const published = posts.filter(p => p.status === 'published').length;
  return `Общо: ${posts.length} · Публикувани: ${published} · Чернови: ${posts.length - published}`;
}

function rowHtml(p) {
  const badges = p.youtube_id ? '<span class="mini-badge">▶ видео</span>' : '';
  const published = p.status === 'published';
  return `
    <tr data-id="${p.id}">
      <td class="title-cell"><strong>${escapeHtml(p.title)}</strong>${badges}</td>
      <td>${escapeHtml(p.category || '—')}</td>
      <td><span class="status-pill ${published ? 'is-published' : 'is-draft'}">${published ? 'Публикувана' : 'Чернова'}</span></td>
      <td>${published ? formatDate(p.published_at) : '—'}</td>
      <td>
        <div class="row-actions">
          <button class="btn btn-outline btn-sm js-edit" type="button">Редактирай</button>
          ${published ? `<a class="btn btn-outline btn-sm" href="/news/${encodeURIComponent(p.slug)}" target="_blank" rel="noopener">Виж ↗</a>` : ''}
        </div>
      </td>
    </tr>`;
}

function renderList() {
  postsBody.innerHTML = posts.length
    ? posts.map(rowHtml).join('')
    : '<tr><td colspan="5" class="empty-state">Все още няма статии. Натиснете „Нова статия“.</td></tr>';
}

async function loadPosts() {
  listStatus.classList.remove('error', 'saved');
  listStatus.textContent = 'Зареждане...';
  postsTable.hidden = true;
  try {
    const { res, data } = await api(API);
    if (!res.ok || !data.ok) throw new Error('api');
    posts = data.posts || [];
    renderList();
    listStatus.textContent = totalText();
    postsTable.hidden = false;
  } catch (err) {
    listStatus.classList.add('error');
    listStatus.textContent = 'Неуспешно зареждане. Провери дали backend-ът работи.';
  }
}

postsBody.addEventListener('click', (e) => {
  const btn = e.target.closest('.js-edit');
  const tr = e.target.closest('tr[data-id]');
  if (!btn || !tr) return;
  const post = posts.find(p => p.id === Number(tr.dataset.id));
  if (post) openEditor(post);
});

$('#refreshBtn').addEventListener('click', loadPosts);
$('#newBtn').addEventListener('click', () => openEditor(null));

// ------------------------------------------------------------- editor ---
const quill = new Quill('#editor', {
  theme: 'snow',
  placeholder: 'Напиши статията тук…',
  modules: {
    toolbar: '#toolbar',
    // Photos dropped or pasted into the text are uploaded (and resized) instead of
    // being embedded as huge inline data.
    uploader: {
      mimetypes: ['image/jpeg', 'image/png', 'image/webp'],
      handler: (range, files) => insertImages([...files], range.index)
    }
  },
  // Only what the server keeps anyway (see sanitize_html in the backend).
  formats: ['header', 'bold', 'italic', 'underline', 'strike', 'list', 'blockquote', 'link', 'image']
});

function getBodyHtml() {
  if (quill.getText().trim() === '' && !quill.root.querySelector('img')) return '';
  // Quill writes &nbsp; next to formatted words, which blocks line wrapping on the site.
  return quill.getSemanticHTML()
    .replace(/&nbsp;/g, ' ')
    .replace(/<img[^>]*src="data:[^"]*"[^>]*>/g, ''); // pasted inline images cannot be saved
}

function setBodyHtml(html) {
  quill.setContents(html ? quill.clipboard.convert({ html }) : [], 'silent');
}

function clearErrors() {
  form.querySelectorAll('.field-error').forEach(el => { el.textContent = ''; });
}

function showErrors(errors) {
  Object.entries(errors || {}).forEach(([field, msg]) => {
    const el = form.querySelector(`[data-error-for="${field}"]`);
    if (el) el.textContent = msg;
  });
}

function refreshButtons() {
  const published = current && current.status === 'published';
  primaryBtn.textContent = published ? 'Запази промените' : 'Публикувай';
  secondaryBtn.textContent = published ? 'Върни в чернова' : 'Запази като чернова';
  deleteBtn.hidden = !current;
  viewLink.hidden = !published;
  if (published) viewLink.href = `/news/${encodeURIComponent(current.slug)}`;
  $('#editorTitle').textContent = current ? 'Редакция на статия' : 'Нова статия';
}

function openEditor(post) {
  current = post;
  clearErrors();
  editorStatus.textContent = '';
  form.elements.title.value = post?.title || '';
  form.elements.category.value = post?.category || '';
  setCover(post?.cover_image, post?.cover_thumb);
  form.elements.excerpt.value = post?.excerpt || '';
  form.elements.youtube_url.value = post?.youtube_url || '';
  setBodyHtml(post?.body || '');
  refreshButtons();
  listView.hidden = true;
  editorView.hidden = false;
  window.scrollTo(0, 0);
  form.elements.title.focus();
}

async function backToList() {
  closeEmojiPanel();
  editorView.hidden = true;
  listView.hidden = false;
  await loadPosts();
}
$('#backBtn').addEventListener('click', backToList);

// ------------------------------------------------------------- photos ---
const MAX_PHOTO_BYTES = 10 * 1024 * 1024;
const coverFile = $('#coverFile');
const coverPreview = $('#coverPreview');
const coverRemove = $('#coverRemove');
const bodyFile = $('#bodyFile');
let insertAt = 0;

async function uploadImage(file) {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    throw new Error('Позволени са само JPG, PNG и WebP снимки.');
  }
  if (file.size > MAX_PHOTO_BYTES) throw new Error('Снимката е над 10 MB.');
  const body = new FormData();
  body.append('image', file);
  let res, data;
  try {
    res = await fetch('/api/admin/uploads', { method: 'POST', body }); // no Content-Type: the browser sets it
    data = await res.json().catch(() => ({}));
  } catch (err) {
    throw new Error('Няма връзка със сървъра. Опитай пак.');
  }
  if (!res.ok || !data.ok) throw new Error(data.error || 'Неуспешно качване.');
  return data;
}

function setUploading(on, text = '') {
  [primaryBtn, secondaryBtn, deleteBtn, $('#coverBtn'), $('#imageBtn')].forEach(b => { b.disabled = on; });
  if (on) {
    clearTimeout(statusTimer);
    editorStatus.classList.remove('error', 'saved');
    editorStatus.textContent = text;
  }
}

function setCover(url, thumb) {
  form.elements.cover_image.value = url || '';
  coverPreview.hidden = !url;
  if (url) coverPreview.src = thumb || url;
  coverRemove.hidden = !url;
}

$('#coverBtn').addEventListener('click', () => coverFile.click());
coverRemove.addEventListener('click', () => setCover(''));
coverFile.addEventListener('change', async () => {
  const file = coverFile.files[0];
  coverFile.value = '';
  if (!file) return;
  setUploading(true, 'Качване на снимката…');
  try {
    const data = await uploadImage(file);
    setCover(data.url, data.thumb);
    form.querySelector('[data-error-for="cover_image"]').textContent = '';
    flash(editorStatus, 'Снимката е качена ✓ (запази статията, за да се приложи)');
  } catch (err) {
    flash(editorStatus, err.message, true);
  } finally {
    setUploading(false);
  }
});

async function insertImages(files, index) {
  files = files.filter(f => f && f.type && f.type.startsWith('image/'));
  if (!files.length) return;
  setUploading(true);
  let added = 0;
  try {
    for (const file of files) {
      setUploading(true, `Качване на снимка ${added + 1} от ${files.length}…`);
      const data = await uploadImage(file);
      quill.insertEmbed(index, 'image', data.url, 'user');
      index += 1;
      added += 1;
    }
    quill.setSelection(index, 0, 'silent');
    flash(editorStatus, added === 1 ? 'Снимката е добавена ✓' : `${added} снимки са добавени ✓`);
  } catch (err) {
    flash(editorStatus, added ? `Добавени: ${added}. ${err.message}` : err.message, true);
  } finally {
    setUploading(false);
  }
}

const imageBtn = $('#imageBtn');
imageBtn.addEventListener('mousedown', (e) => e.preventDefault());
imageBtn.addEventListener('click', () => {
  insertAt = quill.getSelection(true).index; // remember where the cursor is
  bodyFile.click();
});
bodyFile.addEventListener('change', () => {
  const files = [...bodyFile.files];
  bodyFile.value = '';
  insertImages(files, insertAt);
});

function setBusy(busy) {
  [primaryBtn, secondaryBtn, deleteBtn].forEach(b => { b.disabled = busy; });
}

async function save(status) {
  clearErrors();
  const f = form.elements;
  const payload = {
    title: f.title.value,
    category: f.category.value,
    cover_image: f.cover_image.value,
    excerpt: f.excerpt.value,
    youtube_url: f.youtube_url.value,
    body: getBodyHtml(),
    status
  };

  setBusy(true);
  try {
    const { res, data } = await api(current ? `${API}/${current.id}` : API, {
      method: current ? 'PATCH' : 'POST',
      body: JSON.stringify(payload)
    });
    if (!res.ok || !data.ok) {
      if (data.errors) showErrors(data.errors);
      flash(editorStatus, data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно запазване.'), true);
      return;
    }
    current = data.post;
    refreshButtons();
    // Show what the server actually saved (e.g. cleaned-up text).
    setBodyHtml(current.body);
    flash(editorStatus, current.status === 'published' ? 'Публикувана ✓' : 'Запазена като чернова ✓');
  } catch (err) {
    flash(editorStatus, 'Няма връзка със сървъра. Опитай пак.', true);
  } finally {
    setBusy(false);
  }
}

primaryBtn.addEventListener('click', () => save('published'));
secondaryBtn.addEventListener('click', () => save('draft'));

deleteBtn.addEventListener('click', async () => {
  if (!current) return;
  if (!confirm(`Да изтрия ли статията „${current.title}“? Това не може да се върне.`)) return;
  setBusy(true);
  try {
    const { res, data } = await api(`${API}/${current.id}`, { method: 'DELETE' });
    if (!res.ok || !data.ok) throw new Error('delete');
    current = null;
    await backToList();
  } catch (err) {
    flash(editorStatus, 'Неуспешно изтриване. Опитай пак.', true);
  } finally {
    setBusy(false);
  }
});

form.addEventListener('submit', (e) => e.preventDefault());

// ------------------------------------------------------------- emojis ---
const EMOJIS = ['⚽', '🏆', '🥇', '🥈', '🥉', '🎉', '👏', '💪', '🔥', '⭐', '💙', '❤️', '😀', '😃', '😊', '😍', '😎', '🤩',
  '👍', '🙌', '🤝', '🏃', '👟', '🥅', '🧤', '🏟️', '📅', '📍', '⏰', '📣', '✅', '➡️', '🎯', '🚀'];
const emojiPanel = $('#emojiPanel');
const emojiBtn = $('#emojiBtn');
let emojiTarget = 'quill'; // which field gets the emoji: 'quill' or a text input / textarea

emojiPanel.innerHTML = EMOJIS.map(e => `<button type="button" class="emoji-item">${e}</button>`).join('');

form.addEventListener('focusin', (e) => {
  if (e.target.matches('input, textarea')) emojiTarget = e.target;
});
quill.on('selection-change', (range) => { if (range) emojiTarget = 'quill'; });

function closeEmojiPanel() { emojiPanel.hidden = true; }

emojiBtn.addEventListener('mousedown', (e) => e.preventDefault());
emojiBtn.addEventListener('click', () => { emojiPanel.hidden = !emojiPanel.hidden; });
emojiPanel.addEventListener('mousedown', (e) => e.preventDefault()); // keep the cursor where it is

emojiPanel.addEventListener('click', (e) => {
  const item = e.target.closest('.emoji-item');
  if (!item) return;
  const emoji = item.textContent;

  if (emojiTarget === 'quill' || !emojiTarget) {
    const range = quill.getSelection(true);
    quill.insertText(range.index, emoji, 'user');
    quill.setSelection(range.index + emoji.length, 0, 'user');
  } else {
    const el = emojiTarget;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? start;
    if (el.value.length - (end - start) + emoji.length <= (el.maxLength > 0 ? el.maxLength : Infinity)) {
      el.setRangeText(emoji, start, end, 'end');
    }
    el.focus();
  }
});

document.addEventListener('click', (e) => {
  if (!emojiPanel.hidden && !e.target.closest('#emojiPanel') && !e.target.closest('#emojiBtn')) closeEmojiPanel();
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeEmojiPanel(); });

loadPosts();
