// Админ „Отчети и експорт“: оборот, най-продавани артикули, CSV за период, изтриване на стари поръчки.
const API = '/api/admin/shop';
const $ = (sel) => document.querySelector(sel);

const statusEl = $('#status');
statusEl.textContent = '';
let statusTimer = null;
let reqId = 0;   // пази от „закъснели“ отговори при бързо менене на периода

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
function eur(n) { return Number.isInteger(n) ? String(n) : Number(n).toFixed(2).replace('.', ','); }
function bgDate(iso) { const [y, m, d] = iso.split('-'); return `${d}.${m}.${y}`; }

function flash(text, isError = false) {
  clearTimeout(statusTimer);
  statusEl.classList.toggle('error', isError);
  statusEl.classList.toggle('saved', !isError);
  statusEl.textContent = text;
  statusTimer = setTimeout(() => { statusEl.classList.remove('error', 'saved'); statusEl.textContent = ''; }, isError ? 5000 : 2500);
}

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

// ------------------------------------------------------------ период ---
function sofiaToday() {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'Europe/Sofia' }); // ГГГГ-ММ-ДД
}
function iso(y, m, d) { return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`; }
function daysAgo(n) {
  const [y, m, d] = sofiaToday().split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d - n));
  return iso(dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate());
}
const PRESETS = [
  { label: 'Този месец', range: () => { const [y, m] = sofiaToday().split('-').map(Number); return [iso(y, m, 1), sofiaToday()]; } },
  { label: 'Миналия месец', range: () => {
      const [y, m] = sofiaToday().split('-').map(Number);
      const py = m === 1 ? y - 1 : y, pm = m === 1 ? 12 : m - 1;
      return [iso(py, pm, 1), iso(py, pm, new Date(Date.UTC(py, pm, 0)).getUTCDate())];
    } },
  { label: 'Последните 30 дни', range: () => [daysAgo(29), sofiaToday()] },
  { label: 'Тази година', range: () => { const [y] = sofiaToday().split('-').map(Number); return [iso(y, 1, 1), sofiaToday()]; } },
  { label: 'Всичко', range: () => ['', ''] }
];

function renderPresets() {
  const box = $('#presets');
  PRESETS.forEach(p => {
    const b = el('button', 'order-chip', p.label);
    b.type = 'button';
    b.addEventListener('click', () => { const [f, t] = p.range(); $('#from').value = f; $('#to').value = t; refresh(); });
    box.appendChild(b);
  });
}

function periodParams() {
  const params = new URLSearchParams();
  if ($('#from').value) params.set('from', $('#from').value);
  if ($('#to').value) params.set('to', $('#to').value);
  return params;
}

function validPeriod() {
  const f = $('#from').value, t = $('#to').value;
  const err = $('#periodError');
  if (f && t && f > t) { err.textContent = 'Началната дата е след крайната.'; return false; }
  err.textContent = '';
  return true;
}

// --------------------------------------------------------- статистика ---
function stat(label, value, note, main) {
  const box = el('div', 'rp-stat' + (main ? ' main' : ''));
  box.append(el('span', '', label), el('strong', '', value));
  if (note) box.appendChild(el('small', '', note));
  return box;
}

function renderStats(s) {
  const box = $('#stats');
  box.textContent = '';
  const st = s.by_status;
  box.appendChild(stat('Поръчки в периода', String(s.orders_total),
    `нови ${st.new} · обработени ${st.processed} · предадени ${st.delivered} · отказани ${st.cancelled}`));
  box.appendChild(stat('Оборот', eur(s.revenue) + ' €',
    s.scope === 'confirmed' ? `от ${s.counted_orders} обработени и предадени` : `от ${s.counted_orders} поръчки (без отказаните)`, true));
  box.appendChild(stat('Средна поръчка', s.counted_orders ? eur(s.average) + ' €' : '—'));
  box.appendChild(stat('Продадени бройки', String(s.pieces),
    s.scope === 'confirmed' && s.pending_new ? `+ нови, още необработени: ${eur(s.pending_new)} €` : ''));

  const top = $('#topBox');
  top.textContent = '';
  if (!s.top_items.length) {
    top.appendChild(el('p', 'rp-empty', 'Няма продадени артикули за избраните поръчки в този период.'));
    return;
  }
  const maxQty = Math.max(...s.top_items.map(i => i.qty));
  const table = el('table', 'rp-top');
  const head = el('tr');
  [['#', ''], ['Артикул', ''], ['', 'bar-col'], ['Брой', 'num'], ['Сума', 'num'], ['С надпис', 'num']].forEach(([t, c]) => head.appendChild(el('th', c, t)));
  const thead = el('thead'); thead.appendChild(head); table.appendChild(thead);
  const tbody = el('tbody');
  s.top_items.forEach((i, idx) => {
    const tr = el('tr');
    tr.appendChild(el('td', '', String(idx + 1)));
    tr.appendChild(el('td', '', i.name));
    const barCell = el('td', 'bar-col');
    const bar = el('div', 'bar'); const fill = document.createElement('i');
    fill.style.width = Math.max(4, Math.round(100 * i.qty / maxQty)) + '%';
    bar.appendChild(fill); barCell.appendChild(bar); tr.appendChild(barCell);
    tr.appendChild(el('td', 'num', String(i.qty)));
    tr.appendChild(el('td', 'num', eur(i.revenue) + ' €'));
    tr.appendChild(el('td', 'num', i.personalized ? String(i.personalized) : '—'));
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  top.appendChild(table);
  if (s.top_items_more) top.appendChild(el('p', 'rp-empty', `…и още ${s.top_items_more} артикула с по-малко продажби.`));
}

async function refresh() {
  if (!validPeriod()) return;
  const params = periodParams();
  // връзката за експорт следва избрания период
  $('#exportBtn').href = `${API}/orders/export` + (params.toString() ? '?' + params : '');
  const stats = new URLSearchParams(params);
  stats.set('scope', $('#scope').value);
  const mine = ++reqId;
  try {
    const { res, data } = await api(`${API}/reports/stats?` + stats);
    if (mine !== reqId) return;
    if (!res.ok) { flash(data.error || 'Грешка при зареждане.', true); return; }
    renderStats(data);
  } catch (err) {
    flash('Няма връзка със сървъра.', true);
  }
}

// ------------------------------------------------- стари поръчки ---
let purgeInfo = null;

async function refreshPurge() {
  const months = parseInt($('#months').value, 10);
  const { res, data } = await api(`${API}/orders/purge-preview?months=${months}`);
  if (!res.ok) { $('#purgeInfo').textContent = data.error || 'Грешка.'; return; }
  purgeInfo = data;
  const info = $('#purgeInfo');
  const exp = $('#purgeExport');
  const btn = $('#purgeBtn');
  if (!data.count) {
    info.textContent = `Няма поръчки, по-стари от ${bgDate(data.cutoff)}.`;
    exp.hidden = true; btn.disabled = true; btn.textContent = 'Изтрий старите поръчки';
    return;
  }
  info.textContent = `${data.count} ${data.count === 1 ? 'поръчка' : 'поръчки'} преди ${bgDate(data.cutoff)}.`;
  exp.hidden = false;
  exp.href = `${API}/orders/export?to=${data.export_to}`;
  btn.disabled = false;
  btn.textContent = `Изтрий ${data.count} ${data.count === 1 ? 'поръчка' : 'поръчки'}`;
}

async function purge() {
  if (!purgeInfo || !purgeInfo.count) return;
  const n = purgeInfo.count;
  if (!confirm(`Ще бъдат изтрити безвъзвратно ${n} ${n === 1 ? 'поръчка' : 'поръчки'}, по-стари от ${bgDate(purgeInfo.cutoff)}, заедно с личните данни на клиентите.\n\nИзтеглили ли сте CSV за тях? Това не може да се върне.\n\nДа продължа ли?`)) return;
  $('#purgeBtn').disabled = true;
  const { res, data } = await api(`${API}/orders/purge`, { method: 'POST', body: JSON.stringify({ months: purgeInfo.months, expected: n }) });
  if (!res.ok) { flash(data.error || 'Не са изтрити.', true); await refreshPurge(); return; }
  flash(`Изтрити са ${data.deleted} ${data.deleted === 1 ? 'поръчка' : 'поръчки'}.`);
  await refreshPurge();
  await refresh();
  if (window.refreshOrdersBadge) window.refreshOrdersBadge();
}

// ------------------------------------------------------------- старт ---
renderPresets();
const [f0, t0] = PRESETS[0].range();   // по подразбиране — този месец
$('#from').value = f0;
$('#to').value = t0;
['from', 'to', 'scope'].forEach(id => $('#' + id).addEventListener('change', refresh));
$('#months').addEventListener('change', refreshPurge);
$('#purgeBtn').addEventListener('click', purge);
refresh();

// Изтриването е само за главния админ — останалите не виждат тази секция.
(function showPurgeForOwner(tries) {
  if (window.adminUser) {
    if (window.adminUser.role === 'owner') { $('#purgeCard').hidden = false; refreshPurge(); }
  } else if (tries > 0) {
    setTimeout(() => showPurgeForOwner(tries - 1), 100);
  }
})(30);
