const statusEl = document.querySelector('#adminStatus');
const formStatus = document.querySelector('#formStatus');
const table = document.querySelector('#usersTable');
const tbody = document.querySelector('#usersBody');
const form = document.querySelector('#newUserForm');

function setStatus(el, text, kind) {
  el.textContent = text;
  el.classList.remove('error', 'saved');
  if (kind) el.classList.add(kind);
}

function fmt(iso) {
  if (!iso) return 'още не е влизал';
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
  return d.toLocaleString('bg-BG', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// 14 characters, no look-alikes (0/O, 1/l/I), uses the browser's secure random
function generatePassword() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
  const bytes = new Uint32Array(14);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, b => chars[b % chars.length]).join('');
}

async function api(path, method = 'GET', body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

function firstError(data) {
  if (data.errors) return Object.values(data.errors)[0];
  return data.error || 'Грешка.';
}

async function load() {
  const { ok, data } = await api('/api/admin/users');
  if (!ok) { setStatus(statusEl, firstError(data), 'error'); return; }
  render(data.users);
}

function render(users) {
  tbody.innerHTML = '';
  users.forEach(u => {
    const tr = document.createElement('tr');
    const owner = u.role === 'owner';
    const cells = [
      u.username,
      u.display_name,
      owner ? 'Главен админ' : 'Треньор',
      u.is_active ? 'Активен' : 'Изключен',
      fmt(u.last_login_at)
    ];
    cells.forEach(text => {
      const td = document.createElement('td');
      td.textContent = text;
      tr.appendChild(td);
    });
    const actions = document.createElement('td');
    if (owner) {
      actions.textContent = '—';
    } else {
      actions.append(
        button(u.is_active ? 'Изключи' : 'Включи', () => toggle(u)),
        button('Нова парола', () => resetPassword(u)),
        button('Изтрий', () => remove(u), true)
      );
    }
    tr.appendChild(actions);
    tbody.appendChild(tr);
  });
  table.hidden = false;
  setStatus(statusEl, `Акаунти: ${users.length}`);
}

function button(label, onClick, danger) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'row-btn' + (danger ? ' danger' : '');
  b.textContent = label;
  b.addEventListener('click', onClick);
  return b;
}

async function toggle(u) {
  const { ok, data } = await api(`/api/admin/users/${u.id}`, 'PATCH', { is_active: !u.is_active });
  if (!ok) return setStatus(statusEl, firstError(data), 'error');
  load();
}

async function resetPassword(u) {
  const suggested = generatePassword();
  const pw = prompt(`Нова парола за „${u.username}“ (поне 8 символа).\nПредложена е случайна — можете да я промените:`, suggested);
  if (pw === null) return;
  const { ok, data } = await api(`/api/admin/users/${u.id}`, 'PATCH', { password: pw });
  if (!ok) return setStatus(statusEl, firstError(data), 'error');
  alert(`Паролата на „${u.username}“ е сменена.\n\nНова парола: ${pw}\n\nДайте я на треньора — старите му сесии са прекратени.`);
  load();
}

async function remove(u) {
  if (!confirm(`Да изтрия ли акаунта „${u.username}“? Действието не може да се върне.`)) return;
  const { ok, data } = await api(`/api/admin/users/${u.id}`, 'DELETE');
  if (!ok) return setStatus(statusEl, firstError(data), 'error');
  load();
}

document.querySelector('#genBtn').addEventListener('click', () => {
  form.password.value = generatePassword();
});

form.addEventListener('submit', async e => {
  e.preventDefault();
  const payload = {
    username: form.username.value,
    display_name: form.display_name.value,
    password: form.password.value
  };
  const { ok, data } = await api('/api/admin/users', 'POST', payload);
  if (!ok) return setStatus(formStatus, firstError(data), 'error');
  setStatus(formStatus, `Акаунтът „${data.user.username}“ е създаден. Парола: ${payload.password}  (запишете я сега)`, 'saved');
  form.reset();
  load();
});

load();
