// Админ „Отбори“: списък + панел на един отбор (?team=<id>) или нов (?team=new).
const API = '/api/admin/teams';

const $ = (sel) => document.querySelector(sel);
const listView = $('#listView');
const panelView = $('#panelView');
const listStatus = $('#listStatus');
const panelStatus = $('#panelStatus');
const teamsTable = $('#teamsTable');
const teamsBody = $('#teamsBody');
const form = $('#teamForm');
const saveBtn = $('#saveBtn');
const archiveBtn = $('#archiveBtn');
const deleteBtn = $('#deleteBtn');

let teams = [];
let seasonText = '';
let seasonEnd = 0;
let current = null; // отборът в панела (null = нов)
let statusTimer = null;

// ------------------------------------------------------------ helpers ---
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

function flash(el, text, isError = false, resetText = '') {
  clearTimeout(statusTimer);
  el.classList.toggle('error', isError);
  el.classList.toggle('saved', !isError);
  el.textContent = text;
  statusTimer = setTimeout(() => {
    el.classList.remove('error', 'saved');
    el.textContent = resetText;
  }, isError ? 5000 : 2500);
}

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

function cohortOf(t) {
  return t.kind === 'men' ? '—' : t.cohort;
}

function teamName(t) {
  return t.kind === 'men' ? 'MEN' : t.u_label;
}

function isArchived(t) {
  return t.status === 'archived';
}

function refreshMenu() {
  if (typeof window.refreshTeamsMenu === 'function') window.refreshTeamsMenu();
}

// --------------------------------------------------------------- list ---
function rowHtml(t) {
  const archived = isArchived(t);
  const manual = t.u_override ? ' <span class="mini-badge">ръчен етикет</span>' : '';
  return `
    <tr data-id="${t.id}" class="${archived ? 'is-archived' : ''}">
      <td class="title-cell"><strong>${escapeHtml(teamName(t))}</strong>${manual}</td>
      <td>${escapeHtml(cohortOf(t))}</td>
      <td class="message-cell">${escapeHtml(t.description || '—')}</td>
      <td><span class="status-pill ${archived ? 'is-draft' : 'is-published'}">${archived ? 'Архивиран' : 'Активен'}</span></td>
      <td>
        <div class="row-actions">
          <a class="btn btn-outline btn-sm" href="admin-teams.html?team=${t.id}">Отвори</a>
          <button class="btn btn-outline btn-sm js-toggle" type="button">${archived ? 'Възстанови' : 'Архивирай'}</button>
        </div>
      </td>
    </tr>`;
}

function renderList() {
  teamsBody.innerHTML = teams.length
    ? teams.map(rowHtml).join('')
    : '<tr><td colspan="5" class="empty-state">Още няма отбори. Натиснете „Нов отбор“.</td></tr>';
  const active = teams.filter(t => !isArchived(t)).length;
  listStatus.textContent = `Сезон ${seasonText} · Активни: ${active} · Архивирани: ${teams.length - active}`;
}

async function loadTeams() {
  const { res, data } = await api(API);
  if (!res.ok || !data.ok) throw new Error('api');
  teams = data.teams || [];
  seasonText = data.season || '';
  seasonEnd = data.season_end_year || 0;
}

async function loadList() {
  listStatus.classList.remove('error', 'saved');
  listStatus.textContent = 'Зареждане...';
  teamsTable.hidden = true;
  try {
    await loadTeams();
    renderList();
    teamsTable.hidden = false;
  } catch (err) {
    listStatus.classList.add('error');
    listStatus.textContent = 'Неуспешно зареждане. Провери дали backend-ът работи.';
  }
}

async function setStatus(team, status) {
  const { res, data } = await api(`${API}/${team.id}`, { method: 'PATCH', body: JSON.stringify({ status }) });
  if (!res.ok || !data.ok) throw new Error(data.error || 'status');
  return data.team;
}

teamsBody.addEventListener('click', async (e) => {
  const btn = e.target.closest('.js-toggle');
  const tr = e.target.closest('tr[data-id]');
  if (!btn || !tr) return;
  const team = teams.find(t => t.id === Number(tr.dataset.id));
  if (!team) return;
  const archiving = !isArchived(team);
  if (archiving && !confirm(`Да архивирам ли ${teamName(team)}? Отборът ще изчезне от сайта, но данните му се пазят.`)) return;
  btn.disabled = true;
  try {
    await setStatus(team, archiving ? 'archived' : 'active');
    await loadList();
    refreshMenu();
  } catch (err) {
    flash(listStatus, 'Неуспешна промяна. Опитай пак.', true);
    btn.disabled = false;
  }
});

$('#refreshBtn').addEventListener('click', loadList);

// -------------------------------------------------------------- panel ---
const kindSel = $('#f-kind');
const yearsRow = $('#yearsRow');
const fromInput = $('#f-from');
const toInput = $('#f-to');
const labelInput = $('#f-label');
const descInput = $('#f-desc');
const labelHint = $('#labelHint');

function clearErrors() {
  form.querySelectorAll('.field-error').forEach(el => { el.textContent = ''; });
}

function showErrors(errors) {
  clearErrors();
  Object.entries(errors || {}).forEach(([field, msg]) => {
    const el = form.querySelector(`[data-error-for="${field}"]`);
    if (el) el.textContent = msg;
  });
}

function updateKind() {
  yearsRow.hidden = kindSel.value === 'men';
  updateHint();
}

function updateHint() {
  if (kindSel.value === 'men') {
    labelHint.textContent = 'Мъжкият отбор се показва като MEN.';
    return;
  }
  const from = parseInt(fromInput.value, 10);
  const manual = labelInput.value.trim();
  let text = 'Въведете набор, за да видите автоматичния етикет.';
  if (from && seasonEnd) {
    text = `Автоматично за сезон ${seasonText}: U${seasonEnd - from}.`;
    if (manual) text += ` На сайта ще се показва: ${manual}.`;
  }
  labelHint.textContent = text;
}

