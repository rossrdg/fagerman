// Админ „Отбори“: смяна на сезона (само за главния администратор).
// Бутонът е скрит за треньорите — сървърът връща 403 и нищо не се показва.
(function () {
  if (new URLSearchParams(location.search).get('team')) return; // само в списъка с отбори

  const $ = (id) => document.getElementById(id);
  const btn = $('seasonBtn');
  const panel = $('seasonPanel');
  const undoBox = $('seasonUndo');
  if (!btn || !panel || !undoBox) return;

  const NOTES = {
    change: '',
    manual: 'ръчен етикет — не се променя',
    archive: 'преминава в MEN — отборът се архивира',
    men: 'без промяна'
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function api(url, options = {}) {
    const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
    const data = await res.json().catch(() => ({}));
    return { res, data };
  }

  function refreshLists() {
    $('refreshBtn').click();
    if (typeof window.refreshTeamsMenu === 'function') window.refreshTeamsMenu();
  }

  function showMessage(text, isError = false) {
    const status = $('listStatus');
    status.classList.toggle('error', isError);
    status.classList.toggle('saved', !isError);
    status.textContent = text;
    setTimeout(() => status.classList.remove('error', 'saved'), 5000);
  }

  // ---- Връщане към предишен сезон: избор от списък с всички сезони от историята
  function summarize(history, targetEnd) {
    // history е от най-новата към най-старата смяна; връщането към targetEnd отменя всички смени до него
    const undone = history.filter(h => h.from_end >= targetEnd);
    const restored = undone.flatMap(h => h.archived);
    const removed = undone.map(h => h.created).filter(Boolean);
    const lines = [`Ще се отменят ${undone.length} ${undone.length === 1 ? 'смяна' : 'смени'} на сезона.`];
    if (restored.length) lines.push(`Ще се възстановят архивираните отбори: ${restored.join(', ')}.`);
    if (removed.length) lines.push(`Автоматично създадените набори ще се премахнат (или скрият, ако вече имат данни): ${removed.join(', ')}.`);
    lines.push('Ръчните промени (описания, албуми, график) не се връщат.');
    return lines.join('\n');
  }

  function renderUndo(history, currentText) {
    undoBox.textContent = '';
    if (!history.length) { undoBox.hidden = true; return; }
    undoBox.hidden = false;

    const label = el('label', '', 'Върни към сезон: ');
    label.htmlFor = 'seasonRestoreSelect';
    const select = el('select');
    select.id = 'seasonRestoreSelect';
    // всички по-стари сезони, от най-новия към най-стария
    history.forEach(h => {
      const opt = el('option', '', h.from_text);
      opt.value = h.from_end;
      select.append(opt);
    });
    const go = el('button', 'btn btn-outline btn-sm', 'Върни');
    go.type = 'button';
    go.addEventListener('click', async () => {
      const target = Number(select.value);
      const chosen = history.find(h => h.from_end === target);
      if (!confirm(`Да върна ли сезона от ${currentText} към ${chosen.from_text}?\n\n${summarize(history, target)}`)) return;
      go.disabled = true;
      const { res, data } = await api('/api/admin/season/restore', {
        method: 'POST', body: JSON.stringify({ to_season_end_year: target })
      });
      if (!res.ok || !data.ok) {
        go.disabled = false;
        showMessage(data.error || 'Неуспешно връщане.', true);
        return;
      }
      panel.hidden = true;
      await init();
      refreshLists();
      showMessage(`Сезонът е върнат към ${data.season} ✓`);
    });
    undoBox.append(label, select, go);
  }

  // ---- Преглед и потвърждение
  function renderPreview(p) {
    panel.textContent = '';
    panel.append(el('h2', '', `Смяна на сезона: ${p.current_text} → ${p.next_text}`));
    panel.append(el('p', 'season-help',
      `U етикетът на всеки отбор расте с 1. Набор, който би надхвърлил U${p.max_u}, преминава в MEN и отборът му се архивира. ` +
      'Ръчно зададените етикети не се променят. Графикът, албумите, снимките и клиповете остават както са.'));

    const table = el('table', 'admin-table season-table');
    const head = el('thead');
    const hr = el('tr');
    ['Отбор', 'Набор', 'Сега', 'След смяната', 'Бележка'].forEach(t => hr.append(el('th', '', t)));
    head.append(hr);
    const body = el('tbody');
    p.rows.forEach(row => {
      const tr = el('tr', `season-row ${row.action}`);
      tr.append(el('td', '', row.kind === 'men' ? 'MEN' : row.old_label));
      tr.append(el('td', '', row.kind === 'men' ? '—' : row.cohort));
      tr.append(el('td', '', row.old_label));
      const after = row.action === 'change' || row.action === 'archive' ? row.new_label : row.old_label;
      tr.append(el('td', 'season-after', after));
      tr.append(el('td', 'season-note', NOTES[row.action] || ''));
      body.append(tr);
    });
    table.append(head, body);
    const wrap = el('div', 'table-wrap');
    wrap.append(table);
    panel.append(wrap);

    let cohortBox = null;
    if (p.new_cohort) {
      const label = el('label', 'check-item');
      cohortBox = document.createElement('input');
      cohortBox.type = 'checkbox';
      cohortBox.checked = true;
      label.append(cohortBox, el('span', '', `Създай отбор за набор ${p.new_cohort.year} (${p.new_cohort.label}) — най-малката група`));
      panel.append(label);
    }

    const archiving = p.rows.filter(r => r.action === 'archive').length;
    if (archiving) {
      panel.append(el('p', 'season-warn', `${archiving} ${archiving === 1 ? 'отбор ще бъде архивиран' : 'отбора ще бъдат архивирани'} (преминават в MEN). Може да се върнат от „Върни към сезон“.`));
    }

    const actions = el('div', 'form-actions');
    const confirmBtn = el('button', 'btn btn-primary', `Смени сезона на ${p.next_text}`);
    confirmBtn.type = 'button';
    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      const { res, data } = await api('/api/admin/season', {
        method: 'POST',
        body: JSON.stringify({ to_season_end_year: p.next_end, create_new_cohort: !!(cohortBox && cohortBox.checked) })
      });
      if (!res.ok || !data.ok) {
        confirmBtn.disabled = false;
        showMessage(data.error || 'Неуспешна смяна на сезона.', true);
        return;
      }
      panel.hidden = true;
      await init();
      refreshLists();
      showMessage(`Сезонът е сменен на ${data.season} ✓`);
    });
    const cancel = el('button', 'btn btn-outline', 'Отказ');
    cancel.type = 'button';
    cancel.addEventListener('click', () => { panel.hidden = true; });
    actions.append(confirmBtn, cancel);
    panel.append(actions);
  }

  btn.addEventListener('click', async () => {
    const { res, data } = await api('/api/admin/season');
    if (!res.ok || !data.ok) { showMessage(data.error || 'Прегледът не можа да се зареди.', true); return; }
    renderPreview(data);
    panel.hidden = false;
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  async function init() {
    const { res, data } = await api('/api/admin/season');
    if (!res.ok || !data.ok) { btn.hidden = true; undoBox.hidden = true; return; } // не е главен админ
    btn.hidden = false;
    btn.textContent = `Нов сезон ${data.next_text}…`;
    renderUndo(data.history || [], data.current_text);
  }

  init();
})();
