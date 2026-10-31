// Админ „Треньори“: акаунти + профили (снимка, биография, отбори).
// Достъпно за главен админ и главен треньор; главният треньор управлява само обикновени треньори.
const API = '/api/admin/coaches';
const MAX_BYTES = 20 * 1024 * 1024;
const $ = (sel) => document.querySelector(sel);

const statusEl = $('#status');
const form = $('#coachForm');
const body = $('#coachBody');
const table = $('#coachTable');
const saveBtn = $('#saveBtn');
const photoInput = $('#f-photo');

let coaches = [];
let teams = [];
let groups = [];
let meId = null;
let editing = null; // треньорът, който се редактира (null = нов)
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
    statusEl.textContent = `Треньори: ${coaches.length}`;
  }, isError ? 6000 : 2500);
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

function generatePassword() {
  const chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789';
  const bytes = crypto.getRandomValues(new Uint8Array(12));
  return [...bytes].map(b => chars[b % chars.length]).join('');
}

// ------------------------------------------------------------- списък ---
function statusText(c) {
  const parts = [c.is_active ? 'Активен' : 'Изключен'];
  if (!c.show_on_site) parts.push('скрит от сайта');
  return parts.join(' · ');
}

function renderList() {
  body.textContent = '';
  coaches.forEach(c => {
    const tr = el('tr');

    const who = el('td', 'coach-cell');
    if (c.photo) {
      const img = el('img', 'coach-thumb');
      img.src = c.photo; img.alt = '';
      who.append(img);
    }
    const info = el('div');
    const name = el('strong', '', c.display_name);
    if (c.is_head) name.append(el('span', 'mini-badge', 'главен треньор'));
    info.append(name, el('div', 'coach-user', c.username));
    who.append(info);
    tr.append(who);

    const leads = [...c.team_labels, ...c.group_labels];
    tr.append(el('td', '', leads.length ? leads.join(', ') : '—'));
    const st = el('td');
    st.append(el('span', `status-pill ${c.is_active ? 'is-published' : 'is-draft'}`, statusText(c)));
    tr.append(st);

    const actions = el('td');
    const row = el('div', 'row-actions');
    row.append(btn('Редактирай', () => openForm(c)));
    if (!c.is_head) {
      row.append(
        btn(c.is_active ? 'Изключи' : 'Включи', () => toggleActive(c)),
        btn('Нова парола', () => resetPassword(c)),
        btn('Изтрий', () => remove(c), true)
      );
    }
    actions.append(row);
    tr.append(actions);
    body.append(tr);
  });
  table.hidden = false;
  statusEl.textContent = coaches.length ? `Треньори: ${coaches.length}` : 'Още няма треньори.';
}

function btn(text, onClick, danger = false) {
  const b = el('button', 'btn btn-outline btn-sm' + (danger ? ' btn-danger-text' : ''), text);
  b.type = 'button';
  b.addEventListener('click', onClick);
  return b;
}

async function load() {
  const { res, data } = await api(API);
  if (!res.ok || !data.ok) throw new Error('api');
  coaches = data.coaches;
  teams = data.teams;
  groups = data.groups || [];
  meId = data.me;
  renderList();
}

