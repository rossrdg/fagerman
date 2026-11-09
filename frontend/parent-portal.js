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

  const links = el('div', 'child-links');
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

(async function init() {
  const me = await Parent.requireLogin();
  if (me.must_change_password || me.needs_consent) { location.replace('/parent-change-password.html'); return; }
  document.querySelector('#who').textContent = me.parent.name;

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
