const form = document.querySelector('#loginForm');
const statusEl = document.querySelector('#loginStatus');

function goNext(me) {
  location.replace(me.must_change_password || me.needs_consent ? '/parent-change-password.html' : '/parent-portal.html');
}

// Вече влязъл? Направо към портала.
Parent.api('/api/parent/me').then(({ res, data }) => { if (res.ok && data.ok) goNext(data); }).catch(() => {});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  statusEl.textContent = '';
  const btn = form.querySelector('button');
  btn.disabled = true;
  try {
    const { res, data } = await Parent.api('/api/parent/login', {
      method: 'POST',
      body: JSON.stringify({ email: form.email.value, password: form.password.value })
    });
    if (res.ok && data.ok) { goNext(data); return; }
    statusEl.textContent = data.error || 'Неуспешен вход.';
    form.password.value = '';
    form.password.focus();
  } catch (err) {
    statusEl.textContent = 'Няма връзка със сървъра. Опитайте пак.';
  } finally {
    btn.disabled = false;
  }
});
