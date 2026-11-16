// Админ: документите за картотекиране на едно дете (преглед, одобряване, връщане, „картотека получена“).
const playerId = Number(new URLSearchParams(location.search).get('id'));
const $ = (sel) => document.querySelector(sel);
const statusEl = $('#status');
let data = null;
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
    statusEl.textContent = summaryText();
  }, isError ? 6000 : 2500);
}

function summaryText() {
  if (!data) return '';
  const s = data.summary;
  return `Сезон ${data.season} · ${data.category_label} · одобрени ${s.done} от ${s.total}` +
    (s.pending ? ` · за проверка: ${s.pending}` : '') + (s.returned ? ` · върнати: ${s.returned}` : '');
}

async function api(url, options = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
  const out = await res.json().catch(() => ({}));
  return { res, out };
}

function sizeText(bytes) {
  return bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function fileView(file, index) {
  const a = el('a', 'doc-file');
  a.href = file.url; a.target = '_blank'; a.rel = 'noopener';
  if (file.mime === 'application/pdf') {
    a.append(el('span', 'doc-file-pdf', 'PDF'), el('small', '', `${sizeText(file.size)}`));
  } else {
    const img = el('img');
    img.src = file.url; img.alt = `Файл ${index + 1}`; img.loading = 'lazy';
    a.append(img);
  }
  return a;
}

function renderCardBox() {
  const box = $('#cardBox');
  box.hidden = false;
  box.textContent = '';
  box.append(el('h2', '', data.card_received ? 'Картотеката е получена ✓' : 'Картотека'));
  if (data.card_received) {
    box.append(el('p', 'user-hint', 'Качените файлове са изтрити. Комплектът е архивиран за този сезон.'));
    const undo = el('button', 'btn btn-outline btn-sm', 'Върни комплекта');
    undo.type = 'button';
    undo.addEventListener('click', async () => {
      if (!confirm('Да върна ли комплекта? Файловете не се възстановяват — документите ще чакат отново.')) return;
      await cardReceived(false);
    });
    box.append(undo);
  } else {
    box.append(el('p', 'user-hint', 'Когато детето получи официалната картотека, отбележете го. Качените от родителя файлове ще бъдат изтрити.'));
    const done = el('button', 'btn btn-primary btn-sm', 'Картотеката е получена');
    done.type = 'button';
    done.addEventListener('click', async () => {
      if (!confirm('Да отбележа ли картотеката като получена?\n\nВсички качени файлове (снимки, лични карти, медицинско) ще бъдат ИЗТРИТИ и не могат да се върнат.')) return;
      await cardReceived(true);
    });
    box.append(done);
  }
}

async function cardReceived(received) {
  const { res, out } = await api(`/api/admin/players/${playerId}/card-received`, { method: 'POST', body: JSON.stringify({ received }) });
  if (!res.ok || !out.ok) { flash(out.error || 'Неуспешно.', true); return; }
  setData(out);
  flash(received ? 'Картотеката е отбелязана като получена ✓' : 'Комплектът е върнат ✓');
}

function docCard(doc) {
  const card = el('section', 'day-card doc-admin');
  const head = el('div', 'doc-head');
  head.append(el('h2', '', doc.title), el('span', `doc-pill doc-${doc.status}`, doc.status_label));
  card.append(head);

  if (doc.comment) card.append(el('p', 'doc-comment', `Коментар към родителя: ${doc.comment}`));
  if (doc.needs_consent) {
    card.append(el('p', 'user-hint', doc.consent_given ? 'Родителят е потвърдил съгласие за снимката.' : 'Още няма съгласие за снимката.'));
  }

  const files = el('div', 'doc-files');
  if (doc.files.length) doc.files.forEach((f, i) => files.append(fileView(f, i)));
  else files.append(el('p', 'user-hint', 'Още няма качени файлове.'));
  card.append(files);

  if (doc.reviewed_by) card.append(el('p', 'user-hint', `Последна проверка: ${doc.reviewed_by}`));

  const actions = el('div', 'row-actions doc-actions');
  const act = (text, cls, fn) => {
    const b = el('button', `btn ${cls} btn-sm`, text);
    b.type = 'button';
    b.addEventListener('click', fn);
    actions.append(b);
  };
  if (doc.status === 'uploaded') act('Одобри', 'btn-primary', () => review(doc, 'approve'));
  if (doc.status === 'uploaded' || doc.status === 'approved') act('Върни за поправка', 'btn-outline', () => openReturn(card, doc));
  if (!data.card_received) act('Махни от комплекта', 'btn-outline btn-danger-text', () => removeDoc(doc));
  card.append(actions);
  return card;
}

function openReturn(card, doc) {
  if (card.querySelector('.return-box')) return;
  const box = el('div', 'return-box');
  const area = el('textarea');
  area.rows = 2; area.maxLength = 500; area.placeholder = 'Какво трябва да се поправи? (родителят ще го види)';
  const err = el('div', 'field-error');
  const send = el('button', 'btn btn-primary btn-sm', 'Върни');
  send.type = 'button';
  const cancel = el('button', 'btn btn-outline btn-sm', 'Отказ');
  cancel.type = 'button';
  cancel.addEventListener('click', () => box.remove());
  send.addEventListener('click', async () => {
    send.disabled = true;
    const { res, out } = await api(`/api/admin/documents/${doc.id}/return`, { method: 'POST', body: JSON.stringify({ comment: area.value }) });
    if (!res.ok || !out.ok) { send.disabled = false; err.textContent = (out.errors && out.errors.comment) || out.error || 'Неуспешно.'; return; }
    setData(out);
    flash('Документът е върнат ✓');
  });
  const row = el('div', 'row-actions');
  row.append(send, cancel);
  box.append(area, err, row);
  card.append(box);
  area.focus();
}

async function review(doc, action) {
  const { res, out } = await api(`/api/admin/documents/${doc.id}/${action}`, { method: 'POST' });
  if (!res.ok || !out.ok) { flash(out.error || 'Неуспешно.', true); return; }
  setData(out);
  flash('Одобрен ✓');
}

async function removeDoc(doc) {
  const extra = doc.files.length ? ' Качените файлове ще бъдат изтрити.' : '';
  if (!confirm(`Да махна ли „${doc.title}“ от комплекта?${extra}`)) return;
  const { res, out } = await api(`/api/admin/documents/${doc.id}`, { method: 'DELETE' });
  if (!res.ok || !out.ok) { flash(out.error || 'Неуспешно.', true); return; }
  setData(out);
  flash('Документът е махнат ✓');
}

function renderAdd() {
  const box = $('#addBox');
  const available = data.available_types || [];
  box.hidden = data.card_received || !available.length;
  const select = $('#addType');
  select.textContent = '';
  available.forEach(t => { const o = el('option', '', t.title); o.value = t.code; select.append(o); });
}

function setData(next) {
  data = next;
  $('#title').textContent = `Документи: ${data.child_name}`;
  document.title = `Документи — ${data.child_name} — Админ — ФА Герман`;
  renderCardBox();
  const list = $('#docList');
  list.textContent = '';
  data.documents.forEach(d => list.append(docCard(d)));
  renderAdd();
  statusEl.classList.remove('error', 'saved');
  statusEl.textContent = summaryText();
  if (typeof window.refreshDocsBadge === 'function') window.refreshDocsBadge();
}

$('#addBtn').addEventListener('click', async () => {
  const code = $('#addType').value;
  if (!code) return;
  const { res, out } = await api(`/api/admin/players/${playerId}/documents`, { method: 'POST', body: JSON.stringify({ doc_type: code }) });
  if (!res.ok || !out.ok) { flash(out.error || 'Неуспешно.', true); return; }
  setData(out);
  flash('Документът е добавен ✓');
});

(async function init() {
  if (!playerId) { statusEl.textContent = 'Липсва профил.'; return; }
  try {
    const { res, out } = await api(`/api/admin/players/${playerId}/documents`);
    if (res.status === 403) { statusEl.classList.add('error'); statusEl.textContent = 'Нямате права да виждате документите.'; return; }
    if (!res.ok || !out.ok) throw new Error('api');
    setData(out);
  } catch (err) {
    statusEl.classList.add('error');
    statusEl.textContent = 'Неуспешно зареждане. Провери дали backend-ът работи.';
  }
})();
