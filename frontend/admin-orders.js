// Админ „Поръчки“: списък със статуси, бележки, имейл известия и подробности.
const API = '/api/admin/shop/orders';
const $ = (sel) => document.querySelector(sel);

const STATUSES = [
  { key: 'new', label: 'Нова' },
  { key: 'processed', label: 'Обработена' },
  { key: 'delivered', label: 'Предадена' },
  { key: 'cancelled', label: 'Отказана' }
];
const STATUS_LABEL = Object.fromEntries(STATUSES.map(s => [s.key, s.label]));
const CHIP_LABEL = { new: 'Нови', processed: 'Обработени', delivered: 'Предадени', cancelled: 'Отказани' };

const listEl = $('#orderList');
const statusEl = $('#status');
const emptyEl = $('#emptyState');

let orders = [];
let counts = { new: 0, processed: 0, delivered: 0, cancelled: 0 };
let filter = '';          // '' = всички
let query = '';
let matching = 0;
let shownAll = true;
const open = new Set();   // отворените поръчки (оцеляват при прерисуване)
let statusTimer = null;
let flashing = false;

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function eur(n) { return Number.isInteger(n) ? String(n) : Number(n).toFixed(2).replace('.', ','); }

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
  return d.toLocaleString('bg-BG', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Sofia' });
}

function summary() {
  const all = counts.new + counts.processed + counts.delivered + counts.cancelled;
  return `Поръчки: ${all} · нови: ${counts.new}`;
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
  }, isError ? 5000 : 2200);
}

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

// ------------------------------------------------------------ филтри ---
function renderChips() {
  const box = $('#chips');
  box.textContent = '';
  const all = counts.new + counts.processed + counts.delivered + counts.cancelled;
  const chips = [{ key: '', label: 'Всички', n: all }].concat(STATUSES.map(s => ({ key: s.key, label: CHIP_LABEL[s.key], n: counts[s.key] })));
  chips.forEach(c => {
    const b = el('button', 'order-chip', c.label);
    b.type = 'button';
    b.setAttribute('role', 'tab');
    b.setAttribute('aria-selected', String(filter === c.key));
    b.appendChild(el('b', '', String(c.n)));
    b.addEventListener('click', () => { filter = c.key; load(); });
    box.appendChild(b);
  });
}

// ----------------------------------------------------------- карта ---
function personalText(i) {
  const parts = [];
  if (i.personal_name) parts.push('име ' + i.personal_name);
  if (i.personal_number) parts.push('номер ' + i.personal_number);
  return parts.length ? `Персонализация: ${parts.join(', ')} (+${eur(i.personalization_fee)} €)` : '';
}

function mailRow(order, who, label, flag) {
  const row = el('div', 'order-mail');
  row.appendChild(el('span', '', label));
  if (flag === true) row.appendChild(el('span', 'ok', '✓ изпратен'));
  else {
    row.appendChild(el('span', 'bad', flag === false ? '✗ не е изпратен' : '— не е пробван'));
    const b = el('button', 'btn btn-outline btn-sm', 'Изпрати отново');
    b.type = 'button';
    b.addEventListener('click', async () => {
      b.disabled = true;
      const { res, data } = await api(`${API}/${order.id}/resend`, { method: 'POST', body: JSON.stringify({ to: who }) });
      if (data.order) replaceOrder(data.order);
      if (res.ok) flash('Имейлът е изпратен.'); else { flash(data.error || 'Имейлът не е изпратен.', true); b.disabled = false; }
    });
    row.appendChild(b);
  }
  return row;
}

