// Админ „Такси“: месечен екран за отбелязване на плащания, присвояване, видове такси, отчет.
const $ = (sel) => document.querySelector(sel);
const statusEl = $('#status');
let statusTimer = null;
let month = null;           // „ГГГГ-ММ“ на екрана „Месец“
let monthData = null;
let types = [];
let teams = [];
let editingType = null;
let allPlayers = null;

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
  statusTimer = setTimeout(() => { statusEl.classList.remove('error', 'saved'); statusEl.textContent = ''; }, isError ? 6000 : 3000);
}

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

function showErrors(form, errors) {
  form.querySelectorAll('.field-error').forEach(e => { e.textContent = ''; });
  Object.entries(errors || {}).forEach(([k, msg]) => {
    const t = form.querySelector(`[data-error-for="${k}"]`);
    if (t) t.textContent = msg;
  });
}

function fillSelect(select, items, firstLabel, value) {
  const keep = value !== undefined ? value : select.value;
  select.textContent = '';
  if (firstLabel !== null) { const o = el('option', '', firstLabel); o.value = ''; select.append(o); }
  items.forEach(i => { const o = el('option', '', i.label); o.value = i.value; select.append(o); });
  select.value = keep;
  // Без „празна“ опция (Такса, Отбор в присвояването) винаги има избрана — първата.
  if (select.selectedIndex < 0 && select.options.length) select.selectedIndex = 0;
}

function thisMonthKey() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

// -------------------------------------------------------------- табове ---
document.querySelectorAll('.fee-tab').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('.fee-tab').forEach(b => b.classList.toggle('active', b === btn));
  document.querySelectorAll('.fee-pane').forEach(p => { p.hidden = p.id !== `tab-${btn.dataset.tab}`; });
  if (btn.dataset.tab === 'report') loadReport();
  if (btn.dataset.tab === 'pay') loadPay();
  if (btn.dataset.tab === 'assign') loadAssignOptions();
}));

// --------------------------------------------------------------- месец ---
function statusSelect(row) {
  const select = el('select', `fee-status st-${row.status}`);
  [['unpaid', 'Неплатено'], ['paid', 'Платено'], ['waived', 'Освободено']].forEach(([v, t]) => {
    const o = el('option', '', t); o.value = v; select.append(o);
  });
  select.value = row.status;
  select.addEventListener('change', () => patchCharge(row, { status: select.value }));
  return select;
}

async function patchCharge(row, body) {
  const { res, data } = await api(`/api/admin/fee-charges/${row.id}`, { method: 'PATCH', body: JSON.stringify(body) });
  if (!res.ok || !data.ok) {
    flash((data.errors && Object.values(data.errors)[0]) || data.error || 'Неуспешно запазване.', true);
    await loadMonth();
    return;
  }
  flash('Запазено ✓');
  await loadMonth(false);
}

function renderMonth() {
  $('#monthLabel').textContent = monthData.month_label + (monthData.is_current ? ' (текущ)' : '');
  const t = monthData.totals;
  $('#monthTotals').textContent = `Редове: ${t.count} · За плащане: ${t.due_text} · Платено: ${t.paid_text} · Неплатено: ${t.unpaid_text}` + (t.waived_text !== '0 €' ? ` · Освободено: ${t.waived_text}` : '');
  const body = $('#monthBody');
  body.textContent = '';
  if (!monthData.rows.length) {
    const tr = el('tr'); const td = el('td', 'empty-state', 'Няма редове за този месец по тези филтри. Присвоете такса от „Присвояване“.'); td.colSpan = 6; tr.append(td); body.append(tr);
  }
  monthData.rows.forEach(row => {
    const tr = el('tr', row.status === 'paid' ? 'is-processed' : (row.status === 'waived' ? 'is-archived' : ''));
    const who = el('td'); const a = el('a', '', row.child_name); a.href = `admin-player-fees.html?id=${row.player_id}`; who.append(el('strong')); who.firstChild.append(a);
    tr.append(who, el('td', '', row.team_label || '—'), el('td', '', row.type_name));
    const amount = el('td', 'admin-edit'); const input = el('input'); input.value = row.amount; input.inputMode = 'decimal'; input.className = 'fee-amount'; input.setAttribute('aria-label', 'Сума');
    input.addEventListener('change', () => patchCharge(row, { amount: input.value }));
    amount.append(input); tr.append(amount);
    const st = el('td'); st.append(statusSelect(row)); tr.append(st);
    const note = el('td', 'admin-edit'); const n = el('input'); n.value = row.note; n.maxLength = 120; n.className = 'fee-note'; n.placeholder = '—'; n.setAttribute('aria-label', 'Бележка');
    n.addEventListener('change', () => patchCharge(row, { note: n.value }));
    note.append(n); tr.append(note);
    if (row.updated_by) tr.title = `Последна промяна: ${row.updated_by}`;
    body.append(tr);
  });
}

