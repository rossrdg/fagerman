// Форма за попълване на бланките на БФС. ВАЖНО: въведените данни (ЕГН, лична карта, акт за раждане) се
// изпращат само в заявката за генериране и не се пазят — нито тук (без localStorage/sessionStorage/cookies/URL),
// нито на сървъра. Формата не губи въведеното, докато страницата е отворена.
const childId = Number(new URLSearchParams(location.search).get('child'));
const el = Parent.el;
const fieldsBox = document.querySelector('#fields');
const form = document.querySelector('#docForm');
const statusEl = document.querySelector('#formStatus');
let spec = null;
const inputs = {};

// Официална транслитерация (Закон за транслитерацията, „опростената система“). Изписването на латиница
// се предлага автоматично, но може да се поправи ръчно.
const TRANSLIT = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ж: 'zh', з: 'z', и: 'i', й: 'y', к: 'k', л: 'l', м: 'm', н: 'n',
  о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f', х: 'h', ц: 'ts', ч: 'ch', ш: 'sh', щ: 'sht', ъ: 'a',
  ь: 'y', ю: 'yu', я: 'ya'
};
function translit(text) {
  return [...text].map(ch => {
    const lower = ch.toLowerCase();
    const out = TRANSLIT[lower];
    if (out === undefined) return ch;
    return ch === lower ? out : out.charAt(0).toUpperCase() + out.slice(1);
  }).join('');
}

const LATIN_SOURCE = { child_lat: 'child_bg', player_lat: 'player_bg' };

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = 'parent-status' + (kind ? ' ' + kind : '');
}

function clearErrors() {
  form.querySelectorAll('.parent-field-error').forEach(e => { e.textContent = ''; });
}

function showErrors(errors) {
  clearErrors();
  let first = null;
  Object.entries(errors || {}).forEach(([key, msg]) => {
    const target = form.querySelector(`[data-error-for="${key}"]`);
    if (target) { target.textContent = msg; first = first || inputs[key]; }
  });
  if (first) first.focus();
}

function buildField(f) {
  const label = el('label', 'field-label');
  label.append(document.createTextNode(f.label + (f.required ? ' *' : '')));
  const input = document.createElement('input');
  input.name = f.key;
  input.autocomplete = 'off';
  input.autocapitalize = 'off';
  input.spellcheck = false;
  if (f.kind === 'egn') {
    input.inputMode = 'numeric'; input.maxLength = 10; input.placeholder = '10 цифри';
    input.addEventListener('input', () => { input.value = input.value.replace(/\D/g, ''); }); // само цифри
  }
  else if (f.kind === 'date') { input.type = 'date'; }
  else { input.type = 'text'; input.maxLength = 120; }
  if (spec.prefill[f.key]) input.value = spec.prefill[f.key];
  label.append(input);
  if (f.hint) label.append(el('span', 'field-hint', f.hint));
  const err = el('div', 'parent-field-error');
  err.dataset.errorFor = f.key;
  label.append(err);
  inputs[f.key] = input;
  return label;
}

function build() {
  document.querySelector('#subtitle').textContent =
    `${spec.child_name} · сезон ${spec.season} · ${spec.category_label}`;
  document.querySelector('#backLink').href = `/parent-documents.html?child=${childId}`;
  fieldsBox.textContent = '';
  spec.groups.forEach(group => {
    const fs = el('fieldset', 'forms-group');
    fs.append(el('legend', '', group.title));
    group.fields.forEach(f => fs.append(buildField(f)));
    fieldsBox.append(fs);
  });
  // Латиница: предлага се от кирилицата, докато родителят не я поправи ръчно.
  Object.entries(LATIN_SOURCE).forEach(([latinKey, bgKey]) => {
    const latin = inputs[latinKey];
    const bg = inputs[bgKey];
    if (!latin || !bg) return;
    let touched = false;
    latin.value = translit(bg.value);
    latin.addEventListener('input', () => { touched = latin.value !== translit(bg.value); });
    bg.addEventListener('input', () => { if (!touched) latin.value = translit(bg.value); });
  });
}

function collect() {
  const values = {};
  Object.entries(inputs).forEach(([key, input]) => { values[key] = input.value; });
  return values;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  clearErrors();
  setStatus('');
  const btn = document.querySelector('#genBtn');
  btn.disabled = true;
  setStatus('Подготвя се документът…');
  try {
    const res = await fetch(`/api/parent/children/${childId}/forms/generate`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': Parent.getCsrf() },
      body: JSON.stringify({ values: collect() })
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      if (data.errors) { showErrors(data.errors); setStatus('Проверете маркираните полета.', 'error'); }
      else setStatus(data.error || 'Документът не можа да се генерира. Опитайте отново.', 'error');
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'kartotekirane.pdf';
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    setStatus('Документът е свален ✓ Данните не са запазени. Ако имате нужда от нов, натиснете бутона отново.', 'success');
  } catch (err) {
    setStatus('Няма връзка със сървъра. Данните са запазени във формата — опитайте пак.', 'error');
  } finally {
    btn.disabled = false;
  }
});

document.querySelector('#logoutBtn').addEventListener('click', Parent.logout);

(async function init() {
  const me = await Parent.requireLogin();
  if (me.must_change_password || me.needs_consent) { location.replace('/parent-change-password.html'); return; }
  document.querySelector('#who').textContent = me.parent.name;
  if (!childId) { fieldsBox.textContent = 'Липсва профил.'; return; }
  const { res, data } = await Parent.api(`/api/parent/children/${childId}/forms/spec`);
  if (res.status === 403 && data.code === 'password_change_required') { location.replace('/parent-change-password.html'); return; }
  if (!res.ok || !data.ok) { fieldsBox.textContent = 'Формата не може да се зареди в момента. Опитайте по-късно.'; return; }
  spec = data;
  build();
})();