function buildCard(o) {
  const card = el('article', `order-card s-${o.status}` + (open.has(o.id) ? ' open' : ''));

  // --- заглавие
  const head = el('div', 'order-head');
  const idBox = el('div');
  idBox.appendChild(el('div', 'order-no', '№ ' + o.number));
  idBox.appendChild(el('div', 'order-date', fmtDate(o.created_at)));
  head.appendChild(idBox);

  const who = el('div', 'order-who');
  who.appendChild(el('strong', '', o.customer_name));
  who.appendChild(el('span', '', `${o.phone} · ${o.email}`));
  head.appendChild(who);

  head.appendChild(el('div', 'order-total', eur(o.total) + ' €'));

  const select = el('select', 'order-status');
  select.setAttribute('aria-label', 'Статус на поръчка ' + o.number);
  STATUSES.forEach(s => {
    const opt = el('option', '', s.label);
    opt.value = s.key;
    opt.selected = s.key === o.status;
    select.appendChild(opt);
  });
  select.addEventListener('click', e => e.stopPropagation());
  select.addEventListener('change', async () => {
    const { res, data } = await api(`${API}/${o.id}`, { method: 'PATCH', body: JSON.stringify({ status: select.value }) });
    if (!res.ok) { flash(data.error || 'Статусът не е записан.', true); select.value = o.status; return; }
    counts = data.counts;
    replaceOrder(data.order);
    renderChips();
    if (window.refreshOrdersBadge) window.refreshOrdersBadge();
    flash('Статусът е променен: ' + STATUS_LABEL[data.order.status] + '.');
  });
  head.appendChild(select);

  const toggle = el('button', 'order-toggle', '▾');
  toggle.type = 'button';
  toggle.setAttribute('aria-label', 'Подробности');
  head.appendChild(toggle);

  const tags = el('div', 'order-tags');
  tags.appendChild(el('span', 'order-tag', o.delivery === 'delivery' ? 'Доставка до адрес' : 'Взима се от академията'));
  if (o.items.some(i => i.personal_name || i.personal_number)) tags.appendChild(el('span', 'order-tag', 'Има персонализация'));
  if (o.coach_notified !== true) tags.appendChild(el('span', 'order-tag warn', 'Имейлът до треньора не е изпратен'));
  head.appendChild(tags);

  head.addEventListener('click', () => {
    const isOpen = card.classList.toggle('open');
    if (isOpen) open.add(o.id); else open.delete(o.id);
  });
  card.appendChild(head);

  // --- подробности
  const body = el('div', 'order-body');
  const grid = el('div', 'order-grid');

  const left = el('div');
  left.appendChild(el('h4', '', 'Артикули'));
  const table = el('table', 'order-items');
  const thead = el('thead');
  const hr = el('tr');
  ['Артикул', 'Размер', 'Бр.', 'Сума'].forEach((t, idx) => hr.appendChild(el('th', idx > 1 ? 'num' : '', t)));
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el('tbody');
  o.items.forEach(i => {
    const tr = el('tr');
    const name = el('td', '', i.product_name);
    const pers = personalText(i);
    if (pers) name.appendChild(el('span', 'pers', pers));
    tr.appendChild(name);
    tr.appendChild(el('td', '', i.group_label ? `${i.size} (${i.group_label.toLowerCase()})` : 'един размер'));
    tr.appendChild(el('td', 'num', String(i.qty)));
    tr.appendChild(el('td', 'num', eur(i.line_total) + ' €'));
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  left.appendChild(table);
  const sum = el('div', 'order-sum');
  sum.appendChild(el('span', '', 'Общо (ориентировъчно)'));
  sum.appendChild(el('span', '', eur(o.total) + ' €'));
  left.appendChild(sum);
  grid.appendChild(left);

  const right = el('div', 'order-info');
  right.appendChild(el('h4', '', 'Клиент'));
  const tel = el('a', '', o.phone); tel.href = 'tel:' + o.phone.replace(/[^\d+]/g, '');
  const mail = el('a', '', o.email); mail.href = 'mailto:' + o.email;
  const p1 = el('p'); p1.append(el('strong', '', o.customer_name), document.createElement('br'), tel, document.createElement('br'), mail);
  right.appendChild(p1);
  right.appendChild(el('p', '', o.delivery === 'delivery'
    ? 'Доставка до адрес: ' + (o.address || '— не е посочен (да се уточни по телефона)')
    : 'Ще вземе от академията.'));
  right.appendChild(el('p', '', 'Съгласие за лични данни: ' + fmtDate(o.consent_at)));
  right.appendChild(el('h4', '', 'Имейли'));
  right.appendChild(mailRow(o, 'coach', 'До треньора:', o.coach_notified));
  right.appendChild(mailRow(o, 'customer', 'До клиента:', o.customer_notified));
  grid.appendChild(right);
  body.appendChild(grid);

  // --- бележка
  const note = el('div', 'order-note');
  note.style.marginTop = '16px';
  note.appendChild(el('h4', '', 'Бележка (само за админите)'));
  const ta = document.createElement('textarea');
  ta.value = o.admin_note || '';
  ta.maxLength = 2000;
  ta.placeholder = 'напр. звънях, плащане в брой при вземане…';
  note.appendChild(ta);
  const actions = el('div', 'order-note-actions');
  const save = el('button', 'btn btn-primary btn-sm', 'Запази бележката');
  save.type = 'button';
  save.disabled = true;
  const saved = el('span', 'order-note-saved');
  ta.addEventListener('input', () => { save.disabled = ta.value.trim() === (o.admin_note || ''); saved.textContent = ''; });
  save.addEventListener('click', async () => {
    save.disabled = true;
    const { res, data } = await api(`${API}/${o.id}`, { method: 'PATCH', body: JSON.stringify({ admin_note: ta.value }) });
    if (!res.ok) { flash(data.error || 'Бележката не е записана.', true); save.disabled = false; return; }
    o.admin_note = data.order.admin_note;
    const idx = orders.findIndex(x => x.id === o.id);
    if (idx >= 0) orders[idx] = data.order;
    saved.textContent = 'Записано.';
  });
  actions.append(save, saved);
  note.appendChild(actions);
  body.appendChild(note);

  // --- изтриване (само главният админ)
  if (window.adminUser && window.adminUser.role === 'owner') {
    const foot = el('div', 'order-foot');
    const del = el('button', 'btn btn-outline btn-sm btn-danger-text', 'Изтрий поръчката');
    del.type = 'button';
    del.addEventListener('click', async () => {
      if (!confirm(`Да се изтрие ли поръчка № ${o.number} от ${o.customer_name}?\n\nИзтриват се и личните данни на клиента. Това не може да се върне.`)) return;
      const { res, data } = await api(`${API}/${o.id}`, { method: 'DELETE' });
      if (!res.ok) { flash(data.error || 'Не е изтрита.', true); return; }
      open.delete(o.id);
      flash('Поръчката е изтрита.');
      await load();
      if (window.refreshOrdersBadge) window.refreshOrdersBadge();
    });
    foot.appendChild(del);
    body.appendChild(foot);
  }
  card.appendChild(body);
  return card;
}

// Обновява една поръчка на място. Ако смяната на статуса я изважда от избрания филтър,
// тя остава видима до следващото опресняване (за да не „изчезва“ под ръцете на админа).
function replaceOrder(updated) {
  const idx = orders.findIndex(x => x.id === updated.id);
  if (idx >= 0) orders[idx] = updated;
  render();
}

function render() {
  if (!flashing) statusEl.textContent = summary();
  listEl.textContent = '';
  orders.forEach(o => listEl.appendChild(buildCard(o)));
  emptyEl.hidden = orders.length > 0;
  if (!orders.length) {
    emptyEl.textContent = (filter || query) ? 'Няма поръчки, които да отговарят на избраното.' : 'Още няма поръчки.';
  } else if (!shownAll) {
    emptyEl.hidden = false;
    emptyEl.textContent = `Показани са най-новите ${orders.length} от ${matching} поръчки. Стеснете търсенето, за да видите по-стари.`;
  }
}

async function load() {
  const params = new URLSearchParams();
  if (filter) params.set('status', filter);
  if (query) params.set('q', query);
  try {
    const { res, data } = await api(API + (params.toString() ? '?' + params : ''));
    if (!res.ok) { flash(data.error || 'Грешка при зареждане.', true); return; }
    orders = data.orders;
    counts = data.counts;
    matching = data.matching;
    shownAll = data.shown_all;
    renderChips();
    render();
  } catch (err) {
    flash('Няма връзка със сървъра.', true);
  }
}

let searchTimer = null;
$('#search').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { query = e.target.value.trim(); load(); }, 300);
});

load();
