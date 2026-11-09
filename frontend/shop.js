// Публичен магазин: избор на размер, цена по размер, количка (пази се в браузъра).
(function () {
  'use strict';

  var CART_KEY = 'fagerman_cart_v1';
  var MAX_QTY = 10;

  var data = [];
  try { data = JSON.parse(document.getElementById('shopData').textContent) || []; } catch (e) { data = []; }
  var products = {};
  data.forEach(function (p) { products[p.id] = p; });

  function $(id) { return document.getElementById(id); }
  var grid = $('shopGrid'), modal = $('productModal'), drawer = $('cartDrawer'), toast = $('shopToast');
  var fab = $('cartFab'), fabCount = $('cartCount');
  if (!grid) return; // няма артикули — няма какво да се прави

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function eur(n) { return (Math.round(n * 100) % 100 === 0) ? String(Math.round(n)) : n.toFixed(2).replace('.', ','); }

  // ------------------------------------------------------------- цени ---
  function groupOf(product, size) {
    for (var i = 0; i < product.groups.length; i++) {
      var g = product.groups[i];
      for (var j = 0; j < g.sizes.length; j++) if (g.sizes[j].size === size) return { group: g, entry: g.sizes[j] };
    }
    return null;
  }

  // ------------------------------------------------ персонализация ---
  var NAME_RE = /^[A-Za-z][A-Za-z .'\-]*$/;
  var MAX_NAME = 14;

  // Връща { name, number } (по желание) или { error }. Празно = без персонализация.
  function readPersonal(nameRaw, numberRaw) {
    var name = String(nameRaw || '').replace(/\s+/g, ' ').trim();
    var number = String(numberRaw || '').trim();
    if (name) {
      if (name.length > MAX_NAME) return { error: 'Името е до ' + MAX_NAME + ' знака.' };
      if (!NAME_RE.test(name)) return { error: 'Името трябва да е на латиница (A–Z).' };
      name = name.toUpperCase();
    }
    if (number) {
      if (!/^\d{1,2}$/.test(number) || +number < 1 || +number > 99) return { error: 'Номерът е от 1 до 99.' };
      number = String(parseInt(number, 10));
    }
    return { name: name, number: number };
  }
  function isPersonal(l) { return !!(l.pname || l.pnumber); }
  function persFee(p) { return p.personalization ? p.personalization.fee : 0; }
  function persText(l) {
    var parts = [];
    if (l.pname) parts.push('име ' + l.pname);
    if (l.pnumber) parts.push('номер ' + l.pnumber);
    return parts.join(', ');
  }
  function sameLine(a, b) {
    return a.id === b.id && a.size === b.size && (a.pname || '') === (b.pname || '') && (a.pnumber || '') === (b.pnumber || '');
  }

  // ---------------------------------------------------------- количка ---
  var cart = [];

  function load() {
    var raw = [];
    try { raw = JSON.parse(localStorage.getItem(CART_KEY)) || []; } catch (e) { raw = []; }
    cart = [];
    if (!Array.isArray(raw)) return;
    raw.forEach(function (l) {
      var p = l && products[l.id];
      var found = p && groupOf(p, l.size);
      var qty = parseInt(l && l.qty, 10);
      if (!p || !found || found.entry.sold_out || !(qty > 0)) return; // изчезнал артикул/размер — махаме реда
      var pers = readPersonal(l.pname, l.pnumber);
      if (pers.error || (!p.personalization && (pers.name || pers.number))) return; // стара/невалидна персонализация — махаме реда
      cart.push({ id: p.id, size: l.size, qty: Math.min(qty, MAX_QTY), pname: pers.name, pnumber: pers.number });
    });
  }
  function save() { try { localStorage.setItem(CART_KEY, JSON.stringify(cart)); } catch (e) { /* без запис — количката важи за сесията */ } }

  function unitPrice(l) { return groupOf(products[l.id], l.size).group.price + (isPersonal(l) ? persFee(products[l.id]) : 0); }
  function lineTotal(l) { return unitPrice(l) * l.qty; }
  function cartTotal() { return cart.reduce(function (s, l) { return s + lineTotal(l); }, 0); }
  function cartCount() { return cart.reduce(function (s, l) { return s + l.qty; }, 0); }

  function addToCart(id, size, pers) {
    var item = { id: id, size: size, qty: 1, pname: (pers && pers.name) || '', pnumber: (pers && pers.number) || '' };
    var line = cart.filter(function (l) { return sameLine(l, item); })[0];
    if (line) line.qty = Math.min(line.qty + 1, MAX_QTY); else cart.push(item);
    save(); renderCart();
  }

  function renderCart() {
    var count = cartCount();
    fabCount.textContent = String(count);
    fab.hidden = count === 0 || !modal.hidden || !drawer.hidden;
    var box = $('cartItems');
    box.textContent = '';
    if (!cart.length) {
      box.appendChild(el('div', 'cart-empty', 'Количката е празна.'));
    }
    cart.forEach(function (l, index) {
      var p = products[l.id];
      var row = el('div', 'cart-line');
      if (p.thumb) { var img = el('img'); img.src = p.thumb; img.alt = ''; row.appendChild(img); }
      else row.appendChild(el('div', 'cart-noimg', 'ФА'));

      var mid = el('div');
      mid.appendChild(el('div', 'cart-line-name', p.name));
      var g = groupOf(p, l.size).group;
      mid.appendChild(el('div', 'cart-line-meta', p.one_size ? 'Един размер' : 'Размер ' + l.size + ' (' + g.label.toLowerCase() + ')'));
      if (isPersonal(l)) mid.appendChild(el('div', 'cart-line-pers', 'Персонализация: ' + persText(l) + ' (+' + eur(persFee(p)) + ' €)'));
      var qty = el('div', 'cart-qty');
      var minus = el('button', '', '−'); minus.type = 'button'; minus.setAttribute('aria-label', 'Намали броя');
      minus.addEventListener('click', function () { changeQty(index, -1); });
      var plus = el('button', '', '+'); plus.type = 'button'; plus.setAttribute('aria-label', 'Увеличи броя');
      plus.addEventListener('click', function () { changeQty(index, 1); });
      qty.appendChild(minus); qty.appendChild(el('span', '', String(l.qty))); qty.appendChild(plus);
      mid.appendChild(qty);
      row.appendChild(mid);

      var side = el('div', 'cart-line-side');
      side.appendChild(el('div', 'cart-line-price', eur(lineTotal(l)) + ' €'));
      var rm = el('button', 'cart-remove', 'Махни'); rm.type = 'button';
      rm.addEventListener('click', function () { cart.splice(index, 1); save(); renderCart(); });
      side.appendChild(rm);
      row.appendChild(side);
      box.appendChild(row);
    });
    $('cartTotal').textContent = eur(cartTotal()) + ' €';
    $('cartCheckout').disabled = !cart.length;
  }

  function changeQty(index, delta) {
    var l = cart[index];
    if (!l) return;
    l.qty += delta;
    if (l.qty < 1) cart.splice(index, 1); else if (l.qty > MAX_QTY) l.qty = MAX_QTY;
    save(); renderCart();
  }

  // ---------------------------------------------------- прозорци ---
  var lastFocus = null;

  function openOverlay(node, focusSel) {
    lastFocus = document.activeElement;
    node.hidden = false;
    document.body.classList.add('shop-locked');
    fab.hidden = true;
    var target = node.querySelector(focusSel);
    if (target) target.focus();
  }
  function closeOverlay(node) {
    node.hidden = true;
    if (node === drawer) showView('cart');
    if (modal.hidden && drawer.hidden) document.body.classList.remove('shop-locked');
    renderCart();
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  [modal, drawer].forEach(function (node) {
    node.addEventListener('click', function (e) { if (e.target.closest('[data-close]')) closeOverlay(node); });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (!modal.hidden) closeOverlay(modal); else if (!drawer.hidden) closeOverlay(drawer);
  });

  var current = null;   // отворения артикул
  var selected = null;  // избраният размер

  function showPrice() {
    var p = current;
    var extra = (p.personalization && $('pmPersOn').checked) ? p.personalization.fee : 0;
    if (selected) $('pmPrice').textContent = eur(groupOf(p, selected).group.price + extra) + ' €';
    else $('pmPrice').textContent = p.price_text + (extra ? ' (+' + eur(extra) + ' € персонализация)' : '');
  }

  function openProduct(id) {
    var p = products[id];
    if (!p) return;
    current = p;
    selected = p.one_size ? p.groups[0].sizes[0].size : null;
    $('pmName').textContent = p.name;
    var img = $('pmImage');
    img.src = p.image || p.thumb || '';
    img.alt = p.name;
    img.parentNode.hidden = !(p.image || p.thumb);
    $('pmError').textContent = '';
    $('pmPersOn').checked = false;
    $('pmPersName').value = '';
    $('pmPersNumber').value = '';
    $('pmPersFields').hidden = true;
    $('pmPers').hidden = !p.personalization;
    if (p.personalization) $('pmPersFee').textContent = '(+' + eur(p.personalization.fee) + ' €)';

    var box = $('pmGroups');
    box.textContent = '';
    var soldOutAll = true;
    if (!p.one_size) {
      p.groups.forEach(function (g) {
        var wrap = el('div');
        var title = el('div', 'pm-group-title');
        title.appendChild(el('span', '', g.label + ' размери'));
        title.appendChild(el('b', '', eur(g.price) + ' €'));
        wrap.appendChild(title);
        var sizes = el('div', 'pm-sizes');
        g.sizes.forEach(function (s) {
          var b = el('button', 'pm-size', s.size);
          b.type = 'button';
          b.setAttribute('aria-pressed', 'false');
          if (s.sold_out) { b.disabled = true; b.title = 'Изчерпан'; } else soldOutAll = false;
          b.addEventListener('click', function () {
            selected = s.size;
            box.querySelectorAll('.pm-size').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
            $('pmError').textContent = '';
            showPrice();
          });
          sizes.appendChild(b);
        });
        wrap.appendChild(sizes);
        box.appendChild(wrap);
      });
    } else {
      soldOutAll = p.groups[0].sizes[0].sold_out;
    }
    var add = $('pmAdd');
    add.disabled = soldOutAll;
    add.firstChild.textContent = soldOutAll ? 'Изчерпан' : 'Добави в количката ';
    showPrice();
    openOverlay(modal, '.pm-size:not(:disabled), #pmAdd');
  }

  $('pmAdd').addEventListener('click', function () {
    if (!current) return;
    if (!selected) { $('pmError').textContent = 'Изберете размер.'; return; }
    var pers = null;
    if (current.personalization && $('pmPersOn').checked) {
      pers = readPersonal($('pmPersName').value, $('pmPersNumber').value);
      if (pers.error) { $('pmError').textContent = pers.error; return; }
      if (!pers.name && !pers.number) {
        $('pmError').textContent = 'Въведете име и/или номер, или махнете отметката за персонализация.';
        return;
      }
    }
    addToCart(current.id, selected, pers);
    var name = current.name;
    closeOverlay(modal);
    say('Добавено в количката: ' + name);
    fab.classList.remove('bump'); void fab.offsetWidth; fab.classList.add('bump');
  });

  $('pmPersOn').addEventListener('change', function () {
    $('pmPersFields').hidden = !this.checked;
    $('pmError').textContent = '';
    showPrice();
    if (this.checked) $('pmPersName').focus();
  });
  ['pmPersName', 'pmPersNumber'].forEach(function (id) {
    $(id).addEventListener('input', function () { $('pmError').textContent = ''; });
  });

  var toastTimer = null;
  function say(text) {
    toast.textContent = text;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.classList.remove('show'); }, 2600);
  }

  // ------------------------------------------------------ поръчка ---
  var views = { cart: $('viewCart'), checkout: $('viewCheckout'), done: $('viewDone') };
  var titles = { cart: 'Количка', checkout: 'Данни за поръчката', done: 'Благодарим!' };
  var form = $('viewCheckout');
  var submitBtn = $('orderSubmit');
  var submitting = false;

  function showView(name) {
    Object.keys(views).forEach(function (k) { views[k].hidden = k !== name; });
    $('cartTitle').textContent = titles[name];
    var scroller = views[name].querySelector('.cart-items');
    if (scroller) scroller.scrollTop = 0;
  }

  function clearOrderErrors() {
    form.querySelectorAll('[data-error-for]').forEach(function (n) { n.textContent = ''; });
    form.querySelectorAll('.has-error').forEach(function (n) { n.classList.remove('has-error'); });
    $('orderError').textContent = '';
  }

  function showOrderErrors(errors) {
    clearOrderErrors();
    var first = null;
    Object.keys(errors || {}).forEach(function (field) {
      if (field === '_') { $('orderError').textContent = errors._; return; }
      var target = form.querySelector('[data-error-for="' + field + '"]');
      if (!target) { $('orderError').textContent = errors[field]; return; }
      target.textContent = errors[field];
      var holder = target.closest('.of-field');
      if (holder) holder.classList.add('has-error');
      if (!first) first = form.querySelector('[name="' + field + '"]');
    });
    if (first && first.focus) first.focus();
  }

  function renderSummary() {
    var box = $('orderSummary');
    box.textContent = '';
    cart.forEach(function (l) {
      var p = products[l.id];
      var line = el('div', 'os-line');
      var label = p.name + ' · ' + (p.one_size ? 'един размер' : l.size) + (isPersonal(l) ? ' · ' + persText(l) : '') + ' × ' + l.qty;
      line.appendChild(el('span', '', label));
      line.appendChild(el('span', '', eur(lineTotal(l)) + ' €'));
      box.appendChild(line);
    });
    var total = el('div', 'os-total');
    total.appendChild(el('span', '', 'Общо (ориентировъчно)'));
    total.appendChild(el('span', '', eur(cartTotal()) + ' €'));
    box.appendChild(total);
  }

  function syncDelivery() {
    var delivery = form.querySelector('input[name="delivery"]:checked').value === 'delivery';
    $('addressField').hidden = !delivery;
  }

  $('cartCheckout').addEventListener('click', function () {
    if (!cart.length) return;
    clearOrderErrors();
    renderSummary();
    showView('checkout');
    $('o-name').focus();
  });
  $('backToCart').addEventListener('click', function () { showView('cart'); });
  form.querySelectorAll('input[name="delivery"]').forEach(function (r) { r.addEventListener('change', syncDelivery); });
  $('doneClose').addEventListener('click', function () { closeOverlay(drawer); });
  // Щом клиентът поправя поле, съобщението за него изчезва.
  function clearFieldError(e) {
    var name = e.target && e.target.name;
    if (!name) return;
    var msg = form.querySelector('[data-error-for="' + name + '"]');
    if (msg) msg.textContent = '';
    var holder = e.target.closest('.of-field');
    if (holder) holder.classList.remove('has-error');
    $('orderError').textContent = '';
  }
  form.addEventListener('input', clearFieldError);
  form.addEventListener('change', clearFieldError);

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (submitting || !cart.length) return;
    var consent = $('o-consent').checked;
    if (!consent) {
      showOrderErrors({ consent: 'Моля, потвърдете, че сте запознат/а с Политиката за обработване на лични данни.' });
      return;
    }
    var payload = {
      customer: {
        name: $('o-name').value, email: $('o-email').value, phone: $('o-phone').value,
        delivery: form.querySelector('input[name="delivery"]:checked').value,
        address: $('o-address').value, consent: consent
      },
      items: cart.map(function (l) {
        var item = { id: l.id, size: l.size, qty: l.qty };
        if (isPersonal(l)) item.personal = { name: l.pname, number: l.pnumber };
        return item;
      }),
      website: $('o-website').value
    };
    submitting = true;
    submitBtn.disabled = true;
    submitBtn.firstChild.textContent = 'Изпращане... ';
    clearOrderErrors();

    fetch('/api/shop/orders', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      .then(function (res) { return res.json().catch(function () { return {}; }).then(function (data) { return { res: res, data: data }; }); })
      .then(function (r) {
        if (r.res.ok && r.data.ok) {
          cart = []; save(); renderCart();
          form.reset(); syncDelivery();
          $('doneNumber').textContent = r.data.order.number;
          showView('done');
          return;
        }
        if (r.data.errors) showOrderErrors(r.data.errors);
        else $('orderError').textContent = r.data.error || 'Поръчката не беше изпратена. Опитайте пак.';
      })
      .catch(function () { $('orderError').textContent = 'Няма връзка със сървъра. Опитайте пак след малко.'; })
      .then(function () { submitting = false; submitBtn.disabled = false; submitBtn.firstChild.textContent = 'Изпрати поръчка '; });
  });

  // ------------------------------------------------------------ старт ---
  grid.addEventListener('click', function (e) {
    var card = e.target.closest('.shop-card');
    if (card) openProduct(parseInt(card.getAttribute('data-id'), 10));
  });
  fab.addEventListener('click', function () { renderCart(); openOverlay(drawer, '.shop-close'); });

  load();
  save();
  renderCart();
})();
