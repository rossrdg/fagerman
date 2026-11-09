// Общи неща за родителските страници: заявки с CSRF токен и проверка кой е влязъл.
(function () {
  let csrf = '';

  async function api(url, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (csrf) headers['X-CSRF-Token'] = csrf;
    const res = await fetch(url, { credentials: 'same-origin', ...options, headers });
    const data = await res.json().catch(() => ({}));
    return { res, data };
  }

  // Връща данните от /api/parent/me или пренасочва към входа.
  async function requireLogin() {
    const { res, data } = await api('/api/parent/me');
    if (!res.ok || !data.ok) { location.replace('/parent-login.html'); return new Promise(() => {}); }
    csrf = data.csrf;
    return data;
  }

  function setCsrf(token) { csrf = token || ''; }

  async function logout() {
    await api('/api/parent/logout', { method: 'POST' });
    location.replace('/parent-login.html');
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  window.Parent = { api, requireLogin, setCsrf, logout, el };
})();