async function loadMonth(rebuildFilters = true) {
  const params = new URLSearchParams({ month });
  if ($('#mTeam').value) params.set('team', $('#mTeam').value);
  if ($('#mType').value) params.set('type', $('#mType').value);
  if ($('#mQ').value.trim()) params.set('q', $('#mQ').value.trim());
  const { res, data } = await api(`/api/admin/fees/month?${params}`);
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно зареждане.', true); return; }
  monthData = data;
  teams = data.teams; types = data.types;
  if (rebuildFilters) {
    fillSelect($('#mTeam'), teams.map(t => ({ value: t.id, label: t.label })), 'Всички');
    fillSelect($('#mType'), types.map(t => ({ value: t.id, label: t.name })), 'Всички');
  }
  renderMonth();
}

function goMonth(key) { month = key; loadMonth(false); }
$('#prevMonth').addEventListener('click', () => goMonth(monthData.prev));
$('#nextMonth').addEventListener('click', () => goMonth(monthData.next));
$('#thisMonth').addEventListener('click', () => goMonth(thisMonthKey()));
['#mTeam', '#mType'].forEach(s => $(s).addEventListener('change', () => loadMonth(false)));
let qTimer = null;
$('#mQ').addEventListener('input', () => { clearTimeout(qTimer); qTimer = setTimeout(() => loadMonth(false), 300); });

function bulkBody(status, months) {
  return {
    months, status,
    team_id: $('#mTeam').value ? Number($('#mTeam').value) : null,
    type_id: $('#mType').value ? Number($('#mType').value) : null,
    player_ids: months.length === 1 && $('#mQ').value.trim() ? [...new Set(monthData.rows.map(r => r.player_id))] : undefined
  };
}

async function runBulk(status, months, confirmText) {
  if (!confirm(confirmText)) return;
  const { res, data } = await api('/api/admin/fees/bulk', { method: 'POST', body: JSON.stringify(bulkBody(status, months)) });
  if (!res.ok || !data.ok) { flash((data.errors && data.errors.months) || data.error || 'Неуспешно.', true); return; }
  await loadMonth(false);
  flash(`Променени редове: ${data.changed} ✓`);
}

$('#bulkPaid').addEventListener('click', () => runBulk('paid', [month], `Да отбележа ли всички показани неплатени редове за ${monthData.month_label} като платени?`));
$('#bulkWaive').addEventListener('click', () => runBulk('waived', [month], `Да освободя ли всички показани неплатени редове за ${monthData.month_label}?`));
$('#rangeWaive').addEventListener('click', () => {
  const from = $('#rFrom').value, to = $('#rTo').value;
  if (!from || !to || from > to) { flash('Изберете „от месец“ и „до месец“ (началото не може да е след края).', true); return; }
  const months = [];
  let [y, m] = from.split('-').map(Number);
  const [ey, em] = to.split('-').map(Number);
  while (y < ey || (y === ey && m <= em)) {
    months.push(`${y}-${String(m).padStart(2, '0')}`);
    m += 1; if (m > 12) { m = 1; y += 1; }
  }
  const scope = [$('#mTeam').selectedOptions[0].textContent, $('#mType').selectedOptions[0].textContent].join(' / ');
  runBulk('waived', months, `Да освободя ли неплатените месеци от ${from} до ${to} (${months.length} мес.)?\nОбхват — отбор / такса: ${scope}.`);
});

// ---------------------------------------------------------- присвояване ---
async function loadAssignOptions() {
  if (!monthData) await loadMonth();
  fillSelect($('#a-type'), types.filter(t => t.is_active).map(t => ({ value: t.id, label: `${t.name} (${t.kind === 'monthly' ? 'месечна' : 'еднократна'})` })), null);
  fillSelect($('#a-team'), teams.map(t => ({ value: t.id, label: t.label })), null);
  if (!$('#a-start').value) $('#a-start').value = thisMonthKey();
  updateAmountHint();
  if (!allPlayers) {
    const { data } = await api('/api/admin/players');
    allPlayers = (data.players || []).map(p => ({ id: p.id, name: p.child_name, team: p.team_label }));
  }
  renderPlayerPicker();
}

