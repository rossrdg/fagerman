const statusEl = document.querySelector('#adminStatus');
const table = document.querySelector('#registrationsTable');
const tbody = document.querySelector('#registrationsBody');
const refreshBtn = document.querySelector('#refreshBtn');

let registrations = [];
let statusTimer = null;

function formatCreatedAt(isoDateTime) {
  if (!isoDateTime) return '—';
  const date = new Date(isoDateTime + (isoDateTime.endsWith('Z') ? '' : 'Z'));
  if (isNaN(date.getTime())) return isoDateTime;
  return date.toLocaleString('bg-BG', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit'
  });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

function showTotal() {
  const done = registrations.filter(r => r.processed).length;
  statusEl.classList.remove('error', 'saved');
  statusEl.textContent = `Общо записвания: ${registrations.length} · Обработени: ${done}`;
}

function flashStatus(text, isError = false) {
  clearTimeout(statusTimer);
  statusEl.classList.toggle('error', isError);
  statusEl.classList.toggle('saved', !isError);
  statusEl.textContent = text;
  statusTimer = setTimeout(showTotal, isError ? 4000 : 1800);
}

function rowHtml(r) {
  return `
    <tr data-id="${r.id}" class="${r.processed ? 'is-processed' : ''}">
      <td>${r.id}</td>
      <td>${escapeHtml(r.child_name)}</td>
      <td>${r.child_age ?? '—'}</td>
      <td>${escapeHtml(r.parent_name)}</td>
      <td>${escapeHtml(r.phone)}</td>
      <td>${escapeHtml(r.email)}</td>
      <td>${formatCreatedAt(r.created_at)}</td>
      <td class="admin-edit"><input type="date" class="js-date" value="${r.training_date || ''}" aria-label="Ден на тренировката"></td>
      <td class="admin-edit"><input type="time" class="js-time" step="900" value="${r.training_time || ''}" aria-label="Час на тренировката"></td>
      <td class="check-cell"><input type="checkbox" class="js-processed" ${r.processed ? 'checked' : ''} aria-label="Записан"></td>
    </tr>`;
}

function renderRows() {
  if (registrations.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty-state">Все още няма подадени записвания.</td></tr>';
  } else {
    tbody.innerHTML = registrations.map(rowHtml).join('');
  }
}

async function loadRegistrations() {
  statusEl.textContent = 'Зареждане...';
  statusEl.classList.remove('error', 'saved');
  table.hidden = true;
  refreshBtn.disabled = true;

  try {
    const res = await fetch('/api/registration');
    const data = await res.json();

    if (!res.ok || !data.ok) {
      throw new Error('API returned an error');
    }

    registrations = data.registrations || [];
    renderRows();
    showTotal();
    table.hidden = false;
  } catch (err) {
    statusEl.classList.add('error');
    statusEl.textContent = 'Неуспешно зареждане на данните. Провери дали backend-ът работи.';
  } finally {
    refreshBtn.disabled = false;
  }
}

// Autosave: any change to the date / time / checkbox is sent right away.
tbody.addEventListener('change', async (e) => {
  const input = e.target.closest('input');
  const tr = e.target.closest('tr[data-id]');
  if (!input || !tr) return;

  const id = Number(tr.dataset.id);
  const record = registrations.find(r => r.id === id);
  if (!record) return;

  let payload;
  if (input.classList.contains('js-date')) payload = { training_date: input.value };
  else if (input.classList.contains('js-time')) payload = { training_time: input.value };
  else if (input.classList.contains('js-processed')) payload = { processed: input.checked };
  else return;

  const inputs = tr.querySelectorAll('input');
  inputs.forEach(i => (i.disabled = true));

  try {
    const res = await fetch(`/api/registration/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error('save failed');

    Object.assign(record, data.registration);
    tr.classList.toggle('is-processed', record.processed);
    flashStatus('Запазено ✓');
  } catch (err) {
    // Put the controls back to the last saved values.
    tr.querySelector('.js-date').value = record.training_date || '';
    tr.querySelector('.js-time').value = record.training_time || '';
    tr.querySelector('.js-processed').checked = !!record.processed;
    flashStatus('Неуспешно запазване. Опитай пак.', true);
  } finally {
    inputs.forEach(i => (i.disabled = false));
  }
});

refreshBtn.addEventListener('click', loadRegistrations);
loadRegistrations();
