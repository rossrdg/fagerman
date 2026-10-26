// Shared by every admin page (load it first, in <head>, without defer).
// - asks the server who is logged in; no session -> redirect to the login page
// - adds the CSRF token to every non-GET /api/ request of the page scripts
// - adds the user name + "Изход" to the header and, for the owner, the
//   "Потребители" item to the menu
(function () {
  const nativeFetch = window.fetch.bind(window);
  let csrf = '';

  function toLogin() {
    location.replace('/admin-login.html');
  }

  const ready = nativeFetch('/api/auth/me', { credentials: 'same-origin' })
    .then(res => (res.ok ? res.json() : Promise.reject(res.status)))
    .then(data => {
      csrf = data.csrf;
      window.adminUser = data.user;
      return data.user;
    })
    .catch(() => { toLogin(); return new Promise(() => {}); }); // stop the page

  window.fetch = async function (input, init = {}) {
    await ready;
    const url = typeof input === 'string' ? input : input.url;
    const isApi = url.startsWith('/api/') || url.startsWith(location.origin + '/api/');
    if (isApi) {
      const headers = new Headers(init.headers || {});
      headers.set('X-CSRF-Token', csrf);
      init = { ...init, headers, credentials: 'same-origin' };
    }
    const res = await nativeFetch(input, init);
    if (isApi && res.status === 401) toLogin();
    return res;
  };

  // Падащо меню „Отбори“: връзка към управлението + всички активни отбори.
  // Изборът на отбор отваря панела му (admin-teams.html?team=<id>).
  function buildTeamsMenu(nav) {
    const wrap = document.createElement('div');
    wrap.className = 'nav-dropdown';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'nav-dropdown-btn';
    btn.textContent = 'Отбори ▾';
    btn.setAttribute('aria-haspopup', 'true');
    btn.setAttribute('aria-expanded', 'false');
    if (location.pathname.endsWith('admin-teams.html')) btn.classList.add('active');
    const menu = document.createElement('div');
    menu.className = 'nav-menu';
    menu.hidden = true;
    wrap.append(btn, menu);
    nav.appendChild(wrap);

    const currentId = new URLSearchParams(location.search).get('team');

    function link(href, text, isCurrent) {
      const a = document.createElement('a');
      a.href = href;
      a.textContent = text;
      if (isCurrent) a.classList.add('current');
      return a;
    }

    function render(teams) {
      menu.textContent = '';
      menu.append(link('admin-teams.html', 'Всички отбори (управление)', location.pathname.endsWith('admin-teams.html') && !currentId));
      menu.append(document.createElement('hr'));
      if (!teams.length) {
        const empty = document.createElement('div');
        empty.className = 'nav-empty';
        empty.textContent = 'Още няма активни отбори.';
        menu.append(empty);
      }
      teams.forEach(t => {
        const text = t.kind === 'men' ? 'MEN' : t.u_label + ' · набор ' + t.cohort;
        menu.append(link('admin-teams.html?team=' + t.id, text, String(t.id) === currentId));
      });
    }

    async function load() {
      try {
        const res = await window.fetch('/api/admin/teams');
        const data = await res.json();
        render((data.teams || []).filter(t => t.status === 'active'));
      } catch (err) {
        render([]);
      }
    }
    window.refreshTeamsMenu = load; // викат го страниците, след като сменят отбор

    function close() {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
    }
    btn.addEventListener('click', () => {
      if (!menu.hidden) { close(); return; }
      const r = btn.getBoundingClientRect();
      menu.hidden = false;
      menu.style.top = r.bottom + 'px';
      menu.style.left = Math.max(8, Math.min(r.left, window.innerWidth - menu.offsetWidth - 8)) + 'px';
      btn.setAttribute('aria-expanded', 'true');
    });
    document.addEventListener('click', (e) => { if (!wrap.contains(e.target)) close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
    window.addEventListener('resize', close);
    nav.addEventListener('scroll', close, { passive: true });

    render([]);
    load();
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const user = await ready;
    document.querySelectorAll('.admin-notice').forEach(el => el.remove());

    const nav = document.querySelector('.admin-nav');
    if (nav) buildTeamsMenu(nav);
    if (nav && user.role === 'owner') {
      const a = document.createElement('a');
      a.href = 'admin-users.html';
      a.textContent = 'Потребители';
      if (location.pathname.endsWith('admin-users.html')) a.classList.add('active');
      nav.appendChild(a);
    }

    const header = document.querySelector('.admin-header');
    if (header) {
      const box = document.createElement('div');
      box.className = 'admin-user';
      const label = document.createElement('span');
      label.textContent = user.display_name + (user.role === 'owner' ? ' · главен админ' : ' · треньор');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-ghost';
      btn.textContent = 'Изход';
      btn.addEventListener('click', async () => {
        await window.fetch('/api/auth/logout', { method: 'POST' });
        toLogin();
      });
      box.append(label, btn);
      header.appendChild(box);
    }
  });
})();
