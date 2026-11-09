// Админ „Магазин“: артикули (име, снимка, размери и цени, персонализация, видимост, подредба).
const API = '/api/admin/shop/products';
const $ = (sel) => document.querySelector(sel);

const statusEl = $('#status');
const bodyEl = $('#productsBody');
const tableEl = $('#productsTable');
const emptyEl = $('#emptyState');
const saveBtn = $('#saveBtn');
const cancelBtn = $('#cancelBtn');

const f = {
  name: $('#f-name'), mode: $('#f-mode'), child: $('#f-price-child'), adult: $('#f-price-adult'),
  pers: $('#f-pers'), fee: $('#f-fee'), visible: $('#f-visible'), file: $('#f-image')
};

let products = [];
let meta = { child_sizes: [], adult_sizes: [], one_size_label: 'Един размер', default_fee: 5 };
let editingId = null;
let imageUrl = null;      // адрес на качената снимка (празно = без снимка)
let imageThumb = null;
let uploading = false;
let statusTimer = null;
let flashing = false;     // докато тече съобщение, прерисуването на списъка не го изтрива

function summary() {
  const shown = products.filter(p => p.is_visible).length;
  return `Артикули: ${products.length} · показват се в магазина: ${shown} · скрити: ${products.length - shown}`;
}

