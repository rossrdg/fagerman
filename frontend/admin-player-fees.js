// Админ: таксите на едно дете („платено до …“, присвоявания, месеци, история).
const playerId = Number(new URLSearchParams(location.search).get('id'));
const $ = (sel) => document.querySelector(sel);
const statusEl = $('#status');
let data = null;
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
  statusTimer = setTimeout(() => { statusEl.classList.remove('error', 'saved'); statusEl.textContent = ''; }, isError ? 6000 : 3000);
}

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const out = await res.json().catch(() => ({}));
  return { res, out };
}

function fmtAt(iso) {
  if (!iso) return '';
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
  return d.toLocaleString('bg-BG', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function thisMonthKey() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function render() {
  $('#title').textContent = `Такси: ${data.player.child_name}`;
  document.title = `Такси — ${data.player.child_name} — Админ — ФА Герман`;
  const s = data.summary;
  const box = $('#summary');
  box.textContent = '';
  const add = (label, value) => { const d = el('div'); d.append(el('span', 'muted', label + ' '), el('strong', '', value)); box.append(d); };
  add('Платено до:', s.paid_until_text || '—');
  add('Неплатени:', s.unpaid_count ? `${s.unpaid_count} (${s.unpaid_total_text})` : 'няма');
  if (s.unpaid_months.length) add('Неплатени месеци:', s.unpaid_months.join(', '));

  const types = data.types.filter(t => t.is_active);
  const sel = $('#a-type');
  const keep = sel.value;
  sel.textContent = '';
  types.forEach(t => { const o = el('option', '', `${t.name} (${t.kind === 'monthly' ? 'месечна' : 'еднократна'})`); o.value = t.id; sel.append(o); });
  sel.value = keep || (types[0] && types[0].id) || '';
  if (!$('#a-start').value) $('#a-start').value = thisMonthKey();

  const list = $('#assignments');
  list.textContent = '';
  if (!data.assignments.length) list.append(el('p', 'user-hint', 'Още няма присвоени такси.'));
  data.assignments.forEach(a => {
    const row = el('div', 'group-row');
    const info = el('div', 'grow');
    info.append(el('strong', '', a.type_name),
      el('small', '', ` · ${a.amount_text}${a.kind === 'monthly' ? ' на месец' : ''} · от ${a.start_label}`
        + (a.first_month_amount !== null ? ` (първи месец ${a.first_month_amount} €)` : '')
        + (a.end_month ? ` · до ${a.end_month}` : '') + (a.note ? ` · ${a.note}` : '')));
    row.append(info);
    const edit = el('button', 'btn btn-outline btn-sm', 'Промени'); edit.type = 'button'; edit.addEventListener('click', () => openEdit(a));
    const del = el('button', 'btn btn-outline btn-sm btn-danger-text', 'Изтрий'); del.type = 'button';
    del.addEventListener('click', async () => {
      if (!confirm(`Да изтрия ли присвояването „${a.type_name}“? Работи само ако няма платени или освободени месеци.`)) return;
      const { res, out } = await api(`/api/admin/fee-assignments/${a.id}`, { method: 'DELETE' });
      if (!res.ok || !out.ok) { flash(out.error || 'Неуспешно изтриване.', true); return; }
      await load(); flash('Присвояването е изтрито ✓');
    });
    row.append(edit, del);
    list.append(row);
  });

  const body = $('#charges');
  body.textContent = '';
  if (!data.charges.length) { const tr = el('tr'); const td = el('td', 'empty-state', 'Още няма месеци.'); td.colSpan = 5; tr.append(td); body.append(tr); }
  data.charges.forEach(c => {
    const tr = el('tr', c.status === 'paid' ? 'is-processed' : (c.status === 'waived' ? 'is-archived' : ''));
    tr.append(el('td', '', c.kind === 'one_time' ? `${c.month_label} (еднократна)` : c.month_label), el('td', '', c.type_name));
    const amount = el('td', 'admin-edit'); const ai = el('input', 'fee-amount'); ai.value = c.amount; ai.inputMode = 'decimal';
    ai.addEventListener('change', () => patch(c, { amount: ai.value })); amount.append(ai);
    const st = el('td'); const select = el('select', `fee-status st-${c.status}`);
    [['unpaid', 'Неплатено'], ['paid', 'Платено'], ['waived', 'Освободено']].forEach(([v, t]) => { const o = el('option', '', t); o.value = v; select.append(o); });
    select.value = c.status; select.addEventListener('change', () => patch(c, { status: select.value })); st.append(select);
    const note = el('td', 'admin-edit'); const ni = el('input', 'fee-note'); ni.value = c.note; ni.maxLength = 120;
    ni.addEventListener('change', () => patch(c, { note: ni.value })); note.append(ni);
    tr.append(amount, st, note);
    body.append(tr);
  });

  const hist = $('#history');
  hist.textContent = '';
  if (!data.history.length) hist.append(el('li', '', 'Още няма промени.'));
  data.history.forEach(h => { const li = el('li', '', h.detail); li.append(el('small', '', `${h.by || '—'} · ${fmtAt(h.at)}`)); hist.append(li); });
  statusEl.classList.remove('error', 'saved');
  statusEl.textContent = '';
}

async function patch(charge, body) {
  const { res, out } = await api(`/api/admin/fee-charges/${charge.id}`, { method: 'PATCH', body: JSON.stringify(body) });
  if (!res.ok || !out.ok) { flash((out.errors && Object.values(out.errors)[0]) || out.error || 'Неуспешно.', true); }
  else flash('Запазено ✓');
  await load(false);
}

function openEdit(a) {
  editing = a;
  $('#editName').textContent = `${a.type_name} (от ${a.start_label})`;
  $('#e-amount').value = a.amount;
  $('#e-end').value = a.end_month || '';
  $('#e-note').value = a.note;
  $('#e-apply').checked = false;
  $('#editForm').hidden = false;
}

$('#editCancel').addEventListener('click', () => { editing = null; $('#editForm').hidden = true; });
$('#editSave').addEventListener('click', async () => {
  const { res, out } = await api(`/api/admin/fee-assignments/${editing.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ amount: $('#e-amount').value, end_month: $('#e-end').value || null, note: $('#e-note').value, apply_to_unpaid: $('#e-apply').checked })
  });
  if (!res.ok || !out.ok) { flash((out.errors && Object.values(out.errors)[0]) || out.error || 'Неуспешно.', true); return; }
  $('#editForm').hidden = true; editing = null;
  await load(); flash('Запазено ✓');
});

$('#assignBtn').addEventListener('click', async () => {
  $('#assignErr').textContent = '';
  const body = { fee_type_id: Number($('#a-type').value), start_month: $('#a-start').value, player_ids: [playerId], note: $('#a-note').value };
  if ($('#a-amount').value.trim()) body.amount = $('#a-amount').value;
  if ($('#a-first').value.trim()) body.first_month_amount = $('#a-first').value;
  const { res, out } = await api('/api/admin/fees/assign', { method: 'POST', body: JSON.stringify(body) });
  if (!res.ok || !out.ok) { $('#assignErr').textContent = (out.errors && Object.values(out.errors)[0]) || out.error || 'Неуспешно.'; return; }
  if (out.skipped.length) { $('#assignErr').textContent = 'Детето вече има тази такса от по-рано. Променете съществуващото присвояване.'; return; }
  $('#a-amount').value = ''; $('#a-first').value = ''; $('#a-note').value = '';
  await load(); flash('Таксата е присвоена ✓');
});
$('#assignForm').addEventListener('submit', e => e.preventDefault());

async function load(showError = true) {
  const { res, out } = await api(`/api/admin/players/${playerId}/fees`);
  if (res.status === 403) { statusEl.classList.add('error'); statusEl.textContent = 'Нямате права да виждате таксите.'; return; }
  if (!res.ok || !out.ok) { if (showError) { statusEl.classList.add('error'); statusEl.textContent = 'Неуспешно зареждане.'; } return; }
  data = out;
  render();
}

if (!playerId) statusEl.textContent = 'Липсва профил.'; else load();
