const box = document.querySelector('#children');
const el = Parent.el;

function fmtDate(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return `${d}.${m}.${y}`;
}

function childCard(c) {
  const card = el('section', 'parent-card child-card');
  card.setAttribute('aria-label', c.child_name);
  card.append(el('h2', '', c.child_name));
  const meta = el('div', 'child-meta');
  const add = (label, value) => {
    if (!value) return;
    const item = el('span');
    item.append(el('span', 'muted', label + ' '), el('strong', '', value));
    meta.append(item);
  };
  add('Отбор:', c.team_label || 'ще бъде определен');
  add('Набор:', c.team_cohort);
  add('Статус:', c.status_label);
  add('От:', fmtDate(c.start_date));
  card.append(meta);

  if (c.docs) {
    const d = c.docs;
    const line = el('p', 'child-docs');
    if (d.card_received) line.append(el('strong', '', 'Картотеката е получена ✓'));
    else {
      line.append(el('span', 'muted', 'Документи за картотекиране: '), el('strong', '', `${d.done} от ${d.total} готови`));
      if (d.returned) line.append(el('span', 'doc-pill doc-returned', 'има върнат документ'));
    }
    card.append(line);
  }

  const links = el('div', 'child-links');
  const docs = el('a', 'btn btn-primary btn-sm', 'Картотекиране и документи');
  docs.href = `/parent-documents.html?child=${c.id}`;
  links.append(docs);
  const schedule = el('a', 'btn btn-outline btn-sm', 'Тренировъчен график');
  schedule.href = '/schedule';
  links.append(schedule);
  if (c.team_url) {
    const team = el('a', 'btn btn-outline btn-sm', 'Страница на отбора');
    team.href = c.team_url;
    links.append(team);
  }
  card.append(links);
  return card;
}

function messageCards(data) {
  const box = document.querySelector('#messages');
  box.textContent = '';
  if (!data.reminders.length && !(data.announcements || []).length) {
    const card = el('section', 'parent-card parent-soon');
    card.append(el('h2', '', 'Съобщения'), el('p', 'muted', 'Засега няма нови съобщения.'));
    box.append(card);
    return;
  }
  data.reminders.forEach(r => {
    const card = el('section', 'parent-card message-card');
    if (r.type === 'fees') {
      card.append(el('h2', '', `Такси за ${r.child_name}`));
      const list = el('ul', 'fee-list');
      r.items.forEach(i => { const li = el('li'); li.append(el('span', '', i.label), el('strong', '', i.amount_text)); list.append(li); });
      card.append(list);
      const total = el('p', 'fee-total'); total.append(el('span', 'muted', 'Общо: '), el('strong', '', r.total_text));
      card.append(total, el('p', 'muted', r.text));
      if (data.pay_info) { card.append(el('h3', 'pay-title', 'Как се плаща'), el('p', 'pay-info', data.pay_info)); }
    } else {
      card.append(el('h2', '', 'Документи'), el('p', '', r.text));
      const a = el('a', 'btn btn-outline btn-sm', 'Към документите'); a.href = `/parent-documents.html?child=${r.child_id}`; card.append(a);
    }
    box.append(card);
  });
  (data.announcements || []).forEach(a => {
    const card = el('section', 'parent-card announcement-card');
    card.append(el('h2', '', a.title));
    const meta = [a.date_text];
    if (a.for_children.length) meta.push(`за ${a.for_children.join(', ')}`);
    card.append(el('p', 'announcement-meta', meta.join(' · ')));
    card.append(el('p', 'announcement-body', a.body)); // textContent: HTML не се интерпретира
    box.append(card);
  });
}

(async function init() {
  const me = await Parent.requireLogin();
  if (me.must_change_password || me.needs_consent) { location.replace('/parent-change-password.html'); return; }
  document.querySelector('#who').textContent = me.parent.name;

  Parent.api('/api/parent/messages').then(({ res, data }) => { if (res.ok && data.ok) messageCards(data); }).catch(() => {});
  const { res, data } = await Parent.api('/api/parent/children');
  if (res.status === 403 && data.code === 'password_change_required') { location.replace('/parent-change-password.html'); return; }
  box.textContent = '';
  if (!res.ok || !data.ok) { box.append(el('p', 'muted', 'Данните не могат да се заредят в момента. Опитайте отново по-късно.')); return; }
  if (!data.children.length) {
    const card = el('section', 'parent-card');
    card.append(el('h2', '', 'Няма активни профили'), el('p', 'muted', 'В момента няма активен профил на дете към този акаунт. Ако смятате, че е грешка, свържете се с академията.'));
    box.append(card);
    return;
  }
  data.children.forEach(c => box.append(childCard(c)));
})();

document.querySelector('#logoutBtn').addEventListener('click', Parent.logout);
