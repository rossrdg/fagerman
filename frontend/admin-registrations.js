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

function formatDay(isoDate) {
  if (!isoDate) return '—';
  const [y, m, d] = isoDate.split('-');
  return `${d}.${m}.${y}`;
}

function notifiedBadge(r) {
  if (!r.notified_at) return '';
  return `<span class="notified-badge" title="Родителят е уведомен на ${escapeHtml(formatCreatedAt(r.notified_at))}">✉ Уведомен</span>`;
}

function rowHtml(r) {
  const age = r.child_age != null ? `${r.child_age} г.` : '—';
  return `
    <tr data-id="${r.id}" class="${r.processed ? 'is-processed' : ''}">
      <td class="col-id" data-label="№">${r.id}</td>
      <td data-label="Дете"><span class="reg-name">${escapeHtml(r.child_name)}</span><span class="reg-sub">${age}</span></td>
      <td data-label="Родител и контакти">
        <span class="reg-parent">${escapeHtml(r.parent_name)}</span>
        <span class="reg-line">${escapeHtml(r.phone)}</span>
        <span class="reg-line reg-email">${escapeHtml(r.email)}</span>
      </td>
      <td class="reg-created" data-label="Подадено на">${formatCreatedAt(r.created_at)}</td>
      <td class="admin-edit reg-when" data-label="Тренировка (ден и час)">
        <div class="reg-when-inner">
          <input type="date" class="js-date" value="${r.training_date || ''}" aria-label="Ден на тренировката">
          <input type="time" class="js-time" step="900" value="${r.training_time || ''}" aria-label="Час на тренировката">
        </div>
      </td>
      <td class="check-cell" data-label="Записан"><input type="checkbox" class="js-processed" ${r.processed ? 'checked' : ''} aria-label="Записан">${notifiedBadge(r)}</td>
    </tr>`;
}

function renderRows() {
  if (registrations.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Все още няма подадени записвания.</td></tr>';
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

    if (input.classList.contains('js-processed') && record.processed) {
      if (record.training_date && record.training_time) {
        openNotifyModal(record);
      } else {
        flashStatus('Отбелязан е, но без ден и час родителят не може да бъде уведомен.', true);
      }
    }
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

// ---- "Notify parent?" modal ----
const notifyModal = document.querySelector('#notifyModal');
const notifyText = document.querySelector('#notifyText');
const notifyWarn = document.querySelector('#notifyWarn');
const notifyError = document.querySelector('#notifyError');
const notifyYes = document.querySelector('#notifyYes');
const notifyNo = document.querySelector('#notifyNo');
let notifyTarget = null;

function openNotifyModal(record) {
  notifyTarget = record;
  notifyText.textContent =
    `Да изпратя ли имейл до ${record.parent_name} (${record.email}), че ${record.child_name} ` +
    `е записан за пробна тренировка на ${formatDay(record.training_date)} от ${record.training_time} ч.?`;

  notifyWarn.hidden = !record.notified_at;
  if (record.notified_at) {
    notifyWarn.textContent = `Вече е изпратен имейл на ${formatCreatedAt(record.notified_at)}. Ще се изпрати нов.`;
  }
  notifyError.hidden = true;
  notifyYes.disabled = false;
  notifyNo.disabled = false;
  notifyModal.classList.add('open');
  notifyModal.setAttribute('aria-hidden', 'false');
  notifyYes.focus();
}

function closeNotifyModal() {
  notifyModal.classList.remove('open');
  notifyModal.setAttribute('aria-hidden', 'true');
  notifyTarget = null;
}

notifyYes.addEventListener('click', async () => {
  const record = notifyTarget;
  if (!record) return;

  notifyYes.disabled = true;
  notifyNo.disabled = true;
  notifyYes.textContent = 'Изпращане...';
  notifyError.hidden = true;

  try {
    const res = await fetch(`/api/registration/${record.id}/notify`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      throw new Error(data.error || 'Грешка при изпращане.');
    }

    Object.assign(record, data.registration);
    const tr = tbody.querySelector(`tr[data-id="${record.id}"]`);
    if (tr) tr.querySelector('.check-cell').innerHTML =
      `<input type="checkbox" class="js-processed" checked aria-label="Записан">${notifiedBadge(record)}`;

    closeNotifyModal();
    flashStatus(data.sent
      ? 'Имейлът е изпратен ✓'
      : 'Тестов режим: имейлът не е изпратен реално (няма настроен MAIL_SERVER).');
  } catch (err) {
    notifyError.textContent = err.message;
    notifyError.hidden = false;
    notifyYes.disabled = false;
    notifyNo.disabled = false;
  } finally {
    notifyYes.textContent = 'Да, изпрати имейл';
  }
});

notifyNo.addEventListener('click', closeNotifyModal);
notifyModal.querySelector('.modal-close').addEventListener('click', closeNotifyModal);
notifyModal.querySelector('.modal-backdrop').addEventListener('click', closeNotifyModal);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && notifyModal.classList.contains('open')) closeNotifyModal(); });

refreshBtn.addEventListener('click', loadRegistrations);
loadRegistrations();