// ------------------------------------------------------------- действия ---
async function toggleActive(c) {
  const { res, data } = await api(`${API}/${c.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !c.is_active }) });
  if (!res.ok || !data.ok) { flash((data.errors && Object.values(data.errors)[0]) || data.error || 'Неуспешна промяна.', true); return; }
  await load();
}

async function resetPassword(c) {
  const pw = prompt(`Нова парола за „${c.username}“ (поне 8 символа).\nПредложена е случайна — можете да я промените:`, generatePassword());
  if (pw === null) return;
  const { res, data } = await api(`${API}/${c.id}`, { method: 'PATCH', body: JSON.stringify({ password: pw }) });
  if (!res.ok || !data.ok) { flash((data.errors && data.errors.password) || data.error || 'Неуспешна смяна.', true); return; }
  alert(`Паролата на „${c.username}“ е сменена.\n\nНова парола: ${pw}\n\nДайте я на треньора — старите му сесии са прекратени.`);
}

async function remove(c) {
  if (!confirm(`Да изтрия ли треньора „${c.display_name}“? Ще се премахнат акаунтът, картата му от сайта и снимката. Не може да се върне.`)) return;
  const { res, data } = await api(`${API}/${c.id}`, { method: 'DELETE' });
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно изтриване.', true); return; }
  if (editing && editing.id === c.id) closeForm();
  await load();
  flash('Треньорът е изтрит ✓');
}

// ----------------------------------------------------------------- форма ---
function buildTeamChecks(selected, selectedGroups) {
  const box = $('#teamChecks');
  box.textContent = '';
  const add = (name, id, text, checked) => {
    const label = el('label', 'check-item');
    const input = document.createElement('input');
    input.type = 'checkbox'; input.name = name; input.value = id;
    input.checked = checked;
    label.append(input, el('span', '', text));
    box.append(label);
  };
  teams.forEach(t => add('team', t.id, t.cohort ? `${t.label} · ${t.cohort}` : t.label, selected.includes(t.id)));
  // Групи без отбор (напр. „Вратари — големи“) — управляват се от „График“
  groups.forEach(g => add('group', g.id, g.name, selectedGroups.includes(g.id)));
}

function checkedTeams() {
  return [...document.querySelectorAll('input[name="team"]:checked')].map(i => Number(i.value));
}

function checkedGroups() {
  return [...document.querySelectorAll('input[name="group"]:checked')].map(i => Number(i.value));
}

function updatePhotoPreview() {
  const img = $('#photoPreview');
  const has = editing && editing.photo;
  img.hidden = !has;
  if (has) img.src = editing.photo;
  $('#removePhotoBtn').hidden = !has;
}

function openForm(c) {
  editing = c || null;
  clearErrors();
  $('#formTitle').textContent = c ? `Редакция: ${c.display_name}` : 'Нов треньор';
  $('#accountFields').hidden = !!c;  // потребителско име и парола — само при създаване
  $('#f-username').value = '';
  $('#f-password').value = c ? '' : generatePassword();
  $('#f-name').value = c ? c.display_name : '';
  $('#f-bio').value = c ? c.bio : '';
  $('#bioCount').textContent = $('#f-bio').value.length;
  $('#f-show').checked = c ? c.show_on_site : true;
  photoInput.value = '';
  buildTeamChecks(c ? c.team_ids : [], c ? c.group_ids : []);
  updatePhotoPreview();
  saveBtn.textContent = c ? 'Запази' : 'Създай';
  form.hidden = false;
  form.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeForm() {
  editing = null;
  form.hidden = true;
}

async function uploadPhoto(id) {
  const file = photoInput.files[0];
  if (!file) return true;
  if (file.size > MAX_BYTES) {
    showErrors({ photo: 'Снимката е над 20 MB.' });
    return false;
  }
  const fd = new FormData();
  fd.append('image', file);
  const res = await fetch(`${API}/${id}/photo`, { method: 'POST', body: fd });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.ok) {
    showErrors({ photo: data.error || 'Снимката не можа да се качи.' });
    return false;
  }
  return true;
}

async function save() {
  clearErrors();
  saveBtn.disabled = true;
  try {
    const profile = {
      display_name: $('#f-name').value,
      bio: $('#f-bio').value,
      show_on_site: $('#f-show').checked,
      team_ids: checkedTeams(),
      group_ids: checkedGroups()
    };
    if (editing) {
      const { res, data } = await api(`${API}/${editing.id}`, { method: 'PATCH', body: JSON.stringify(profile) });
      if (!res.ok || !data.ok) {
        showErrors(data.errors);
        flash(data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно запазване.'), true);
        return;
      }
      const photoOk = await uploadPhoto(editing.id);
      await load();
      editing = coaches.find(x => x.id === editing.id) || null;
      if (editing) openFormKeepScroll(editing);
      flash(photoOk ? 'Запазено ✓' : 'Запазено, но снимката не се качи.', !photoOk);
    } else {
      const username = $('#f-username').value;
      const password = $('#f-password').value;
      const { res, data } = await api(API, { method: 'POST', body: JSON.stringify({ ...profile, username, password }) });
      if (!res.ok || !data.ok) {
        showErrors(data.errors);
        flash(data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно създаване.'), true);
        return;
      }
      const created = data.coach;
      const photoOk = await uploadPhoto(created.id);
      closeForm();
      await load();
      alert(`Треньорът е създаден.\n\nПотребител: ${created.username}\nПарола: ${password}\n\nДайте ги на треньора — паролата не се показва повторно.`);
      flash(photoOk ? 'Треньорът е създаден ✓' : 'Треньорът е създаден, но снимката не се качи — добавете я от „Редактирай“.', !photoOk);
    }
  } catch (err) {
    flash('Няма връзка със сървъра. Опитай пак.', true);
  } finally {
    saveBtn.disabled = false;
  }
}

function openFormKeepScroll(c) {
  const y = window.scrollY;
  openForm(c);
  window.scrollTo(0, y);
}

$('#removePhotoBtn').addEventListener('click', async () => {
  if (!editing || !confirm('Да махна ли снимката на този треньор?')) return;
  const { res, data } = await api(`${API}/${editing.id}/photo`, { method: 'DELETE' });
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно махане.', true); return; }
  await load();
  editing = coaches.find(x => x.id === editing.id) || null;
  updatePhotoPreview();
  flash('Снимката е махната ✓');
});

$('#genBtn').addEventListener('click', () => { $('#f-password').value = generatePassword(); });
$('#f-bio').addEventListener('input', () => { $('#bioCount').textContent = $('#f-bio').value.length; });
$('#newBtn').addEventListener('click', () => openForm(null));
$('#cancelBtn').addEventListener('click', closeForm);
saveBtn.addEventListener('click', save);
form.addEventListener('submit', (e) => e.preventDefault());

load().catch(() => {
  statusEl.classList.add('error');
  statusEl.textContent = 'Неуспешно зареждане. Нямате права или backend-ът не работи.';
});
