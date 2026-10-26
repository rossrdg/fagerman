// Админ „График“: всички тренировъчни слотове на едно място.
const API = '/api/admin/schedule';
const $ = (sel) => document.querySelector(sel);

const statusEl = $('#status');
const listEl = $('#slotList');
const dayChecks = $('#dayChecks');
const teamChecks = $('#teamChecks');
const daySelect = $('#f-day');
const timeInput = $('#f-time');
const labelInput = $('#f-label');
const saveBtn = $('#saveBtn');
const cancelBtn = $('#cancelBtn');

let days = [];
let teams = [];
let slots = [];
let editingId = null;
let statusTimer = null;

function flash(text, isError = false, reset = '') {
  clearTimeout(statusTimer);
  statusEl.classList.toggle('error', isError);
  statusEl.classList.toggle('saved', !isError);
  statusEl.textContent = text;
  statusTimer = setTimeout(() => {
    statusEl.classList.remove('error', 'saved');
    statusEl.textContent = reset || summary();
  }, isError ? 5000 : 2500);
}

function summary() {
  return `Слотове: ${slots.length}`;
}

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function clearErrors() {
  document.querySelectorAll('#slotForm .field-error').forEach(e => { e.textContent = ''; });
}

function showErrors(errors) {
  clearErrors();
  Object.entries(errors || {}).forEach(([field, msg]) => {
    const target = document.querySelector(`[data-error-for="${field}"]`);
    if (target) target.textContent = msg;
  });
}

// ------------------------------------------------------------ form ---
function checkItem(name, value, text, checked = false) {
  const label = el('label', 'check-item');
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.name = name;
  input.value = value;
  input.checked = checked;
  label.append(input, el('span', '', text));
  return label;
}

function buildForm() {
  dayChecks.textContent = '';
  days.forEach(d => dayChecks.append(checkItem('day', d.number, d.name)));
  daySelect.textContent = '';
  days.forEach(d => {
    const opt = el('option', '', d.name);
    opt.value = d.number;
    daySelect.append(opt);
  });
  teamChecks.textContent = '';
  teams.filter(t => t.status === 'active').forEach(t => {
    const text = t.kind === 'men' ? 'MEN' : `${t.u_label} · ${t.cohort}`;
    teamChecks.append(checkItem('team', t.id, text));
  });
}

function checkedValues(name) {
  return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(i => Number(i.value));
}

function resetForm() {
  editingId = null;
  document.querySelectorAll('#slotForm input[type="checkbox"]').forEach(i => { i.checked = false; });
  timeInput.value = '';
  labelInput.value = '';
  clearErrors();
  $('#formTitle').textContent = 'Нов слот';
  $('#daysMulti').hidden = false;
  $('#daySingle').hidden = true;
  saveBtn.textContent = 'Добави';
  cancelBtn.hidden = true;
}

function startEdit(slot) {
  editingId = slot.id;
  clearErrors();
  $('#formTitle').textContent = `Редакция: ${slot.day_name} ${slot.time}`;
  $('#daysMulti').hidden = true;
  $('#daySingle').hidden = false;
  daySelect.value = slot.day;
  timeInput.value = slot.time;
  labelInput.value = slot.label || '';
  document.querySelectorAll('input[name="team"]').forEach(i => {
    i.checked = slot.team_ids.includes(Number(i.value));
  });
  saveBtn.textContent = 'Запази';
  cancelBtn.hidden = false;
  $('#slotForm').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function save() {
  clearErrors();
  const body = {
    time: timeInput.value,
    team_ids: checkedValues('team'),
    label: labelInput.value.trim()
  };
  if (editingId) body.day = Number(daySelect.value);
  else body.days = checkedValues('day');

  saveBtn.disabled = true;
  try {
    const { res, data } = await api(editingId ? `${API}/${editingId}` : API, {
      method: editingId ? 'PATCH' : 'POST',
      body: JSON.stringify(body)
    });
    if (!res.ok || !data.ok) {
      if (data.errors) showErrors(data.errors);
      flash(data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно запазване.'), true);
      return;
    }
    const message = editingId ? 'Запазено ✓' : (data.slots.length > 1 ? `Добавени ${data.slots.length} слота ✓` : 'Добавен ✓');
    resetForm();
    await load();
    flash(message);
  } catch (err) {
    flash('Няма връзка със сървъра. Опитай пак.', true);
  } finally {
    saveBtn.disabled = false;
  }
}

async function removeSlot(slot) {
  if (!confirm(`Да изтрия ли слота ${slot.day_name} ${slot.time} (${slot.shown || 'без отбор'})?`)) return;
  try {
    const { res, data } = await api(`${API}/${slot.id}`, { method: 'DELETE' });
    if (!res.ok || !data.ok) throw new Error(data.error || 'delete');
    if (editingId === slot.id) resetForm();
    await load();
    flash('Изтрит ✓');
  } catch (err) {
    flash('Неуспешно изтриване. Опитай пак.', true);
  }
}

// ------------------------------------------------------------ list ---
function renderList() {
  listEl.textContent = '';
  if (!slots.length) {
    listEl.append(el('p', 'user-hint', 'Още няма слотове. Добавете първия с формата отгоре.'));
    return;
  }
  days.forEach(day => {
    const daySlots = slots.filter(s => s.day === day.number);
    if (!daySlots.length) return;

    const card = el('section', 'day-card');
    card.append(el('h2', '', day.name));
    const table = el('table', 'admin-table slot-table');
    const body = el('tbody');
    daySlots.forEach(slot => {
      const tr = el('tr');
      if (!slot.visible) tr.className = 'is-archived';
      tr.append(el('td', 'slot-time-cell', slot.time));

      const who = el('td');
      who.append(el('strong', '', slot.shown || '—'));
      if (slot.team_names.length) who.append(el('span', 'slot-teams', ' · ' + slot.team_names.join(', ')));
      if (!slot.visible) who.append(el('span', 'mini-badge', 'скрит (отборът е архивиран)'));
      tr.append(who);

      const actions = el('td');
      const row = el('div', 'row-actions');
      const edit = el('button', 'btn btn-outline btn-sm', 'Редактирай');
      edit.type = 'button';
      edit.addEventListener('click', () => startEdit(slot));
      const del = el('button', 'btn btn-outline btn-sm btn-danger-text', 'Изтрий');
      del.type = 'button';
      del.addEventListener('click', () => removeSlot(slot));
      row.append(edit, del);
      actions.append(row);
      tr.append(actions);
      body.append(tr);
    });
    table.append(body);
    card.append(table);
    listEl.append(card);
  });
}

async function load() {
  const { res, data } = await api(API);
  if (!res.ok || !data.ok) throw new Error('api');
  days = data.days;
  teams = data.teams;
  slots = data.slots;
  // Формата се прави само първия път, за да не се губят отметките при презареждане.
  if (!dayChecks.children.length) buildForm();
  renderList();
  statusEl.classList.remove('error', 'saved');
  statusEl.textContent = summary();
}

saveBtn.addEventListener('click', save);
cancelBtn.addEventListener('click', resetForm);
$('#slotForm').addEventListener('submit', (e) => e.preventDefault());

load().catch(() => {
  statusEl.classList.add('error');
  statusEl.textContent = 'Неуспешно зареждане. Провери дали backend-ът работи.';
});
