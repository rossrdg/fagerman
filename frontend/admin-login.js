const form = document.querySelector('#loginForm');
const statusEl = document.querySelector('#loginStatus');

// Already logged in? Go straight to the panel.
fetch('/api/auth/me', { credentials: 'same-origin' })
  .then(res => { if (res.ok) location.replace('/admin-registrations.html'); })
  .catch(() => {});

form.addEventListener('submit', async e => {
  e.preventDefault();
  statusEl.textContent = '';
  const btn = form.querySelector('button');
  btn.disabled = true;
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: form.username.value,
        password: form.password.value
      })
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      location.replace('/admin-registrations.html');
      return;
    }
    statusEl.textContent = data.error || 'Неуспешен вход.';
    form.password.value = '';
    form.password.focus();
  } catch (err) {
    statusEl.textContent = 'Няма връзка със сървъра.';
  } finally {
    btn.disabled = false;
  }
});
