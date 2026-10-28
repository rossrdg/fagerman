// Админ: галерия на отбор (албуми със снимки + YouTube клипове).
// Показва се в панела на отбор (admin-teams.html?team=<id>).
(function () {
  const teamParam = new URLSearchParams(location.search).get('team');
  const teamId = /^\d+$/.test(teamParam || '') ? Number(teamParam) : null;
  const section = document.getElementById('gallerySection');
  if (!teamId || !section) return;

  const $ = (sel) => section.querySelector(sel);
  const statusEl = $('#galStatus');
  const albumList = $('#albumList');
  const videoList = $('#videoList');
  const MAX_BYTES = 20 * 1024 * 1024;
  const DEFAULT_MAX_PHOTOS = 28;

  let albums = [];
  let videos = [];
  let openId = null;
  let statusTimer = null;

  // ---------------------------------------------------------- helpers ---
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function button(text, className, onClick) {
    const b = el('button', className, text);
    b.type = 'button';
    b.addEventListener('click', onClick);
    return b;
  }

  function flash(text, isError = false) {
    clearTimeout(statusTimer);
    statusEl.classList.toggle('error', isError);
    statusEl.classList.toggle('saved', !isError);
    statusEl.textContent = text;
    statusTimer = setTimeout(() => {
      statusEl.classList.remove('error', 'saved');
      statusEl.textContent = '';
    }, isError ? 6000 : 2500);
  }

  async function api(url, options = {}) {
    const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
    const data = await res.json().catch(() => ({}));
    return { res, data };
  }

  function showErrors(form, errors) {
    form.querySelectorAll('.field-error').forEach(e => { e.textContent = ''; });
    Object.entries(errors || {}).forEach(([field, msg]) => {
      const target = form.querySelector(`[data-error-for="${field}"]`);
      if (target) target.textContent = msg;
    });
  }

  function todayIso() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  // ----------------------------------------------------------- albums ---
  function albumSummary(album) {
    const count = album.photo_count;
    return `${album.date_text} · ${count} ${count === 1 ? 'снимка' : 'снимки'}`;
  }

  function renderAlbums() {
    albumList.textContent = '';
    if (!albums.length) {
      albumList.append(el('p', 'user-hint', 'Още няма албуми. Създайте първия с формата отгоре.'));
      return;
    }
    albums.forEach(album => {
      const item = el('div', 'album-item');
      const row = el('div', 'album-row');

      const thumb = el('img', 'album-thumb');
      thumb.alt = '';
      if (album.cover_thumb) thumb.src = album.cover_thumb;
      row.append(thumb);

      const meta = el('div', 'album-meta');
      const title = el('strong', '', album.title);
      if (album.is_hidden) title.append(el('span', 'mini-badge', 'скрит'));
      meta.append(title, el('small', '', albumSummary(album)));
      row.append(meta);

      row.append(button(openId === album.id ? 'Затвори' : 'Отвори', 'btn btn-outline btn-sm', () => toggleAlbum(album.id)));
      item.append(row);

      if (openId === album.id) item.append(editorFor(album));
      albumList.append(item);
    });
  }

  async function reloadAll() {
    const { res, data } = await api(`/api/admin/teams/${teamId}/gallery`);
    if (!res.ok || !data.ok) throw new Error('api');
    albums = data.albums;
    videos = data.videos;
  }

  async function refresh() {
    await reloadAll();
    renderAlbums();
    renderVideos();
  }

  function toggleAlbum(id) {
    openId = openId === id ? null : id;
    renderAlbums();
    if (openId) loadPhotos(id);
  }

  // Албумът в списъка е със снимките в отделен контейнер, който се пълни при отваряне.
  function editorFor(album) {
    const box = el('div', 'album-editor');
    box.dataset.albumId = album.id;

    const fields = el('div', 'album-edit-fields');
    const fTitle = el('div', 'field grow');
    const lTitle = el('label', '', 'Заглавие');
    const iTitle = el('input'); iTitle.value = album.title; iTitle.maxLength = 80;
    fTitle.append(lTitle, iTitle, el('div', 'field-error'));
    fTitle.querySelector('.field-error').dataset.errorFor = 'title';

    const fDate = el('div', 'field');
    const iDate = el('input'); iDate.type = 'date'; iDate.value = album.event_date;
    fDate.append(el('label', '', 'Дата'), iDate, el('div', 'field-error'));
    fDate.querySelector('.field-error').dataset.errorFor = 'event_date';

    const hide = el('label', 'check-item');
    const iHide = el('input'); iHide.type = 'checkbox'; iHide.checked = album.is_hidden;
    hide.append(iHide, el('span', '', 'Скрит от сайта'));

    fields.append(fTitle, fDate, hide,
      button('Запази', 'btn btn-primary btn-sm', async () => {
        const { res, data } = await api(`/api/admin/albums/${album.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ title: iTitle.value, event_date: iDate.value, is_hidden: iHide.checked })
        });
        if (!res.ok || !data.ok) {
          showErrors(fields, data.errors);
          flash(data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно запазване.'), true);
          return;
        }
        await refresh();
        loadPhotos(album.id);
        flash('Албумът е запазен ✓');
      }),
      button('Изтрий албума', 'btn btn-danger btn-sm', async () => {
        if (!confirm(`Да изтрия ли албума „${album.title}“ и всичките му снимки? Това не може да се върне.`)) return;
        const { res, data } = await api(`/api/admin/albums/${album.id}`, { method: 'DELETE' });
        if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно изтриване.', true); return; }
        openId = null;
        await refresh();
        flash('Албумът е изтрит ✓');
      }));
    box.append(fields);

    // Качване
    const upload = el('div', 'upload-box');
    upload.append(el('p', '', 'Качвайки снимки, потвърждавате, че имате съгласие на родителите. Без имена на деца в албума.'));
    const maxPhotos = album.max_photos || DEFAULT_MAX_PHOTOS;
    const remaining = Math.max(0, maxPhotos - album.photo_count);
    upload.append(el('p', 'upload-limit', `Снимки: ${album.photo_count} от ${maxPhotos}. До 20 MB на снимка; JPG, PNG, HEIC (iPhone) и др.`));
    const input = el('input');
    input.type = 'file'; input.multiple = true; input.accept = 'image/*,.heic,.heif,.avif';
    const progress = el('div', 'upload-progress');
    if (remaining === 0) {
      input.disabled = true;
      upload.append(el('p', 'upload-full', 'Албумът е пълен. За повече снимки създайте нов албум.'));
    }
    upload.append(input, progress);
    input.addEventListener('change', () => uploadFiles(album.id, [...input.files], progress, input));
    box.append(upload);

    box.append(el('div', 'photo-admin-grid'));
    return box;
  }

  function gridFor(albumId) {
    return albumList.querySelector(`.album-editor[data-album-id="${albumId}"] .photo-admin-grid`);
  }

  async function loadPhotos(albumId) {
    const { res, data } = await api(`/api/admin/albums/${albumId}`);
    const grid = gridFor(albumId);
    if (!grid) return;
    grid.textContent = '';
    if (!res.ok || !data.ok) { grid.append(el('p', 'user-hint', 'Снимките не можаха да се заредят.')); return; }
    if (!data.album.photos.length) {
      grid.append(el('p', 'user-hint', 'Още няма снимки. Изберете файлове по-горе.'));
      return;
    }
    data.album.photos.forEach(photo => grid.append(photoTile(albumId, photo)));
  }

  function photoTile(albumId, photo) {
    const tile = el('div', 'photo-admin');
    const img = el('img');
    img.src = photo.thumb; img.alt = `Снимка № ${photo.code}`; img.loading = 'lazy';
    const info = el('div', 'info');
    const code = el('div', 'code', `№ ${photo.code}`);
    if (photo.is_cover) code.append(el('span', 'cover-badge', 'корица'));
    info.append(code, el('div', 'who', photo.uploaded_by ? `качена от ${photo.uploaded_by}` : ''));

    const actions = el('div', 'actions');
    if (!photo.is_cover) {
      actions.append(button('Корица', 'btn btn-outline btn-sm', async () => {
        const { res, data } = await api(`/api/admin/albums/${albumId}`, {
          method: 'PATCH', body: JSON.stringify({ cover_photo_id: photo.id })
        });
        if (!res.ok || !data.ok) { flash(data.error || 'Неуспешна промяна.', true); return; }
        await refresh();
        loadPhotos(albumId);
        flash('Корицата е сменена ✓');
      }));
    }
    actions.append(button('Изтрий', 'btn btn-outline btn-sm btn-danger-text', async () => {
      if (!confirm(`Да изтрия ли снимка № ${photo.code}?`)) return;
      const { res, data } = await api(`/api/admin/photos/${photo.id}`, { method: 'DELETE' });
      if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно изтриване.', true); return; }
      await refresh();
      loadPhotos(albumId);
      flash('Снимката е изтрита ✓');
    }));
    tile.append(img, info, actions);
    return tile;
  }

  // Качва снимките една по една (по-надеждно при бавна връзка и големи файлове).
  async function uploadFiles(albumId, files, progress, input) {
    if (!files.length) return;
    progress.textContent = '';
    let done = 0;
    let failed = 0;
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const line = el('div', '', `Качване ${i + 1} от ${files.length}: ${file.name}…`);
      progress.append(line);
      if (file.size > MAX_BYTES) {
        line.className = 'err'; line.textContent = `${file.name}: над 20 MB — пропусната.`; failed++;
        continue;
      }
      try {
        const body = new FormData();
        body.append('image', file);
        const res = await fetch(`/api/admin/albums/${albumId}/photos`, { method: 'POST', body });
        const data = await res.json().catch(() => ({}));
        if (res.status === 409) {
          // Албумът се напълни: тази и всички следващи снимки се пропускат (неуспелите по-рано не заемат място).
          line.className = 'err';
          line.textContent = `${file.name}: албумът е пълен (максимум 28 снимки) — пропусната.`;
          failed++;
          for (const rest of files.slice(i + 1)) {
            progress.append(el('div', 'err', `${rest.name}: албумът е пълен — пропусната.`));
            failed++;
          }
          break;
        }
        if (!res.ok || !data.ok) throw new Error(data.error || 'Грешка');
        line.textContent = `${file.name}: готова (№ ${data.photo.code}) ✓`;
        done++;
      } catch (err) {
        line.className = 'err'; line.textContent = `${file.name}: ${err.message}`; failed++;
      }
    }
    input.value = '';
    await refresh();
    loadPhotos(albumId);
    // Списъкът се прерисува след качването — връщаме съобщенията по файлове, за да се виждат грешките.
    const newProgress = albumList.querySelector(`.album-editor[data-album-id="${albumId}"] .upload-progress`);
    if (newProgress) [...progress.children].forEach(line => newProgress.append(line));
    flash(failed ? `Качени: ${done}, неуспешни: ${failed}.` : `Качени снимки: ${done} ✓`, failed > 0);
  }

  $('#albumCreateBtn').addEventListener('click', async () => {
    const form = $('#albumForm');
    const { res, data } = await api(`/api/admin/teams/${teamId}/albums`, {
      method: 'POST',
      body: JSON.stringify({ title: $('#al-title').value, event_date: $('#al-date').value || todayIso() })
    });
    if (!res.ok || !data.ok) {
      showErrors(form, data.errors);
      flash(data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно създаване.'), true);
      return;
    }
    showErrors(form, {});
    $('#al-title').value = '';
    openId = data.album.id;
    await refresh();
    loadPhotos(openId);
    flash('Албумът е създаден — качете снимки ✓');
  });

  // ----------------------------------------------------------- videos ---
  function renderVideos() {
    videoList.textContent = '';
    if (!videos.length) {
      videoList.append(el('p', 'user-hint', 'Още няма добавени клипове.'));
      return;
    }
    videos.forEach(video => {
      const row = el('div', 'video-row');
      const info = el('div', 'grow');
      info.append(el('strong', '', video.title || 'Клип без заглавие'));
      const link = el('a', '', video.url);
      link.href = video.url; link.target = '_blank'; link.rel = 'noopener';
      info.append(el('br'), link);
      row.append(info, button('Изтрий', 'btn btn-outline btn-sm btn-danger-text', async () => {
        if (!confirm('Да премахна ли този клип от отбора?')) return;
        const { res, data } = await api(`/api/admin/videos/${video.id}`, { method: 'DELETE' });
        if (!res.ok || !data.ok) { flash(data.error || 'Неуспешно изтриване.', true); return; }
        await refresh();
        flash('Клипът е премахнат ✓');
      }));
      videoList.append(row);
    });
  }

  $('#videoAddBtn').addEventListener('click', async () => {
    const form = $('#videoForm');
    const { res, data } = await api(`/api/admin/teams/${teamId}/videos`, {
      method: 'POST',
      body: JSON.stringify({ url: $('#vd-url').value, title: $('#vd-title').value })
    });
    if (!res.ok || !data.ok) {
      showErrors(form, data.errors);
      flash(data.errors ? 'Проверете маркираните полета.' : (data.error || 'Неуспешно добавяне.'), true);
      return;
    }
    showErrors(form, {});
    $('#vd-url').value = '';
    $('#vd-title').value = '';
    await refresh();
    flash('Клипът е добавен ✓');
  });

  [$('#albumForm'), $('#videoForm')].forEach(f => f.addEventListener('submit', e => e.preventDefault()));

  // ------------------------------------------------------------- start ---
  $('#al-date').value = todayIso();
  section.hidden = false;
  refresh().catch(() => {
    flash('Галерията не можа да се зареди. Провери дали backend-ът работи.', true);
  });
})();
