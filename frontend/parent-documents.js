const childId = Number(new URLSearchParams(location.search).get('child'));
const box = document.querySelector('#docs');
const el = Parent.el;
let state = null;
const openCards = new Set(); // кои документи са „отворени“ — за да не се губи мястото при презареждане

function sizeText(bytes) {
  return bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function fileThumb(doc, file, index) {
  const wrap = el('div', 'doc-file-wrap');
  const a = el('a', 'doc-file');
  a.href = file.url; a.target = '_blank'; a.rel = 'noopener';
  if (file.mime === 'application/pdf') {
    a.append(el('span', 'doc-file-pdf', 'PDF'), el('small', '', sizeText(file.size)));
  } else {
    const img = el('img');
    img.src = file.url; img.alt = `Файл ${index + 1}`; img.loading = 'lazy';
    a.append(img);
  }
  wrap.append(a);
  if (doc.can_edit) {
    const remove = el('button', 'doc-file-remove', '×');
    remove.type = 'button';
    remove.setAttribute('aria-label', 'Махни файла');
    remove.addEventListener('click', async () => {
      if (!confirm('Да махна ли този файл?')) return;
      const { res, data } = await Parent.api(`/api/parent/documents/${doc.id}/files/${file.id}`, { method: 'DELETE' });
      if (!res.ok || !data.ok) { alert(data.error || 'Неуспешно махане.'); return; }
      await load();
    });
    wrap.append(remove);
  }
  return wrap;
}

async function uploadFiles(doc, files, progress, consent) {
  progress.textContent = '';
  let failed = 0;
  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    const line = el('div', '', `Качване ${i + 1} от ${files.length}…`);
    progress.append(line);
    const form = new FormData();
    form.append('file', file);
    if (consent) form.append('consent', '1');
    try {
      const { res, data } = await Parent.api(`/api/parent/documents/${doc.id}/files`, { method: 'POST', body: form });
      if (!res.ok || !data.ok) {
        failed++;
        line.className = 'err';
        line.textContent = (data.errors && data.errors.consent) || data.error || 'Файлът не можа да се качи.';
        if (res.status === 409) break; // пълно или заключено — другите също ще се откажат
        continue;
      }
      line.textContent = 'Качен ✓';
    } catch (err) {
      failed++;
      line.className = 'err';
      line.textContent = 'Няма връзка със сървъра.';
    }
  }
  openCards.add(doc.id);
  const keep = [...progress.querySelectorAll('.err')].map(n => n.textContent);
  await load();
  if (keep.length) {
    const fresh = document.querySelector(`[data-doc="${doc.id}"] .upload-progress`);
    if (fresh) keep.forEach(t => fresh.append(el('div', 'err', t)));
  }
}

function docCard(doc) {
  const card = el('section', 'parent-card doc-card');
  card.dataset.doc = doc.id;
  const head = el('div', 'doc-head');
  head.append(el('h2', '', doc.title), el('span', `doc-pill doc-${doc.status}`, doc.status_label));
  card.append(head);
  card.append(el('p', 'muted', doc.hint));

  if (doc.status === 'returned' && doc.comment) {
    const note = el('div', 'doc-note');
    note.append(el('strong', '', 'Треньорът помоли за поправка: '), document.createTextNode(doc.comment));
    card.append(note);
  }

  if (doc.has_template) {
    const tpl = el('a', 'btn btn-outline btn-sm', 'Изтегли бланката');
    tpl.href = `/api/parent/documents/${doc.id}/template`;
    card.append(tpl);
  }

  if (doc.files.length) {
    const files = el('div', 'doc-files');
    doc.files.forEach((f, i) => files.append(fileThumb(doc, f, i)));
    card.append(files);
  }

  if (doc.status === 'uploaded') card.append(el('p', 'doc-state', 'Изпратен — чака проверка от треньора.'));
  if (doc.status === 'approved') card.append(el('p', 'doc-state ok', 'Одобрен ✓'));

  if (doc.can_edit) {
    const controls = el('div', 'doc-controls');
    let consentBox = null;
    if (doc.needs_consent && !doc.consent_given) {
      const label = el('label', 'check');
      consentBox = document.createElement('input');
      consentBox.type = 'checkbox';
      label.append(consentBox, el('span', '', 'Съгласен/на съм снимката на детето да се използва за картотекирането.'));
      controls.append(label);
    }
    if (doc.files.length < doc.max_files) {
      const pick = el('label', 'btn btn-outline btn-sm upload-pick', doc.files.length ? 'Добави още файл' : 'Качи снимка или PDF');
      const input = document.createElement('input');
      input.type = 'file'; input.multiple = true; input.hidden = true;
      input.accept = 'image/*,.heic,.heif,.pdf,application/pdf';
      pick.append(input);
      const progress = el('div', 'upload-progress');
      input.addEventListener('change', () => {
        const list = [...input.files];
        input.value = '';
        if (!list.length) return;
        if (consentBox && !consentBox.checked) { progress.textContent = ''; progress.append(el('div', 'err', 'Първо отбележете съгласието за снимката.')); return; }
        uploadFiles(doc, list.slice(0, doc.max_files - doc.files.length), progress, !!(consentBox && consentBox.checked));
      });
      controls.append(pick, progress);
    }
    if (doc.files.length && doc.status !== 'uploaded') {
      const submit = el('button', 'btn btn-primary btn-sm', 'Изпрати за проверка');
      submit.type = 'button';
      submit.addEventListener('click', async () => {
        submit.disabled = true;
        const { res, data } = await Parent.api(`/api/parent/documents/${doc.id}/submit`, { method: 'POST' });
        if (!res.ok || !data.ok) { submit.disabled = false; alert(data.error || 'Неуспешно изпращане.'); return; }
        await load();
      });
      controls.append(submit);
    }
    card.append(controls);
  }
  return card;
}

function render() {
  document.querySelector('#title').textContent = state.child_name;
  document.querySelector('#subtitle').textContent = `Картотекиране за сезон ${state.season} · ${state.category_label}`;
  document.querySelector('#received').hidden = !state.card_received;
  const howto = document.querySelector('#howto');
  howto.hidden = state.card_received;
  const steps = document.querySelector('#steps');
  steps.textContent = '';
  state.instructions.forEach(t => steps.append(el('li', '', t)));
  box.textContent = '';
  if (state.card_received) return;
  state.documents.forEach(d => box.append(docCard(d)));
}

async function load() {
  const { res, data } = await Parent.api(`/api/parent/children/${childId}/documents`);
  if (res.status === 403 && data.code === 'password_change_required') { location.replace('/parent-change-password.html'); return; }
  if (!res.ok || !data.ok) {
    box.textContent = '';
    box.append(el('p', 'muted', res.status === 404 ? 'Профилът не е намерен.' : 'Данните не могат да се заредят в момента. Опитайте отново по-късно.'));
    return;
  }
  state = data;
  render();
}

(async function init() {
  const me = await Parent.requireLogin();
  if (me.must_change_password || me.needs_consent) { location.replace('/parent-change-password.html'); return; }
  document.querySelector('#who').textContent = me.parent.name;
  if (!childId) { box.textContent = ''; box.append(el('p', 'muted', 'Липсва профил.')); return; }
  await load();
})();

document.querySelector('#logoutBtn').addEventListener('click', Parent.logout);
