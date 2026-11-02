// Админ „Мачове“: програма по кръгове, резултати и почивни кръгове на един отбор.
const API = '/api/admin/matches';
const $ = (sel) => document.querySelector(sel);

const statusEl = $('#status');
const listEl = $('#matchList');
const teamSelect = $('#teamSelect');
const seasonSelect = $('#seasonSelect');
const publicLink = $('#publicLink');
const saveBtn = $('#saveBtn');
const cancelBtn = $('#cancelBtn');

const f = {
  status: $('#f-status'), round: $('#f-round'), date: $('#f-date'), time: $('#f-time'),
  side: $('#f-side'), opponent: $('#f-opponent'), venue: $('#f-venue'),
  gf: $('#f-gf'), ga: $('#f-ga'), note: $('#f-note')
};

let teams = [];
let matches = [];
let seasons = [];
let currentSeason = null;   // текущият сезон на сайта (крайна година)
let teamId = Number(new URLSearchParams(location.search).get('team')) || null;
let seasonEnd = Number(new URLSearchParams(location.search).get('season')) || null;
let editingId = null;
let statusTimer = null;
let standingsUrl = null;

function flash(text, isError = false) {
  clearTimeout(statusTimer);
  statusEl.classList.toggle('error', isError);
  statusEl.classList.toggle('saved', !isError);
  statusEl.textContent = text;
  statusTimer = setTimeout(() => {
    statusEl.classList.remove('error', 'saved');
    statusEl.textContent = summary();
  }, isError ? 5000 : 2500);
}

function summary() {
  const real = matches.filter(m => m.status !== 'rest');
  const played = real.filter(m => m.status === 'played').length;
  return `Мачове: ${real.length} · изиграни: ${played} · предстоящи или без резултат: ${real.length - played}`;
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
  document.querySelectorAll('#matchForm .field-error').forEach(e => { e.textContent = ''; });
}

function showErrors(errors) {
  clearErrors();
  Object.entries(errors || {}).forEach(([field, msg]) => {
    const target = document.querySelector(`#matchForm [data-error-for="${field}"]`);
    if (target) target.textContent = msg;
  });
}

function teamText(t) {
  return t.kind === 'men' ? 'MEN' : `${t.u_label} · набор ${t.cohort}`;
}

function todayIso() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// ------------------------------------------------------------ form ---
// Почивен кръг няма съперник, час, място и резултат; отложеният и непроведеният нямат резултат.
function syncFormMode() {
  const status = f.status.value;
  const rest = status === 'rest';
  const noGoals = rest || status === 'postponed' || status === 'not_played';
  document.querySelectorAll('[data-hide-rest]').forEach(n => { n.hidden = rest; });
  document.querySelectorAll('[data-hide-nogoals]').forEach(n => { n.hidden = noGoals; });
  $('#dateReq').hidden = status === 'postponed' || status === 'not_played';
}

function nextRoundHint() {
  const rounds = matches.map(m => m.round_no || 0);
  return rounds.length ? Math.max(...rounds) + 1 : 1;
}

function resetForm() {
  editingId = null;
  clearErrors();
  f.status.value = 'scheduled';
  f.round.value = '';
  f.round.placeholder = String(nextRoundHint());
  f.date.value = '';
  f.time.value = '';
  f.side.value = 'home';
  f.opponent.value = '';
  f.venue.value = '';
  f.gf.value = '';
  f.ga.value = '';
  f.note.value = '';
  $('#formTitle').textContent = 'Нов мач';
  saveBtn.textContent = 'Добави';
  cancelBtn.hidden = true;
  syncFormMode();
}