function flash(text, isError = false) {
  clearTimeout(statusTimer);
  flashing = true;
  statusEl.classList.toggle('error', isError);
  statusEl.classList.toggle('saved', !isError);
  statusEl.textContent = text;
  statusTimer = setTimeout(() => {
    flashing = false;
    statusEl.classList.remove('error', 'saved');
    statusEl.textContent = summary();
  }, isError ? 5000 : 2500);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

function eur(n) {
  if (n === null || n === undefined) return '';
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace('.', ',');
}

function clearErrors() {
  document.querySelectorAll('#productForm .field-error').forEach(e => { e.textContent = ''; });
}

function showErrors(errors) {
  clearErrors();
  Object.entries(errors || {}).forEach(([field, msg]) => {
    const target = document.querySelector(`#productForm [data-error-for="${field}"]`);
    if (target) target.textContent = msg;
  });
}

// ------------------------------------------------------------- форма ---
function sizesFor(mode) {
  if (mode === 'child') return meta.child_sizes;
  if (mode === 'adult') return meta.adult_sizes;
  if (mode === 'both') return [...meta.child_sizes, ...meta.adult_sizes];
  return [meta.one_size_label];
}

function checkedSoldOut() {
  return [...document.querySelectorAll('#soldOutBoxes input:checked')].map(i => i.value);
}

function renderSoldOut(selected = []) {
  const box = $('#soldOutBoxes');
  box.textContent = '';
  sizesFor(f.mode.value).forEach(size => {
    const label = el('label', 'check-item');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = size;
    input.checked = selected.includes(size);
    label.append(input, document.createTextNode(size));
    box.append(label);
  });
}

function syncMode() {
  const mode = f.mode.value;
  $('#childPriceField').hidden = !(mode === 'both' || mode === 'child');
  $('#adultPriceField').hidden = mode === 'child';
  $('#adultPriceLabel').textContent = mode === 'one' ? 'Цена (€) *' : 'Цена възрастен (€) *';
  const hints = {
    both: `Детски: ${meta.child_sizes.join(', ')} · Възрастни: ${meta.adult_sizes.join(', ')}`,
    child: `Детски: ${meta.child_sizes.join(', ')}`,
    adult: `Възрастни: ${meta.adult_sizes.join(', ')}`,
    one: 'Без избор на размер — клиентът просто добавя артикула.'
  };
  $('#sizesHint').textContent = hints[mode];
  renderSoldOut(checkedSoldOut());
}

function syncPers() {
  $('#feeField').hidden = !f.pers.checked;
}

function setImage(url, thumb) {
  imageUrl = url || null;
  imageThumb = thumb || null;
  const img = $('#imagePreview');
  img.hidden = !imageUrl;
  if (imageUrl) img.src = imageThumb || imageUrl;
  $('#imageRemove').hidden = !imageUrl;
  $('#imageBtnText').textContent = imageUrl ? 'Смени снимката' : 'Избери снимка';
}

function resetForm() {
  editingId = null;
  f.name.value = '';
  f.mode.value = 'both';
  f.child.value = '';
  f.adult.value = '';
  f.pers.checked = false;
  f.fee.value = eur(meta.default_fee);
  f.visible.checked = true;
  f.file.value = '';
  setImage(null, null);
  syncMode();
  syncPers();
  clearErrors();
  $('#formTitle').textContent = 'Нов артикул';
  saveBtn.textContent = 'Добави';
  cancelBtn.hidden = true;
}

function editProduct(p) {
  editingId = p.id;
  f.name.value = p.name;
  f.mode.value = p.size_mode;
  f.child.value = eur(p.price_child);
  f.adult.value = eur(p.price_adult);
  f.pers.checked = p.allows_personalization;
  f.fee.value = eur(p.personalization_fee);
  f.visible.checked = p.is_visible;
  f.file.value = '';
  setImage(p.image, p.thumb);
  syncMode();
  renderSoldOut(p.sold_out_sizes);
  syncPers();
  clearErrors();
  $('#formTitle').textContent = 'Редакция на артикул';
  saveBtn.textContent = 'Запази промените';
  cancelBtn.hidden = false;
  $('#productForm').scrollIntoView({ behavior: 'smooth', block: 'start' });
  f.name.focus({ preventScroll: true });
}

function formValues() {
  return {
    name: f.name.value,
    size_mode: f.mode.value,
    price_child: f.child.value,
    price_adult: f.adult.value,
    allows_personalization: f.pers.checked,
    personalization_fee: f.fee.value,
    sold_out_sizes: checkedSoldOut(),
    image: imageUrl || '',
    is_visible: f.visible.checked
  };
}

async function save() {
  if (uploading) { flash('Изчакайте качването на снимката.', true); return; }
  saveBtn.disabled = true;
  try {
    const url = editingId ? `${API}/${editingId}` : API;
    const { res, data } = await api(url, { method: editingId ? 'PATCH' : 'POST', body: JSON.stringify(formValues()) });
    if (!res.ok) {
      if (data.errors) showErrors(data.errors);
      flash(data.error || 'Проверете маркираните полета.', true);
      return;
    }
    flash(editingId ? 'Промените са записани.' : 'Артикулът е добавен.');
    resetForm();
    await load();
  } catch (err) {
    flash('Няма връзка със сървъра.', true);
  } finally {
    saveBtn.disabled = false;
  }
}

const MAX_PHOTO_BYTES = 20 * 1024 * 1024;

async function uploadImage(file) {
  if (file.size > MAX_PHOTO_BYTES) { showErrors({ image: 'Снимката е над 20 MB.' }); f.file.value = ''; return; }
  uploading = true;
  saveBtn.disabled = true;
  $('#imageBtnText').textContent = 'Качване...';
  f.file.disabled = true;
  try {
    const body = new FormData();
    body.append('image', file);
    const res = await fetch('/api/admin/uploads', { method: 'POST', body }); // без Content-Type: браузърът го слага
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showErrors({ image: data.error || 'Снимката не се качи.' });
      return;
    }
    clearErrors();
    setImage(data.url, data.thumb);
  } catch (err) {
    showErrors({ image: 'Снимката не се качи. Опитайте пак.' });
  } finally {
    uploading = false;
    saveBtn.disabled = false;
    f.file.disabled = false;
    f.file.value = '';
    $('#imageBtnText').textContent = imageUrl ? 'Смени снимката' : 'Избери снимка';
  }
}

// ------------------------------------------------------------ списък ---
function priceText(p) {
  if (p.size_mode === 'both') return `дет. ${eur(p.price_child)} € · възр. ${eur(p.price_adult)} €`;
  if (p.size_mode === 'child') return `дет. ${eur(p.price_child)} €`;
  if (p.size_mode === 'adult') return `възр. ${eur(p.price_adult)} €`;
  return `${eur(p.price_adult)} €`;
}

function sizesText(p) {
  return { both: 'Детски и възрастни', child: 'Само детски', adult: 'Само възрастни', one: 'Един размер' }[p.size_mode];
}

