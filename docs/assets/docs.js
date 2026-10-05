/* SLATE 文档站交互 · 零依赖 · 主题 / 侧栏抽屉 / 目录跟随 / 客户端搜索 / 代码复制 */
(function () {
  'use strict';

  var root = document.documentElement;
  var INDEX = window.SLATE_DOCS_INDEX || [];

  /* ── 明暗主题 ─────────────────────────────── */

  function bindTheme() {
    var btn = document.querySelector('[data-theme-toggle]');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('slate-docs-theme', next); } catch (e) {}
    });
  }

  /* ── 侧栏抽屉（窄屏） ─────────────────────── */

  function bindDrawer() {
    var btn = document.querySelector('[data-menu]');
    var sidebar = document.querySelector('[data-sidebar]');
    var scrim = document.querySelector('[data-scrim]');
    if (!btn || !sidebar) return;

    function setOpen(open) {
      sidebar.classList.toggle('open', open);
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (scrim) scrim.hidden = !open;
      document.body.style.overflow = open ? 'hidden' : '';
    }

    btn.addEventListener('click', function () {
      setOpen(!sidebar.classList.contains('open'));
    });
    if (scrim) scrim.addEventListener('click', function () { setOpen(false); });
    sidebar.addEventListener('click', function (e) {
      if (e.target.closest('a')) setOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') setOpen(false);
    });
  }

  /* ── 右侧目录跟随滚动 ─────────────────────── */

  function bindScrollSpy() {
    var links = [].slice.call(document.querySelectorAll('.toc-list a'));
    if (!links.length) return;

    var targets = links
      .map(function (a) {
        var id = decodeURIComponent(a.getAttribute('href').slice(1));
        return document.getElementById(id);
      })
      .filter(Boolean);
    if (!targets.length) return;

    var current = -1;

    function update() {
      var line = window.scrollY + 110;
      var idx = 0;
      for (var i = 0; i < targets.length; i++) {
        if (targets[i].getBoundingClientRect().top + window.scrollY <= line) idx = i;
      }
      if (idx === current) return;
      current = idx;
      links.forEach(function (a, i) { a.classList.toggle('active', i === idx); });
    }

    var ticking = false;
    window.addEventListener('scroll', function () {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () { update(); ticking = false; });
    }, { passive: true });
    window.addEventListener('resize', update);
    update();
  }

  /* ── 代码块复制 ───────────────────────────── */

  function bindCopy() {
    document.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-copy]');
      if (!btn) return;
      var block = btn.closest('.code-block');
      var code = block && block.querySelector('pre code');
      if (!code) return;
      var text = code.textContent;

      function done() {
        btn.classList.add('done');
        btn.textContent = '已复制';
        setTimeout(function () {
          btn.classList.remove('done');
          btn.textContent = '复制';
        }, 1600);
      }

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, fallback);
      } else {
        fallback();
      }

      function fallback() {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); done(); } catch (err) {}
        document.body.removeChild(ta);
      }
    });
  }

  /* ── 客户端搜索 ───────────────────────────── */

  function bindSearch() {
    var overlay = document.querySelector('[data-search-overlay]');
    if (!overlay) return;
    var input = overlay.querySelector('[data-search-input]');
    var box = overlay.querySelector('[data-search-results]');
    var openers = document.querySelectorAll('[data-search-open]');
    var hits = [];
    var cursor = 0;

    function open() {
      overlay.hidden = false;
      document.body.style.overflow = 'hidden';
      input.value = '';
      input.focus();
      render('');
    }

    function close() {
      overlay.hidden = true;
      document.body.style.overflow = '';
    }

    function esc(s) {
      return String(s).replace(/[&<>"]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
      });
    }

    function termsOf(q) {
      return q.toLowerCase().split(/\s+/).filter(Boolean);
    }

    function score(item, terms) {
      var title = item.t.toLowerCase();
      var heads = (item.h || []).join(' ').toLowerCase();
      var body = (item.x || '').toLowerCase();
      var total = 0;
      for (var i = 0; i < terms.length; i++) {
        var t = terms[i];
        var s = 0;
        if (title.indexOf(t) !== -1) s += 120;
        if (heads.indexOf(t) !== -1) s += 40;
        var at = body.indexOf(t);
        if (at !== -1) {
          s += 12;
          if (at < 200) s += 8;
        }
        if (!s) return 0;
        total += s;
      }
      return total;
    }

    function snippet(item, terms) {
      var body = item.x || '';
      var low = body.toLowerCase();
      var at = -1;
      for (var i = 0; i < terms.length && at === -1; i++) at = low.indexOf(terms[i]);
      if (at === -1) return esc(body.slice(0, 110)) + (body.length > 110 ? '…' : '');
      var start = Math.max(0, at - 40);
      var text = (start ? '…' : '') + body.slice(start, at + 96).trim();
      var out = esc(text);
      terms.forEach(function (t) {
        if (!t) return;
        var re = new RegExp('(' + t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
        out = out.replace(re, '<mark>$1</mark>');
      });
      return out + '…';
    }

    function render(q) {
      var terms = termsOf(q);
      if (!terms.length) {
        hits = INDEX.slice(0, 8);
      } else {
        var scored = [];
        INDEX.forEach(function (item) {
          var s = score(item, terms);
          if (s) scored.push({ item: item, s: s });
        });
        scored.sort(function (a, b) { return b.s - a.s; });
        hits = scored.slice(0, 12).map(function (x) { return x.item; });
      }
      cursor = 0;

      if (!hits.length) {
        box.innerHTML = '<div class="search-empty">没有匹配的内容，换个关键词试试</div>';
        return;
      }

      box.innerHTML = hits
        .map(function (item, i) {
          return (
            '<a class="search-result' + (i === 0 ? ' active' : '') + '" href="' + esc(item.u) + '">' +
              '<div class="r-top">' + esc(item.t) +
                '<span class="r-sec">' + esc(item.s || '文档') + '</span>' +
              '</div>' +
              '<div class="r-snippet">' + snippet(item, terms) + '</div>' +
            '</a>'
          );
        })
        .join('');
    }

    function move(step) {
      var items = box.querySelectorAll('.search-result');
      if (!items.length) return;
      cursor = (cursor + step + items.length) % items.length;
      items.forEach(function (el, i) { el.classList.toggle('active', i === cursor); });
      items[cursor].scrollIntoView({ block: 'nearest' });
    }

    Array.prototype.forEach.call(openers, function (el) { el.addEventListener('click', open); });

    input.addEventListener('input', function () { render(input.value); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (e.key === 'Enter') {
        var items = box.querySelectorAll('.search-result');
        if (items[cursor]) { e.preventDefault(); window.location.href = items[cursor].getAttribute('href'); }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        close();
      }
    });

    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) close();
    });

    document.addEventListener('keydown', function (e) {
      var el = document.activeElement;
      var typing = !!el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName);
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (overlay.hidden) open(); else close();
        return;
      }
      if (e.key === 'Escape' && !overlay.hidden) { close(); return; }
      if (e.key === '/' && !typing && overlay.hidden) {
        e.preventDefault();
        open();
      }
    });
  }

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    bindTheme();
    bindDrawer();
    bindScrollSpy();
    bindCopy();
    bindSearch();
  });
})();