function updateCount() {
  $('#descCount').textContent = descInput.value.length;
}

function fillForm(t) {
  kindSel.value = t ? t.kind : 'youth';
  kindSel.disabled = !!t; // видът не се сменя след създаване
  fromInput.value = t && t.birth_year_from ? t.birth_year_from : '';
  toInput.value = t && t.birth_year_to ? t.birth_year_to : '';
  labelInput.value = t ? t.u_override : '';
  descInput.value = t ? t.description : '';
  clearErrors();
  updateKind();
  updateCount();
}

function refreshPanelButtons() {
  const exists = !!current;
  const archived = exists && isArchived(current);
  $('#panelTitle').textContent = exists
    ? `${teamName(current)}${current.kind === 'men' ? '' : ' · ' + cohortOf(current)}`
    : 'Нов отбор';
  $('#statusRow').hidden = !exists;
  $('#soonBox').hidden = !exists;
  if (exists) {
    const pill = $('#statusPill');
    pill.textContent = archived ? 'Архивиран — скрит от сайта' : 'Активен';
    pill.className = `status-pill ${archived ? 'is-draft' : 'is-published'}`;
  }
  archiveBtn.hidden = !exists;
  archiveBtn.textContent = archived ? 'Възстанови' : 'Архивирай';
  // Истинско изтриване: само главният админ и само за вече архивиран отбор.
  deleteBtn.hidden = !(archived && window.adminUser && window.adminUser.role === 'owner');
  const view = $('#viewLink');
  view.hidden = !(exists && !archived);
  if (exists) view.href = current.url;
}

function openPanel(team) {
  current = team;
  listView.hidden = true;
  panelView.hidden = false;
  fillForm(team);
  refreshPanelButtons();
  document.title = (team ? teamName(team) : 'Нов отбор') + ' — Админ — ФА Герман';
}

function payload() {
  const data = {
    u_override: labelInput.value.trim(),
    description: descInput.value.trim()
  };
  if (!current) data.kind = kindSel.value;
  if (kindSel.value === 'youth') {
    data.birth_year_from = fromInput.value.trim();
    data.birth_year_to = toInput.value.trim();
  }
  return data;
}

function setBusy(busy) {
  [saveBtn, archiveBtn, deleteBtn].forEach(b => { b.disabled = busy; });
}

async function save() {
  clearErrors();
  setBusy(true);
  try {
    const { res, data } = await api(current ? `${API}/${current.id}` : API, {
      method: current ? 'PATCH' : 'POST',
      body: JSON.stringify(payload())
    });
    if (!res.ok || !data.ok) {
      if (data.errors) showErrors(data.errors);
      flash(panelStatus, data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно запазване.'), true);
      return;
    }
    if (!current) {
      // Нов отбор: отваряме го като съществуващ (и менюто „Отбори“ се опреснява).
      location.replace(`admin-teams.html?team=${data.team.id}`);
      return;
    }
    current = data.team;
    fillForm(current);
    refreshPanelButtons();
    flash(panelStatus, 'Запазено ✓');
    refreshMenu();
  } catch (err) {
    flash(panelStatus, 'Няма връзка със сървъра. Опитай пак.', true);
  } finally {
    setBusy(false);
  }
}

async function toggleArchive() {
  if (!current) return;
  const archiving = !isArchived(current);
  if (archiving && !confirm(`Да архивирам ли ${teamName(current)}? Отборът ще изчезне от сайта, но данните му се пазят.`)) return;
  setBusy(true);
  try {
    current = await setStatus(current, archiving ? 'archived' : 'active');
    refreshPanelButtons();
    flash(panelStatus, archiving ? 'Архивиран ✓' : 'Възстановен ✓');
    refreshMenu();
  } catch (err) {
    flash(panelStatus, 'Неуспешна промяна. Опитай пак.', true);
  } finally {
    setBusy(false);
  }
}

async function deleteForever() {
  if (!current || !isArchived(current)) return;
  if (!confirm(`Да изтрия ли ${teamName(current)} ЗАВИНАГИ? Това не може да се върне.`)) return;
  setBusy(true);
  try {
    const { res, data } = await api(`${API}/${current.id}`, { method: 'DELETE' });
    if (!res.ok || !data.ok) throw new Error(data.error || 'delete');
    location.replace('admin-teams.html');
  } catch (err) {
    flash(panelStatus, 'Неуспешно изтриване. Опитай пак.', true);
    setBusy(false);
  }
}

kindSel.addEventListener('change', updateKind);
[fromInput, labelInput].forEach(el => el.addEventListener('input', updateHint));
descInput.addEventListener('input', updateCount);
saveBtn.addEventListener('click', save);
archiveBtn.addEventListener('click', toggleArchive);
deleteBtn.addEventListener('click', deleteForever);
form.addEventListener('submit', (e) => e.preventDefault());

// -------------------------------------------------------------- start ---
(async function init() {
  const param = new URLSearchParams(location.search).get('team');
  if (!param) {
    await loadList();
    return;
  }
  try {
    await loadTeams();
  } catch (err) {
    listStatus.classList.add('error');
    listStatus.textContent = 'Неуспешно зареждане. Провери дали backend-ът работи.';
    return;
  }
  if (param === 'new') {
    openPanel(null);
    return;
  }
  const team = teams.find(t => t.id === Number(param));
  if (!team) {
    listStatus.classList.add('error');
    listStatus.textContent = 'Отборът не е намерен.';
    return;
  }
  openPanel(team);
})();