function startEdit(m) {
  editingId = m.id;
  clearErrors();
  f.status.value = m.status;
  f.round.value = m.round_no ?? '';
  f.date.value = m.date || '';
  f.time.value = m.time || '';
  f.side.value = m.is_home ? 'home' : 'away';
  f.opponent.value = m.opponent;
  f.venue.value = m.venue;
  f.gf.value = m.goals_for ?? '';
  f.ga.value = m.goals_against ?? '';
  f.note.value = m.note;
  $('#formTitle').textContent = `Редакция: ${m.round_no ? 'Кръг ' + m.round_no : 'мач'}${m.opponent ? ' — ' + m.opponent : ''}`;
  saveBtn.textContent = 'Запази';
  cancelBtn.hidden = false;
  syncFormMode();
  $('#matchForm').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function formBody() {
  const rest = f.status.value === 'rest';
  const noGoals = rest || f.status.value === 'postponed' || f.status.value === 'not_played';
  const num = (input) => (input.value === '' ? null : Number(input.value));
  return {
    status: f.status.value,
    round_no: num(f.round),
    date: f.date.value || null,
    time: rest ? null : (f.time.value || null),
    is_home: rest ? true : f.side.value === 'home',
    opponent: rest ? '' : f.opponent.value,
    venue: rest ? '' : f.venue.value,
    goals_for: noGoals ? null : num(f.gf),
    goals_against: noGoals ? null : num(f.ga),
    note: f.note.value
  };
}

async function save() {
  clearErrors();
  const body = formBody();
  if (!editingId) { body.team_id = teamId; body.season = seasonEnd; }
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
    const message = editingId ? 'Запазено ✓' : 'Добавен ✓';
    resetForm();
    await load();
    flash(message);
  } catch (err) {
    flash('Няма връзка със сървъра. Опитай пак.', true);
  } finally {
    saveBtn.disabled = false;
  }
}

async function removeMatch(m) {
  const what = m.status === 'rest' ? `почивния кръг (Кръг ${m.round_no})` : `мача „${m.home} – ${m.away}“`;
  if (!confirm(`Да изтрия ли ${what}?`)) return;
  try {
    const { res, data } = await api(`${API}/${m.id}`, { method: 'DELETE' });
    if (!res.ok || !data.ok) throw new Error(data.error || 'delete');
    if (editingId === m.id) resetForm();
    await load();
    flash('Изтрит ✓');
  } catch (err) {
    flash('Неуспешно изтриване. Опитай пак.', true);
  }
}

// ------------------------------------------------------------ list ---
function matchCell(m) {
  const td = el('td', 'match-teams');
  if (m.status === 'rest') {
    td.append(el('em', 'rest-text', 'Почива — няма мач'));
  } else {
    const line = el('div');
    [m.home, m.away].forEach((name, i) => {
      if (i) line.append(document.createTextNode(' – '));
      const mine = (i === 0) === m.is_home;
      line.append(el(mine ? 'strong' : 'span', mine ? 'is-us' : '', name));
    });
    td.append(line);
  }
  if (m.note) td.append(el('div', 'match-note', m.note));
  return td;
}

function dateCell(m) {
  const td = el('td', 'match-when');
  td.append(el('div', 'match-date', m.date ? m.date_text : 'дата предстои'));
  if (m.status !== 'rest') td.append(el('div', 'match-time', m.time || 'час предстои'));
  return td;
}

function resultCell(m) {
  const td = el('td', 'match-result');
  if (m.score) {
    td.append(el('span', `score-badge ${m.outcome || ''}`, m.score));
  } else if (m.status === 'scheduled' && m.date && m.date < todayIso()) {
    td.append(el('span', 'pending-badge', 'чака резултат'));
  }
  if (m.status !== 'scheduled' && m.status !== 'played') {
    td.append(el('span', `match-status st-${m.status}`, m.status_label));
  }
  return td;
}

