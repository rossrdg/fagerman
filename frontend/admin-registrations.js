const statusEl = document.querySelector('#adminStatus');
const table = document.querySelector('#registrationsTable');
const tbody = document.querySelector('#registrationsBody');
const refreshBtn = document.querySelector('#refreshBtn');

function formatDate(isoDate) {
  if (!isoDate) return '—';
  const [y, m, d] = isoDate.split('-');
  return `${d}.${m}.${y}`;
}

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

async function loadRegistrations() {
  statusEl.textContent = 'Зареждане...';
  statusEl.classList.remove('error');
  table.hidden = true;
  refreshBtn.disabled = true;

  try {
    const res = await fetch('/api/registration');
    const data = await res.json();

    if (!res.ok || !data.ok) {
      throw new Error('API returned an error');
    }

    const registrations = data.registrations || [];

    if (registrations.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty-state">Все още няма подадени записвания.</td></tr>';
    } else {
      tbody.innerHTML = registrations.map(r => `
        <tr>
          <td>${r.id}</td>
          <td>${escapeHtml(r.child_name)}</td>
          <td>${r.child_age ?? '—'}</td>
          <td>${escapeHtml(r.parent_name)}</td>
          <td>${escapeHtml(r.phone)}</td>
          <td>${escapeHtml(r.email)}</td>
          <td>${formatCreatedAt(r.created_at)}</td>
        </tr>
      `).join('');
    }

    statusEl.textContent = `Общо записвания: ${registrations.length}`;
    table.hidden = false;
  } catch (err) {
    statusEl.classList.add('error');
    statusEl.textContent = 'Неуспешно зареждане на данните. Провери дали backend-ът работи.';
  } finally {
    refreshBtn.disabled = false;
  }
}

refreshBtn.addEventListener('click', loadRegistrations);
loadRegistrations();
