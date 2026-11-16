const form = document.querySelector('#pwForm');
const statusEl = document.querySelector('#pwStatus');
let mustFinish = false;

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = 'parent-status' + (kind ? ' ' + kind : '');
}

function clearErrors() {
  form.querySelectorAll('.parent-field-error').forEach(e => { e.textContent = ''; });
}

function showErrors(errors) {
  clearErrors();
  Object.entries(errors || {}).forEach(([field, msg]) => {
    const target = form.querySelector(`[data-error-for="${field}"]`);
    if (target) target.textContent = msg;
  });
}

(async function init() {
  const me = await Parent.requireLogin();
  document.querySelector('#who').textContent = me.parent.name;
  mustFinish = me.must_change_password || me.needs_consent;
  document.querySelector('#consentRow').hidden = !me.needs_consent;
  document.querySelector('#backRow').hidden = mustFinish;
  document.querySelector('#title').textContent = mustFinish ? 'Добре дошли!' : 'Смяна на парола';
  document.querySelector('#lead').textContent = mustFinish
    ? 'За да продължите към портала, изберете своя парола.'
    : 'Въведете текущата си парола и изберете нова.';
})();

document.querySelector('#logoutBtn').addEventListener('click', Parent.logout);

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  clearErrors();
  setStatus('');
  if (form.new.value !== form.repeat.value) {
    showErrors({ repeat: 'Паролите не съвпадат.' });
    return;
  }
  const btn = form.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    const { res, data } = await Parent.api('/api/parent/change-password', {
      method: 'POST',
      body: JSON.stringify({
        current_password: form.current.value,
        new_password: form.new.value,
        consent: form.consent.checked
      })
    });
    if (!res.ok || !data.ok) {
      if (data.errors) showErrors(data.errors); else setStatus(data.error || 'Неуспешна смяна.', 'error');
      return;
    }
    Parent.setCsrf(data.csrf);
    setStatus('Паролата е сменена ✓', 'success');
    setTimeout(() => location.replace('/parent-portal.html'), 700);
  } catch (err) {
    setStatus('Няма връзка със сървъра. Опитайте пак.', 'error');
  } finally {
    btn.disabled = false;
  }
});
