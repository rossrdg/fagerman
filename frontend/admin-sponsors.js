// Админ „Партньори“: лого + текст за pop-up, подредба, скриване.
const API = '/api/admin/sponsors';
const MAX_BYTES = 20 * 1024 * 1024;
const $ = (sel) => document.querySelector(sel);

const statusEl = $('#status');
const listEl = $('#sponsorList');
const form = $('#sponsorForm');
const saveBtn = $('#saveBtn');
const cancelBtn = $('#cancelBtn');
const logoInput = $('#f-logo');
const logoPreview = $('#logoPreview');

let sponsors = [];
let editing = null;
let statusTimer = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function flash(text, isError = false) {
  clearTimeout(statusTimer);
  statusEl.classList.toggle('error', isError);
  statusEl.classList.toggle('saved', !isError);
  statusEl.textContent = text;
  statusTimer = setTimeout(() => {
    statusEl.classList.remove('error', 'saved');
    statusEl.textContent = `Партньори: ${sponsors.length}`;
  }, isError ? 5000 : 2500);
}

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

function clearErrors() {
  form.querySelectorAll('.field-error').forEach(e => { e.textContent = ''; });
}

function showErrors(errors) {
  clearErrors();
  Object.entries(errors || {}).forEach(([field, msg]) => {
    const target = form.querySelector(`[data-error-for="${field}"]`);
    if (target) target.textContent = msg;
  });
}

// ------------------------------------------------------------ форма ---
function resetForm() {
  editing = null;
  clearErrors();
  $('#formTitle').textContent = 'Нов партньор';
  $('#f-name').value = '';
  $('#f-website').value = '';
  $('#f-headline').value = '';
  $('#f-body').value = '';
  $('#f-visible').checked = true;
  logoInput.value = '';
  logoPreview.hidden = true;
  $('#bodyCount').textContent = '0';
  saveBtn.textContent = 'Добави';
  cancelBtn.hidden = true;
}

function startEdit(s) {
  editing = s;
  clearErrors();
  $('#formTitle').textContent = `Редакция: ${s.name}`;
  $('#f-name').value = s.name;
  $('#f-website').value = s.website;
  $('#f-headline').value = s.headline;
  $('#f-body').value = s.body;
  $('#f-visible').checked = s.is_visible;
  logoInput.value = '';
  logoPreview.src = s.logo;
  logoPreview.hidden = false;
  $('#bodyCount').textContent = s.body.length;
  saveBtn.textContent = 'Запази';
  cancelBtn.hidden = false;
  form.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

logoInput.addEventListener('change', () => {
  const file = logoInput.files[0];
  if (!file) return;
  if (file.type.startsWith('image/') && file.type !== 'image/heic' && file.type !== 'image/heif') {
    logoPreview.src = URL.createObjectURL(file);
    logoPreview.hidden = false;
  }
});

async function save() {
  clearErrors();
  const file = logoInput.files[0];
  if (file && file.size > MAX_BYTES) { showErrors({ logo: 'Файлът е над 20 MB.' }); return; }

  const body = new FormData();
  body.append('name', $('#f-name').value);
  body.append('website', $('#f-website').value);
  body.append('headline', $('#f-headline').value);
  body.append('body', $('#f-body').value);
  body.append('is_visible', $('#f-visible').checked ? '1' : '0');
  if (file) body.append('logo', file);

  saveBtn.disabled = true;
  try {
    // без Content-Type: браузърът го слага сам за multipart
    const res = await fetch(editing ? `${API}/${editing.id}` : API, { method: editing ? 'PATCH' : 'POST', body });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      showErrors(data.errors);
      flash(data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно запазване.'), true);
      return;
    }
    const message = editing ? 'Запазено ✓' : 'Добавен ✓';
    resetForm();
    await load();
    flash(message);
  } catch (err) {
    flash('Няма връзка със сървъра. Опитай пак.', true);
  } finally {
    saveBtn.disabled = false;
  }
}

// ----------------------------------------------------------- списък ---
function button(text, onClick, danger = false, disabled = false) {
  const b = el('button', 'btn btn-outline btn-sm' + (danger ? ' btn-danger-text' : ''), text);
  b.type = 'button';
  b.disabled = disabled;
  b.addEventListener('click', onClick);
  return b;
}

async function move(s, direction) {
  const { res, data } = await api(`${API}/${s.id}/move`, { method: 'POST', body: JSON.stringify({ direction }) });
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешна промяна.', true); return; }
  await load();
}

async function remove(s) {
  if (!confirm(`Да изтрия ли партньора „${s.name}“? Това не може да се върне.`)) return;
  const { res, data } = await api(`${API}/${s.id}`, { method: 'DELETE' });
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно изтриване.', true); return; }
  if (editing && editing.id === s.id) resetForm();
  await load();
  flash('Изтрит ✓');
}

function renderList() {
  listEl.textContent = '';
  if (!sponsors.length) {
    listEl.append(el('p', 'user-hint', 'Още няма партньори. Добавете първия с формата отгоре.'));
    return;
  }
  sponsors.forEach((s, i) => {
    const row = el('div', 'group-row');
    const img = el('img', 'sponsor-thumb');
    img.src = s.logo; img.alt = '';
    const info = el('div', 'grow');
    const name = el('strong', '', s.name);
    if (!s.is_visible) name.append(el('span', 'mini-badge', 'скрит'));
    info.append(name);
    if (s.headline) info.append(el('br'), el('small', '', s.headline));
    row.append(img, info,
      button('↑', () => move(s, 'up'), false, i === 0),
      button('↓', () => move(s, 'down'), false, i === sponsors.length - 1),
      button('Редактирай', () => startEdit(s)),
      button('Изтрий', () => remove(s), true));
    listEl.append(row);
  });
}

async function load() {
  const { res, data } = await api(API);
  if (!res.ok || !data.ok) throw new Error('api');
  sponsors = data.sponsors;
  renderList();
  statusEl.classList.remove('error', 'saved');
  statusEl.textContent = `Партньори: ${sponsors.length}`;
}

$('#f-body').addEventListener('input', () => { $('#bodyCount').textContent = $('#f-body').value.length; });
saveBtn.addEventListener('click', save);
cancelBtn.addEventListener('click', resetForm);
form.addEventListener('submit', (e) => e.preventDefault());

resetForm();
load().catch(() => {
  statusEl.classList.add('error');
  statusEl.textContent = 'Неуспешно зареждане. Провери дали backend-ът работи.';
});
