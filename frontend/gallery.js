// Публична галерия: преглед на снимки (lightbox) и YouTube клипове с пускане при клик.
(function () {
  // ---- Клипове: плейърът се зарежда чак при натискане (youtube-nocookie, без проследяване преди това)
  document.querySelectorAll('[data-youtube]').forEach(function (card) {
    card.addEventListener('click', function (e) {
      e.preventDefault();
      var frame = document.createElement('iframe');
      frame.src = 'https://www.youtube-nocookie.com/embed/' + encodeURIComponent(card.dataset.youtube) + '?autoplay=1&rel=0';
      frame.title = card.dataset.title || 'Клип от YouTube';
      frame.allow = 'accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture; fullscreen';
      frame.allowFullscreen = true;
      frame.className = 'video-frame';
      var box = document.createElement('div');
      box.className = 'video-box';
      box.appendChild(frame);
      card.replaceWith(box);
    });
  });

  // ---- Албум: lightbox със стрелки и Esc
  var grid = document.getElementById('photoGrid');
  var box = document.getElementById('lightbox');
  if (!grid || !box) return;
  var tiles = Array.prototype.slice.call(grid.querySelectorAll('.photo-tile'));
  var img = document.getElementById('lbImg');
  var caption = document.getElementById('lbCode');
  var index = 0;
  var opener = null;

  function show(i) {
    index = (i + tiles.length) % tiles.length;
    var tile = tiles[index];
    img.src = tile.dataset.full;
    img.alt = 'Снимка № ' + tile.dataset.code;
    caption.textContent = '№ ' + tile.dataset.code;
  }
  function open(i) {
    opener = document.activeElement;
    show(i);
    box.hidden = false;
    document.body.style.overflow = 'hidden';
    box.querySelector('.lb-close').focus();
  }
  function close() {
    box.hidden = true;
    img.src = '';
    document.body.style.overflow = '';
    if (opener && opener.focus) opener.focus();
  }

  tiles.forEach(function (tile, i) { tile.addEventListener('click', function () { open(i); }); });
  box.querySelector('.lb-close').addEventListener('click', close);
  box.querySelector('.lb-prev').addEventListener('click', function () { show(index - 1); });
  box.querySelector('.lb-next').addEventListener('click', function () { show(index + 1); });
  box.addEventListener('click', function (e) { if (e.target === box) close(); });
  document.addEventListener('keydown', function (e) {
    if (box.hidden) return;
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowLeft') show(index - 1);
    else if (e.key === 'ArrowRight') show(index + 1);
  });
})();