// Бърз резултат: два полета в реда „домакин : гост“, без да се отваря целият формуляр.
function openQuickResult(m, td) {
  td.textContent = '';
  const wrap = el('div', 'quick-score');
  const mkInput = (label, value) => {
    const input = document.createElement('input');
    input.type = 'number';
    input.min = '0';
    input.max = '99';
    input.inputMode = 'numeric';
    input.setAttribute('aria-label', label);
    input.title = label;
    input.value = value ?? '';
    return input;
  };
  const home = mkInput('Голове на домакина', m.is_home ? m.goals_for : m.goals_against);
  const away = mkInput('Голове на госта', m.is_home ? m.goals_against : m.goals_for);
  const ok = el('button', 'btn btn-primary btn-sm', '✓');
  ok.type = 'button';
  ok.title = 'Запази резултата';
  const no = el('button', 'btn btn-outline btn-sm', '✕');
  no.type = 'button';
  no.title = 'Отказ';
  const err = el('div', 'field-error');
  wrap.append(home, el('span', '', ':'), away, ok, no);
  td.append(wrap, err);
  home.focus();

  no.addEventListener('click', () => renderList());
  ok.addEventListener('click', async () => {
    if (home.value === '' || away.value === '') { err.textContent = 'Въведете двата резултата.'; return; }
    const homeGoals = Number(home.value);
    const awayGoals = Number(away.value);
    ok.disabled = true;
    const { res, data } = await api(`${API}/${m.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        status: 'played',
        goals_for: m.is_home ? homeGoals : awayGoals,
        goals_against: m.is_home ? awayGoals : homeGoals
      })
    });
    if (!res.ok || !data.ok) {
      ok.disabled = false;
      const errors = data.errors || {};
      err.textContent = errors.goals_for || errors.goals_against || errors.date || errors.status || data.error || 'Неуспешно запазване.';
      return;
    }
    await load();
    flash('Резултатът е запазен ✓');
  });
  [home, away].forEach(i => i.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') ok.click();
    if (e.key === 'Escape') no.click();
  }));
}

function actionsCell(m, resultTd) {
  const td = el('td');
  const row = el('div', 'row-actions');
  if (m.status !== 'rest' && m.status !== 'postponed' && m.status !== 'not_played') {
    const res = el('button', 'btn btn-primary btn-sm', m.score ? 'Промени резултата' : 'Резултат');
    res.type = 'button';
    res.addEventListener('click', () => openQuickResult(m, resultTd));
    row.append(res);
  }
  const edit = el('button', 'btn btn-outline btn-sm', 'Редактирай');
  edit.type = 'button';
  edit.addEventListener('click', () => startEdit(m));
  const del = el('button', 'btn btn-outline btn-sm btn-danger-text', 'Изтрий');
  del.type = 'button';
  del.addEventListener('click', () => removeMatch(m));
  row.append(edit, del);
  td.append(row);
  return td;
}

function renderList() {
  listEl.textContent = '';
  if (!teamId) {
    listEl.append(el('p', 'user-hint', 'Още няма отбори. Първо създайте отбор от „Отбори“.'));
    return;
  }
  if (!matches.length) {
    listEl.append(el('p', 'user-hint', 'Още няма мачове за този отбор и сезон. Добавете първия с формата отгоре.'));
    return;
  }
  const card = el('section', 'day-card match-card');
  const wrap = el('div', 'table-wrap');
  const table = el('table', 'admin-table match-table');
  const head = el('thead');
  const hr = el('tr');
  ['Кръг', 'Кога', 'Мач', 'Място', 'Резултат', ''].forEach(h => hr.append(el('th', '', h)));
  head.append(hr);
  const body = el('tbody');
  matches.forEach(m => {
    const tr = el('tr');
    if (m.status === 'rest') tr.className = 'is-rest';
    tr.append(el('td', 'match-round', m.round_no ? String(m.round_no) : '—'));
    tr.append(dateCell(m));
    tr.append(matchCell(m));
    tr.append(el('td', 'match-venue', m.venue || '—'));
    const resultTd = resultCell(m);
    tr.append(resultTd);
    tr.append(actionsCell(m, resultTd));
    body.append(tr);
  });
  table.append(head, body);
  wrap.append(table);
  card.append(wrap);
  listEl.append(card);
}

function renderPickers() {
  teamSelect.textContent = '';
  teams.filter(t => t.status === 'active').forEach(t => {
    const opt = el('option', '', teamText(t));
    opt.value = t.id;
    teamSelect.append(opt);
  });
  if (!teamId || !teams.some(t => t.id === teamId && t.status === 'active')) {
    const first = teams.find(t => t.status === 'active');
    teamId = first ? first.id : null;
  }
  if (teamId) teamSelect.value = teamId;

  seasonSelect.textContent = '';
  seasons.forEach(s => {
    const opt = el('option', '', s.end === currentSeason ? `${s.text} (текущ)` : s.text);
    opt.value = s.end;
    seasonSelect.append(opt);
  });
  seasonSelect.value = seasonEnd;

  const team = teams.find(t => t.id === teamId);
  publicLink.hidden = !team;
  if (team) publicLink.href = `/teams/${team.slug}`;
}

function renderStandings() {
  const team = teams.find(t => t.id === teamId);
  $('#standingsFor').textContent = team ? `${teamText(team)} (${seasons.find(x => x.end === seasonEnd)?.text || ''})` : 'избрания отбор';
  $('#f-standings').value = standingsUrl || '';
  $('#standingsForm').hidden = !team;
  const open = $('#standingsOpen');
  open.hidden = !standingsUrl;
  if (standingsUrl) open.href = standingsUrl;
}

async function saveStandings() {
  const btn = $('#standingsSave');
  const err = document.querySelector('#standingsForm [data-error-for="url"]');
  err.textContent = '';
  btn.disabled = true;
  try {
    const { res, data } = await api('/api/admin/standings-link', {
      method: 'PUT',
      body: JSON.stringify({ team_id: teamId, season: seasonEnd, url: $('#f-standings').value })
    });
    if (!res.ok || !data.ok) {
      err.textContent = (data.errors && data.errors.url) || data.error || 'Неуспешно запазване.';
      flash('Проверете връзката.', true);
      return;
    }
    standingsUrl = data.standings_url;
    renderStandings();
    flash(standingsUrl ? 'Връзката е запазена ✓' : 'Връзката е премахната ✓');
  } catch (e) {
    flash('Няма връзка със сървъра. Опитай пак.', true);
  } finally {
    btn.disabled = false;
  }
}

function renderSuggestions(s) {
  const fill = (id, items) => {
    const list = document.getElementById(id);
    list.textContent = '';
    items.forEach(v => { const o = document.createElement('option'); o.value = v; list.append(o); });
  };
  fill('opponentList', s.opponents || []);
  fill('venueList', s.venues || []);
}

async function load() {
  const requestedTeam = teamId;
  const params = new URLSearchParams();
  if (teamId) params.set('team', teamId);
  if (seasonEnd) params.set('season', seasonEnd);
  const { res, data } = await api(`${API}?${params}`);
  if (!res.ok || !data.ok) throw new Error('api');
  teams = data.teams;
  matches = data.matches;
  seasons = data.seasons;
  currentSeason = data.current_season;
  seasonEnd = data.season;
  renderPickers();
  renderSuggestions(data.suggestions);
  standingsUrl = data.standings_url || null;
  renderStandings();
  // Отборът от адреса липсва или е архивиран (или още няма избран): вземи мачовете на избрания.
  if (teamId && teamId !== requestedTeam) { await load(); return; }
  const url = new URL(location.href);
  url.searchParams.set('team', teamId || '');
  url.searchParams.set('season', seasonEnd);
  history.replaceState(null, '', url);
  if (!editingId) f.round.placeholder = String(nextRoundHint());
  renderList();
  statusEl.classList.remove('error', 'saved');
  statusEl.textContent = summary();
}

teamSelect.addEventListener('change', async () => {
  teamId = Number(teamSelect.value);
  resetForm();
  await load();
});
seasonSelect.addEventListener('change', async () => {
  seasonEnd = Number(seasonSelect.value);
  resetForm();
  await load();
});
f.status.addEventListener('change', syncFormMode);
saveBtn.addEventListener('click', save);
$('#standingsSave').addEventListener('click', saveStandings);
$('#standingsForm').addEventListener('submit', (e) => e.preventDefault());
cancelBtn.addEventListener('click', resetForm);
$('#matchForm').addEventListener('submit', (e) => e.preventDefault());

resetForm();
load().catch(() => {
  statusEl.classList.add('error');
  statusEl.textContent = 'Неуспешно зареждане. Провери дали backend-ът работи.';
});
