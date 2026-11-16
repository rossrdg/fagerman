// Админ „Известия“: известия към родителите (всички / отбор / дете), с дата на публикуване и край.
const API = '/api/admin/announcements';
const $ = (sel) => document.querySelector(sel);
const statusEl = $('#status');
const form = $('#annForm');
const saveBtn = $('#saveBtn');

let items = [];
let teams = [];
let mailConfigured = false;
let players = null;
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
  statusTimer = setTimeout(() => { statusEl.classList.remove('error', 'saved'); statusEl.textContent = summary(); }, isError ? 6000 : 3000);
}

function summary() {
  const active = items.filter(a => a.state === 'active').length;
  return `Известия: ${items.length} · показват се: ${active}`;
}

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

function clearErrors() { form.querySelectorAll('.field-error').forEach(e => { e.textContent = ''; }); }
function showErrors(errors) {
  clearErrors();
  Object.entries(errors || {}).forEach(([k, msg]) => { const t = form.querySelector(`[data-error-for="${k}"]`); if (t) t.textContent = msg; });
}

function audValue() { return document.querySelector('input[name="aud"]:checked').value; }
function syncAudience() {
  $('#audTeam').hidden = audValue() !== 'team';
  $('#audPlayer').hidden = audValue() !== 'player';
}
document.querySelectorAll('input[name="aud"]').forEach(r => r.addEventListener('change', syncAudience));

// ------------------------------------------------------------ списък ---
function btn(text, onClick, danger = false) {
  const b = el('button', 'btn btn-outline btn-sm' + (danger ? ' btn-danger-text' : ''), text);
  b.type = 'button';
  b.addEventListener('click', onClick);
  return b;
}

function render() {
  const body = $('#annBody');
  body.textContent = '';
  if (!items.length) {
    const tr = el('tr'); const td = el('td', 'empty-state', 'Още няма известия. Натиснете „Ново известие“.'); td.colSpan = 5; tr.append(td); body.append(tr);
  }
  items.forEach(a => {
    const tr = el('tr', a.state === 'hidden' || a.state === 'expired' ? 'is-archived' : '');
    const what = el('td', 'title-cell');
    what.append(el('strong', '', a.title), el('div', 'reg-sub', a.body.length > 110 ? a.body.slice(0, 110) + '…' : a.body));
    tr.append(what);
    tr.append(el('td', '', `${a.audience_text} (${a.recipients} ${a.recipients === 1 ? 'родител' : 'родители'})`));
    tr.append(el('td', '', `от ${a.publish_text}` + (a.expires_text ? ` до ${a.expires_text}` : '')));
    const st = el('td'); st.append(el('span', `status-pill ${a.state === 'active' ? 'is-published' : 'is-draft'}`, a.state_label));
    if (a.emailed_at) st.append(el('span', 'notified-badge', `✉ Изпратено до ${a.emailed_count} · ${fmtAt(a.emailed_at)}`));
    tr.append(st);
    const act = el('td'); const row = el('div', 'row-actions');
    const mail = btn('✉ Изпрати по имейл', () => sendEmail(a));
    if (!a.can_email) { mail.disabled = true; mail.title = 'По имейл се изпраща само известие, което се показва в портала в момента.'; }
    row.append(mail, btn('Редактирай', () => openForm(a)),
      btn(a.is_hidden ? 'Покажи' : 'Скрий', () => toggleHidden(a)),
      btn('Изтрий', () => remove(a), true));
    act.append(row); tr.append(act);
    body.append(tr);
  });
  $('#annTable').hidden = false;
  statusEl.textContent = summary();
}

async function load() {
  const { res, data } = await api(API);
  if (res.status === 403) { statusEl.classList.add('error'); statusEl.textContent = 'Нямате права за известията.'; return; }
  if (!res.ok || !data.ok) throw new Error('api');
  items = data.announcements;
  teams = data.teams;
  mailConfigured = !!data.mail_configured;
  render();
}