function render() {
  if (!flashing) statusEl.textContent = summary();
  tableEl.hidden = !products.length;
  emptyEl.hidden = products.length > 0;
  bodyEl.textContent = '';

  products.forEach((p, index) => {
    const tr = el('tr', p.is_visible ? '' : 'is-hidden');

    const order = el('td');
    const box = el('div', 'shop-order');
    const up = el('button', '', '↑');
    up.type = 'button'; up.title = 'По-нагоре'; up.disabled = index === 0;
    up.addEventListener('click', () => move(p.id, 'up'));
    const down = el('button', '', '↓');
    down.type = 'button'; down.title = 'По-надолу'; down.disabled = index === products.length - 1;
    down.addEventListener('click', () => move(p.id, 'down'));
    box.append(el('span', '', String(index + 1)), up, down);
    order.append(box);

    const photo = el('td');
    if (p.thumb) {
      const img = el('img', 'shop-thumb');
      img.src = p.thumb; img.alt = ''; img.loading = 'lazy';
      photo.append(img);
    } else {
      photo.append(el('div', 'shop-nothumb', 'няма снимка'));
    }

    const name = el('td', 'title-cell');
    name.append(el('strong', '', p.name));
    const sizesLine = sizesText(p) + (p.sold_out_sizes.length ? ` · изчерпани: ${p.sold_out_sizes.join(', ')}` : '');
    name.append(el('span', 'shop-small', sizesLine));

    const price = el('td', '', priceText(p));

    const pers = el('td');
    if (p.allows_personalization) pers.append(el('span', 'shop-badge pers', `да · +${eur(p.personalization_fee)} €`));
    else pers.append(el('span', 'shop-small', '—'));

    const vis = el('td');
    vis.append(el('span', p.is_visible ? 'shop-badge' : 'shop-badge off', p.is_visible ? 'показва се' : 'скрит'));

    const actions = el('td');
    const wrap = el('div', 'shop-actions');
    const edit = el('button', 'btn btn-outline btn-sm', 'Редакция');
    edit.type = 'button';
    edit.addEventListener('click', () => editProduct(p));
    const toggle = el('button', 'btn btn-outline btn-sm', p.is_visible ? 'Скрий' : 'Покажи');
    toggle.type = 'button';
    toggle.addEventListener('click', () => patch(p.id, { is_visible: !p.is_visible }));
    const del = el('button', 'btn btn-outline btn-sm btn-danger-text', 'Изтрий');
    del.type = 'button';
    del.addEventListener('click', () => remove(p));
    wrap.append(edit, toggle, del);
    actions.append(wrap);

    tr.append(order, photo, name, price, pers, vis, actions);
    bodyEl.append(tr);
  });
}

async function load() {
  try {
    const { res, data } = await api(API);
    if (!res.ok) { flash(data.error || 'Грешка при зареждане.', true); return; }
    products = data.products;
    meta = data.meta;
    render();
  } catch (err) {
    flash('Няма връзка със сървъра.', true);
  }
}

async function patch(id, changes) {
  const { res, data } = await api(`${API}/${id}`, { method: 'PATCH', body: JSON.stringify(changes) });
  if (!res.ok) { flash(data.error || 'Промяната не е записана.', true); return; }
  flash('Записано.');
  await load();
}

async function move(id, direction) {
  const { res, data } = await api(`${API}/${id}/move`, { method: 'POST', body: JSON.stringify({ direction }) });
  if (!res.ok) { flash(data.error || 'Не може да се премести.', true); return; }
  products = data.products;
  render();
}

async function remove(p) {
  if (!confirm(`Да се изтрие ли „${p.name}“?\n\nАко искате само да го махнете от магазина за известно време, използвайте „Скрий“.`)) return;
  const { res, data } = await api(`${API}/${p.id}`, { method: 'DELETE' });
  if (!res.ok) { flash(data.error || 'Не е изтрит.', true); return; }
  if (editingId === p.id) resetForm();
  flash('Артикулът е изтрит.');
  await load();
}

// ------------------------------------------------------------- старт ---
f.mode.addEventListener('change', syncMode);
f.pers.addEventListener('change', syncPers);
f.file.addEventListener('change', () => { if (f.file.files[0]) uploadImage(f.file.files[0]); });
$('#imageRemove').addEventListener('click', () => setImage(null, null));
saveBtn.addEventListener('click', save);
cancelBtn.addEventListener('click', resetForm);
$('#productForm').addEventListener('submit', (e) => { e.preventDefault(); save(); });

(async function init() {
  await load();
  resetForm();
})();