function updateAmountHint() {
  const t = types.find(x => String(x.id) === $('#a-type').value);
  $('#a-amount').placeholder = t ? String(t.default_amount) : '';
  $('#a-amount-hint').textContent = t ? `Празно = стандартната сума (${t.default_amount_text}).` : '';
}
$('#a-type').addEventListener('change', updateAmountHint);

function whoValue() { return document.querySelector('input[name="who"]:checked').value; }
document.querySelectorAll('input[name="who"]').forEach(r => r.addEventListener('change', () => {
  $('#whoTeam').hidden = whoValue() !== 'team';
  $('#whoPlayers').hidden = whoValue() !== 'players';
}));

function renderPlayerPicker() {
  const needle = $('#a-search').value.trim().toLowerCase();
  const box = $('#a-players');
  const chosen = new Set([...box.querySelectorAll('input:checked')].map(i => Number(i.value)));
  box.textContent = '';
  (allPlayers || []).filter(p => !needle || p.name.toLowerCase().includes(needle) || chosen.has(p.id)).slice(0, 80).forEach(p => {
    const label = el('label', 'check-item'); const i = document.createElement('input');
    i.type = 'checkbox'; i.value = p.id; i.checked = chosen.has(p.id);
    label.append(i, el('span', '', `${p.name}${p.team ? ' · ' + p.team : ''}`)); box.append(label);
  });
}
$('#a-search').addEventListener('input', renderPlayerPicker);