function fmtAt(iso) {
  if (!iso) return '';
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
  return d.toLocaleString('bg-BG', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

async function sendEmail(a) {
  const people = `${a.recipients} ${a.recipients === 1 ? 'родител' : 'родители'}`;
  let text = `Да изпратя ли известието „${a.title}“ по имейл до ${people}?`;
  if (a.emailed_at) text += `\n\nВече е изпращано на ${fmtAt(a.emailed_at)} (до ${a.emailed_count}). Ще се изпрати отново.`;
  if (!mailConfigured) text += '\n\nТестов режим: няма настроен MAIL_SERVER — имейлите няма да се изпратят реално, а само ще се запишат в лога на сървъра.';
  if (!confirm(text)) return;
  const { res, data } = await api(`${API}/${a.id}/send-email`, { method: 'POST' });
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно изпращане.', true); return; }
  await load();
  if (data.sent === 0 && data.dry_run > 0 && data.failed === 0) {
    flash(`Тестов режим: ${data.dry_run} ${data.dry_run === 1 ? 'имейл е записан' : 'имейла са записани'} в лога на сървъра (не ${data.dry_run === 1 ? 'е изпратен' : 'са изпратени'} реално).`);
  } else if (data.failed) {
    flash(`Изпратени: ${data.sent} от ${data.total}. Неуспешни: ${data.failed} (${data.failed_emails.join(', ')}).`, true);
  } else {
    flash(`Изпратено по имейл до ${data.sent} ${data.sent === 1 ? 'родител' : 'родители'} ✓`);
  }
}

async function toggleHidden(a) {
  const { res, data } = await api(`${API}/${a.id}`, { method: 'PATCH', body: JSON.stringify({ is_hidden: !a.is_hidden }) });
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно.', true); return; }
  await load();
  flash(a.is_hidden ? 'Известието отново се показва ✓' : 'Известието е скрито ✓');
}

async function remove(a) {
  if (!confirm(`Да изтрия ли известието „${a.title}“? Това не може да се върне.`)) return;
  const { res, data } = await api(`${API}/${a.id}`, { method: 'DELETE' });
  if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно изтриване.', true); return; }
  if (editing && editing.id === a.id) closeForm();
  await load();
  flash('Изтрито ✓');
}

// ------------------------------------------------------------- форма ---
function fillTeams() {
  const sel = $('#f-team');
  sel.textContent = '';
  teams.forEach(t => { const o = el('option', '', t.label); o.value = t.id; sel.append(o); });
  if (sel.options.length) sel.selectedIndex = 0;
}

async function loadPlayers() {
  if (players) return;
  const { data } = await api('/api/admin/players');
  players = (data.players || []).map(p => ({ id: p.id, label: `${p.child_name}${p.team_label ? ' · ' + p.team_label : ''}` }));
}

function renderPlayers(selected) {
  const sel = $('#f-player');
  const needle = $('#f-psearch').value.trim().toLowerCase();
  const keep = selected !== undefined ? selected : sel.value;
  sel.textContent = '';
  (players || []).filter(p => !needle || p.label.toLowerCase().includes(needle)).slice(0, 100).forEach(p => {
    const o = el('option', '', p.label); o.value = p.id; sel.append(o);
  });
  if (keep) sel.value = keep;
}
$('#f-psearch').addEventListener('input', () => renderPlayers());

function updateCount() { $('#bodyCount').textContent = $('#f-body').value.length; }
$('#f-body').addEventListener('input', updateCount);

async function openForm(a) {
  editing = a || null;
  clearErrors();
  await loadPlayers();
  fillTeams();
  $('#f-psearch').value = '';
  $('#formTitle').textContent = a ? `Редакция: ${a.title}` : 'Ново известие';
  $('#f-title').value = a ? a.title : '';
  $('#f-body').value = a ? a.body : '';
  document.querySelector(`input[name="aud"][value="${a ? a.audience : 'all'}"]`).checked = true;
  if (a && a.audience === 'team') $('#f-team').value = a.team_id;
  renderPlayers(a && a.audience === 'player' ? String(a.player_id) : '');
  $('#f-publish').value = a ? a.publish_date : '';
  $('#f-expires').value = a ? (a.expires_date || '') : '';
  $('#recipientsHint').textContent = a ? `Достига до ${a.recipients} ${a.recipients === 1 ? 'родител' : 'родители'}.` : '';
  saveBtn.textContent = a ? 'Запази' : 'Публикувай';
  syncAudience();
  updateCount();
  form.hidden = false;
  form.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeForm() { form.hidden = true; editing = null; }

async function save() {
  clearErrors();
  const aud = audValue();
  const payload = {
    title: $('#f-title').value, body: $('#f-body').value, audience: aud,
    publish_date: $('#f-publish').value || null, expires_date: $('#f-expires').value || null
  };
  if (aud === 'team') payload.team_id = $('#f-team').value ? Number($('#f-team').value) : null;
  if (aud === 'player') payload.player_id = $('#f-player').value ? Number($('#f-player').value) : null;
  saveBtn.disabled = true;
  try {
    const { res, data } = await api(editing ? `${API}/${editing.id}` : API, { method: editing ? 'PATCH' : 'POST', body: JSON.stringify(payload) });
    if (!res.ok || !data.ok) {
      showErrors(data.errors);
      flash(data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно запазване.'), true);
      return;
    }
    const a = data.announcement;
    closeForm();
    await load();
    flash(a.state === 'scheduled' ? `Известието е насрочено за ${a.publish_text} ✓` : `Известието е публикувано — достига до ${a.recipients} ${a.recipients === 1 ? 'родител' : 'родители'} ✓`);
  } catch (err) {
    flash('Няма връзка със сървъра. Опитай пак.', true);
  } finally {
    saveBtn.disabled = false;
  }
}

$('#newBtn').addEventListener('click', () => openForm(null));
$('#cancelBtn').addEventListener('click', closeForm);
saveBtn.addEventListener('click', save);
form.addEventListener('submit', (e) => e.preventDefault());

load().catch(() => { statusEl.classList.add('error'); statusEl.textContent = 'Неуспешно зареждане. Провери дали backend-ът работи.'; });
