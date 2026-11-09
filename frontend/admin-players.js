// Админ „Футболисти“: профили на деца + родителски акаунти (временна парола по имейл).
const API = '/api/admin/players';
const $ = (sel) => document.querySelector(sel);

const statusEl = $('#status');
const form = $('#playerForm');
const table = $('#playersTable');
const body = $('#playersBody');
const head = $('#playersHead');
const saveBtn = $('#saveBtn');
const f = {
  child: $('#f-child'), birth: $('#f-birth'), start: $('#f-start'), parent: $('#f-parent'),
  phone: $('#f-phone'), email: $('#f-email'), status: $('#f-status'), team: $('#f-team'), notes: $('#f-notes')
};

let players = [];
let teams = [];
let canEdit = false;
let editing = null;          // профилът, който се редактира (null = нов)
let fromRegistration = null; // id на запитването, от което се създава профилът
let statusTimer = null;
let searchTimer = null;

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
    statusEl.textContent = summary();
  }, isError ? 7000 : 3500);
}

function summary() {
  return `Профили: ${players.length}`;
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

function fmtDate(iso) {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-');
  return `${d}.${m}.${y}`;
}

function emailMessage(status) {
  if (status === 'sent') return 'Имейлът до родителя е изпратен ✓';
  if (status === 'dry_run') return 'Тестов режим: имейлът не е изпратен реално (няма настроен MAIL_SERVER).';
  return 'Имейлът НЕ можа да бъде изпратен. Използвайте „Нова парола“, за да опитате пак.';
}

// ------------------------------------------------------------ списък ---
function headRow() {
  const cols = canEdit
    ? ['Дете', 'Отбор', 'Родител', 'Статус', 'Вход в портала', '']
    : ['Дете', 'Отбор', 'Статус'];
  head.textContent = '';
  const tr = el('tr');
  cols.forEach(c => tr.append(el('th', '', c)));
  head.append(tr);
}

function portalText(p) {
  const par = p.parent;
  if (!par.is_active) return 'достъпът е спрян';
  if (!par.last_login_at) return par.must_change_password ? 'още не е влизал' : 'не е влизал';
  return par.must_change_password ? 'чака смяна на парола' : 'активен';
}

function btn(text, onClick, danger = false) {
  const b = el('button', 'btn btn-outline btn-sm' + (danger ? ' btn-danger-text' : ''), text);
  b.type = 'button';
  b.addEventListener('click', onClick);
  return b;
}

function renderList() {
  headRow();
  body.textContent = '';
  if (!players.length) {
    const tr = el('tr');
    const td = el('td', 'empty-state', 'Няма профили по тези филтри.');
    td.colSpan = canEdit ? 6 : 3;
    tr.append(td);
    body.append(tr);
  }
  players.forEach(p => {
    const tr = el('tr');
    if (p.archived) tr.className = 'is-archived';

    const who = el('td');
    who.append(el('strong', '', p.child_name), el('div', 'reg-sub', `род. ${fmtDate(p.birth_date)}`));
    tr.append(who);

    const team = el('td');
    team.append(el('span', '', p.team_label || 'без отбор'));
    if (p.team_manual) team.append(el('span', 'mini-badge', 'ръчно'));
    tr.append(team);

    if (canEdit) {
      const par = el('td');
      par.append(el('span', 'reg-parent', p.parent.name), el('span', 'reg-line', p.parent.phone), el('span', 'reg-line reg-email', p.parent.email));
      tr.append(par);
    }

    const st = el('td');
    st.append(el('span', `status-pill ${p.status === 'active' && !p.archived ? 'is-published' : 'is-draft'}`, p.archived ? 'Архивиран' : p.status_label));
    tr.append(st);

    if (canEdit) {
      tr.append(el('td', '', portalText(p)));
      const actions = el('td');
      const row = el('div', 'row-actions');
      row.append(btn('Редактирай', () => openForm(p)));
      if (!p.archived) {
        row.append(btn('Нова парола', () => newPassword(p)), btn('Архивирай', () => archive(p)));
      } else {
        row.append(btn('Възстанови', () => restore(p)));
        if (window.adminUser && window.adminUser.role === 'owner') row.append(btn('Изтрий завинаги', () => purge(p), true));
      }
      actions.append(row);
      tr.append(actions);
    }
    body.append(tr);
  });
  table.hidden = false;
  statusEl.textContent = summary();
}

function renderFilters() {
  const sel = $('#teamFilter');
  const current = sel.value;
  sel.textContent = '';
  const all = el('option', '', 'Всички'); all.value = '';
  sel.append(all);
  teams.forEach(t => { const o = el('option', '', t.label); o.value = t.id; sel.append(o); });
  sel.value = current;

  f.team.textContent = '';
  const auto = el('option', '', 'Автоматично (по година на раждане)'); auto.value = '';
  f.team.append(auto);
  teams.forEach(t => { const o = el('option', '', t.label); o.value = t.id; f.team.append(o); });
}

async function load() {
  const params = new URLSearchParams();
  if ($('#q').value.trim()) params.set('q', $('#q').value.trim());
  if ($('#teamFilter').value) params.set('team', $('#teamFilter').value);
  if ($('#statusFilter').value) params.set('status', $('#statusFilter').value);
  if ($('#archivedFilter').checked) params.set('archived', '1');
  const { res, data } = await api(`${API}?${params}`);
  if (!res.ok || !data.ok) throw new Error('api');
  players = data.players;
  teams = data.teams;
  canEdit = data.can_edit;
  $('#newBtn').hidden = !canEdit;
  renderFilters();
  renderList();
}

// ------------------------------------------------------------- форма ---
function updateTeamHint() {
  const hint = $('#teamHint');
  hint.textContent = '';
  if (!f.birth.value) return;
  const year = Number(f.birth.value.slice(0, 4));
  hint.textContent = `Набор ${year}.`;
}

function resetForm() {
  editing = null;
  fromRegistration = null;
  clearErrors();
  [f.child, f.birth, f.start, f.parent, f.phone, f.email, f.notes].forEach(i => { i.value = ''; });
  f.status.value = 'active';
  f.team.value = '';
  f.email.disabled = false;
  $('#fromBox').hidden = true;
  $('#emailHint').textContent = 'Ако родителят вече има акаунт с този имейл, детето се добавя към него (без нова парола).';
  $('#statusField').hidden = true;
  $('#createHint').hidden = false;
  $('#formTitle').textContent = 'Нов футболист';
  saveBtn.textContent = 'Създай профил';
  updateTeamHint();
}

function openForm(player) {
  resetForm();
  if (player) {
    editing = player;
    f.child.value = player.child_name;
    f.birth.value = player.birth_date || '';
    f.start.value = player.start_date || '';
    f.parent.value = player.parent.name;
    f.phone.value = player.parent.phone;
    f.email.value = player.parent.email;
    f.email.disabled = true;
    $('#emailHint').textContent = 'Имейлът е потребителското име и не се сменя оттук. Името и телефонът са общи за всички деца на този родител.';
    f.status.value = player.status;
    f.team.value = player.team_override_id || '';
    f.notes.value = player.internal_notes || '';
    $('#statusField').hidden = false;
    $('#createHint').hidden = true;
    $('#formTitle').textContent = `Редакция: ${player.child_name}`;
    saveBtn.textContent = 'Запази';
    updateTeamHint();
  }
  form.hidden = false;
  form.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeForm() {
  form.hidden = true;
  resetForm();
  const url = new URL(location.href);
  if (url.searchParams.has('from')) { url.searchParams.delete('from'); history.replaceState(null, '', url); }
}

async function openFromRegistration(id) {
  const { res, data } = await api(`/api/admin/registrations/${id}/prefill`);
  if (!res.ok || !data.ok) { flash(data.error || 'Запитването не е намерено.', true); return; }
  openForm(null);
  fromRegistration = data.registration_id;
  f.child.value = data.child_name;
  f.parent.value = data.parent_name;
  f.phone.value = data.parent_phone;
  f.email.value = data.parent_email;
  const box = $('#fromBox');
  box.hidden = false;
  box.textContent = data.already_created
    ? 'За това запитване вече има създаден профил.'
    : `Данните са взети от запитването за пробна тренировка (дете на ${data.child_age} г.). Допълнете датата на раждане.`;
  f.birth.focus();
}

async function save() {
  clearErrors();
  const payload = {
    child_name: f.child.value, birth_date: f.birth.value || null, start_date: f.start.value || null,
    parent_name: f.parent.value, parent_phone: f.phone.value,
    team_override_id: f.team.value === '' ? null : Number(f.team.value),
    internal_notes: f.notes.value
  };
  saveBtn.disabled = true;
  try {
    let result;
    if (editing) {
      payload.status = f.status.value;
      result = await api(`${API}/${editing.id}`, { method: 'PATCH', body: JSON.stringify(payload) });
    } else {
      payload.parent_email = f.email.value;
      if (fromRegistration) payload.registration_id = fromRegistration;
      result = await api(API, { method: 'POST', body: JSON.stringify(payload) });
    }
    const { res, data } = result;
    if (!res.ok || !data.ok) {
      showErrors(data.errors);
      flash(data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно запазване.'), true);
      return;
    }
    const wasEditing = !!editing;
    const message = wasEditing
      ? 'Запазено ✓'
      : `Профилът е създаден ✓ ${data.parent_existing ? 'Детето е добавено към съществуващ родителски акаунт. ' : ''}${emailMessage(data.email_status)}`;
    closeForm();
    await load();
    flash(message, !wasEditing && data.email_status === 'failed');
  } catch (err) {
    flash('Няма връзка със сървъра. Опитай пак.', true);
  } finally {
    saveBtn.disabled = false;
  }
}

// ------------------------------------------------------------ действия ---
async function newPassword(p) {
  if (!confirm(`Да създам ли нова временна парола за ${p.parent.name} (${p.parent.email})?\n\nСтарата парола спира веднага, а новата се изпраща по имейл.`)) return;
  const { res, data } = await api(`${API}/${p.id}/new-password`, { method: 'POST' });
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно.', true); return; }
  await load();
  flash(emailMessage(data.email_status), data.email_status === 'failed');
}

async function archive(p) {
  if (!confirm(`Да архивирам ли профила на ${p.child_name}? Родителят губи достъп до него; данните се пазят.`)) return;
  const { res, data } = await api(`${API}/${p.id}/archive`, { method: 'POST' });
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно архивиране.', true); return; }
  await load();
  flash('Профилът е архивиран ✓');
}

async function restore(p) {
  const { res, data } = await api(`${API}/${p.id}/restore`, { method: 'POST' });
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно възстановяване.', true); return; }
  await load();
  flash('Профилът е възстановен ✓');
}

async function purge(p) {
  if (!confirm(`Да изтрия ли профила на ${p.child_name} ЗАВИНАГИ? Това не може да се върне.`)) return;
  const { res, data } = await api(`${API}/${p.id}?forever=1`, { method: 'DELETE' });
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно изтриване.', true); return; }
  await load();
  flash('Профилът е изтрит ✓');
}

// ------------------------------------------------------------- старт ---
$('#newBtn').addEventListener('click', () => openForm(null));
$('#cancelBtn').addEventListener('click', closeForm);
saveBtn.addEventListener('click', save);
form.addEventListener('submit', (e) => e.preventDefault());
f.birth.addEventListener('input', updateTeamHint);
['#teamFilter', '#statusFilter', '#archivedFilter'].forEach(s => $(s).addEventListener('change', () => load()));
$('#q').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(load, 300); });

resetForm();
load().then(() => {
  const from = Number(new URLSearchParams(location.search).get('from'));
  if (from && canEdit) openFromRegistration(from);
}).catch(() => {
  statusEl.classList.add('error');
  statusEl.textContent = 'Неуспешно зареждане. Провери дали backend-ът работи.';
});