$('#assignBtn').addEventListener('click', async () => {
  const form = $('#assignForm');
  const body = { fee_type_id: Number($('#a-type').value), start_month: $('#a-start').value, note: $('#a-note').value };
  if ($('#a-amount').value.trim()) body.amount = $('#a-amount').value;
  if ($('#a-first').value.trim()) body.first_month_amount = $('#a-first').value;
  const who = whoValue();
  if (who === 'team') body.team_id = Number($('#a-team').value);
  else if (who === 'all') body.all = true;
  else body.player_ids = [...$('#a-players').querySelectorAll('input:checked')].map(i => Number(i.value));
  $('#assignBtn').disabled = true;
  const { res, data } = await api('/api/admin/fees/assign', { method: 'POST', body: JSON.stringify(body) });
  $('#assignBtn').disabled = false;
  if (!res.ok || !data.ok) { showErrors(form, data.errors); flash(data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно.'), true); return; }
  showErrors(form, {});
  const skipped = data.skipped.length ? ` Пропуснати (вече имат таксата): ${data.skipped.join(', ')}.` : '';
  flash(`Присвоено на ${data.created} ${data.created === 1 ? 'играч' : 'играчи'} ✓${skipped}`);
});
$('#assignForm').addEventListener('submit', e => e.preventDefault());

// ------------------------------------------------------- видове такси ---
function renderTypes() {
  const body = $('#typesBody'); body.textContent = '';
  if (!types.length) { const tr = el('tr'); const td = el('td', 'empty-state', 'Още няма такси. Добавете първата с формата отгоре.'); td.colSpan = 6; tr.append(td); body.append(tr); }
  types.forEach(t => {
    const tr = el('tr', t.is_active ? '' : 'is-archived');
    tr.append(el('td', '', t.name), el('td', '', t.kind === 'monthly' ? 'Месечна' : 'Еднократна'), el('td', '', t.default_amount_text), el('td', '', String(t.assignments)));
    const st = el('td'); st.append(el('span', `status-pill ${t.is_active ? 'is-published' : 'is-draft'}`, t.is_active ? 'Активна' : 'Неактивна')); tr.append(st);
    const act = el('td'); const row = el('div', 'row-actions');
    const edit = el('button', 'btn btn-outline btn-sm', 'Редактирай'); edit.type = 'button'; edit.addEventListener('click', () => editType(t));
    const tog = el('button', 'btn btn-outline btn-sm', t.is_active ? 'Деактивирай' : 'Активирай'); tog.type = 'button';
    tog.addEventListener('click', async () => {
      const { res, data } = await api(`/api/admin/fee-types/${t.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !t.is_active }) });
      if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно.', true); return; }
      await loadMonth(); renderTypes();
    });
    row.append(edit, tog); act.append(row); tr.append(act); body.append(tr);
  });
}

function editType(t) {
  editingType = t || null;
  $('#typeFormTitle').textContent = t ? `Редакция: ${t.name}` : 'Нов вид такса';
  $('#t-name').value = t ? t.name : '';
  $('#t-kind').value = t ? t.kind : 'monthly';
  $('#t-amount').value = t ? t.default_amount : '';
  $('#t-active').checked = t ? t.is_active : true;
  $('#typeSave').textContent = t ? 'Запази' : 'Добави';
  $('#typeCancel').hidden = !t;
  showErrors($('#typeForm'), {});
}
$('#typeCancel').addEventListener('click', () => editType(null));
$('#typeSave').addEventListener('click', async () => {
  const body = { name: $('#t-name').value, kind: $('#t-kind').value, default_amount: $('#t-amount').value || 0, is_active: $('#t-active').checked };
  const { res, data } = await api(editingType ? `/api/admin/fee-types/${editingType.id}` : '/api/admin/fee-types', { method: editingType ? 'PATCH' : 'POST', body: JSON.stringify(body) });
  if (!res.ok || !data.ok) { showErrors($('#typeForm'), data.errors); flash(data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно.'), true); return; }
  editType(null);
  await loadMonth();
  renderTypes();
  flash('Запазено ✓');
});
$('#typeForm').addEventListener('submit', e => e.preventDefault());
document.querySelector('[data-tab="types"]').addEventListener('click', renderTypes);

// ---------------------------------------------------------------- отчет ---
async function loadReport() {
  if (!monthData) await loadMonth();
  if (!$('#rMonth').value) $('#rMonth').value = month;
  fillSelect($('#rTeam'), teams.map(t => ({ value: t.id, label: t.label })), 'Всички');
  fillSelect($('#rType'), types.map(t => ({ value: t.id, label: t.name })), 'Всички');
  const params = new URLSearchParams({ month: $('#rMonth').value, status: $('#rStatus').value });
  if ($('#rTeam').value) params.set('team', $('#rTeam').value);
  if ($('#rType').value) params.set('type', $('#rType').value);
  $('#csvLink').href = `/api/admin/fees/report.csv?${params}`;
  const { res, data } = await api(`/api/admin/fees/report?${params}`);
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно зареждане.', true); return; }
  const t = data.totals;
  $('#reportTotals').textContent = `${data.month_label} · Редове: ${t.count} · За плащане: ${t.due_text} · Платено: ${t.paid_text} · Неплатено: ${t.unpaid_text}`;
  const body = $('#reportBody'); body.textContent = '';
  if (!data.rows.length) { const tr = el('tr'); const td = el('td', 'empty-state', 'Няма редове по тези филтри.'); td.colSpan = 5; tr.append(td); body.append(tr); }
  data.rows.forEach(r => {
    const tr = el('tr'); const who = el('td'); const a = el('a', '', r.child_name); a.href = `admin-player-fees.html?id=${r.player_id}`; who.append(a);
    tr.append(who, el('td', '', r.team_label || '—'), el('td', '', r.label), el('td', '', r.amount_text), el('td', '', r.status_label)); body.append(tr);
  });
}
['#rMonth', '#rTeam', '#rType', '#rStatus'].forEach(s => $(s).addEventListener('change', loadReport));

// -------------------------------------------------------- как се плаща ---
async function loadPay() {
  const { data } = await api('/api/admin/fees/pay-info');
  $('#p-text').value = data.text || '';
}
$('#paySave').addEventListener('click', async () => {
  const { res, data } = await api('/api/admin/fees/pay-info', { method: 'PUT', body: JSON.stringify({ text: $('#p-text').value }) });
  if (!res.ok || !data.ok) { showErrors($('#payForm'), data.errors); flash('Неуспешно запазване.', true); return; }
  showErrors($('#payForm'), {});
  flash('Запазено ✓');
});
$('#payForm').addEventListener('submit', e => e.preventDefault());

// ---------------------------------------------------------------- старт ---
month = new URLSearchParams(location.search).get('month') || thisMonthKey();
loadMonth().catch(() => { statusEl.classList.add('error'); statusEl.textContent = 'Неуспешно зареждане или нямате права.'; });
