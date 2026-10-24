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

  document.addEventListener('DOMContentLoaded', async () => {
    const user = await ready;
    document.querySelectorAll('.admin-notice').forEach(el => el.remove());

    const nav = document.querySelector('.admin-nav');
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
