/**
 * site.js — Theme switching, font-size control, and read-aloud (TTS).
 * Runs synchronously in <head> so theme is applied before first paint (no FOUC).
 */
(function () {
  'use strict';

  var root = document.documentElement;
  var THEMES = ['light', 'dark', 'green', 'hippy'];
  var SIZES  = ['s', 'm', 'l'];

  // ── Theme ────────────────────────────────────────────────────────────────────

  function applyTheme(theme) {
    if (THEMES.indexOf(theme) === -1) theme = 'light';
    root.setAttribute('data-theme', theme);
    try { localStorage.setItem('theme', theme); } catch(e) {}
    document.querySelectorAll('.theme-btn').forEach(function(btn) {
      var on = btn.dataset.theme === theme;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  // ── Font size ─────────────────────────────────────────────────────────────────

  function applyFont(size) {
    if (SIZES.indexOf(size) === -1) size = 'm';
    root.setAttribute('data-font', size);
    try { localStorage.setItem('font', size); } catch(e) {}
    document.querySelectorAll('.font-btn').forEach(function(btn) {
      var on = btn.dataset.font === size;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    window.dispatchEvent(new Event('resize'));
  }

  // ── Apply immediately (before DOM, prevents FOUC) ────────────────────────────

  try {
    applyTheme(localStorage.getItem('theme') || 'light');
    applyFont(localStorage.getItem('font')   || 'm');
  } catch(e) {}

  // ── Wire up controls after DOM is ready ──────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {

    // Re-apply to update button active states now that buttons exist
    applyTheme(root.getAttribute('data-theme') || 'light');
    applyFont(root.getAttribute('data-font')   || 'm');

    document.querySelectorAll('.theme-btn').forEach(function(btn) {
      btn.addEventListener('click', function() { applyTheme(btn.dataset.theme); });
    });

    document.querySelectorAll('.font-btn').forEach(function(btn) {
      btn.addEventListener('click', function() { applyFont(btn.dataset.font); });
    });

    // ── TTS (Web Speech API) ──────────────────────────────────────────────────

    var ttsBtn = document.getElementById('tts-btn');
    if (ttsBtn) {
      if (!('speechSynthesis' in window)) {
        ttsBtn.style.display = 'none';
      } else {
        var speaking = false;

        function stopTTS() {
          window.speechSynthesis.cancel();
          speaking = false;
          ttsBtn.classList.remove('active');
          ttsBtn.title = 'Lees voor';
          ttsBtn.setAttribute('aria-pressed', 'false');
        }

        ttsBtn.addEventListener('click', function () {
          if (speaking) { stopTTS(); return; }

          // Grab readable text: prefer article content, fall back to <main>
          var target = document.querySelector('main .article-card, main article, main')
          var text = target ? target.innerText : '';
          text = text.trim();
          if (!text) return;

          var utter = new SpeechSynthesisUtterance(text);
          utter.lang  = 'nl-NL';
          utter.rate  = 0.90;
          utter.pitch = 1.0;

          // Pick a Dutch voice if available
          var voices = window.speechSynthesis.getVoices();
          var nlVoice = voices.find(function(v) { return v.lang.startsWith('nl'); });
          if (nlVoice) utter.voice = nlVoice;

          utter.onend   = stopTTS;
          utter.onerror = stopTTS;

          speaking = true;
          ttsBtn.classList.add('active');
          ttsBtn.title = 'Stop voorlezen';
          ttsBtn.setAttribute('aria-pressed', 'true');
          window.speechSynthesis.speak(utter);
        });

        // Voices load async in some browsers
        if (window.speechSynthesis.onvoiceschanged !== undefined) {
          window.speechSynthesis.onvoiceschanged = function() {};
        }
      }
    }
  });

})();

// ── Masonry layout ────────────────────────────────────────────────────────────
// Falls back gracefully if CSS native masonry is already active or JS disabled.

(function () {
  'use strict';

  function masonry(grid) {
    // Only run if the browser didn't apply native CSS masonry
    if (getComputedStyle(grid).gridTemplateRows === 'masonry') return;

    var items = Array.prototype.slice.call(grid.children);
    if (items.length < 2) return;

    // Reset any previous absolute positioning so we can measure natural heights
    grid.style.position = 'relative';
    items.forEach(function (el) {
      el.style.position = '';
      el.style.top      = '';
      el.style.left     = '';
      el.style.width    = '';
    });

    // Measure column count and gap from computed style
    var cs       = getComputedStyle(grid);
    var colCount = cs.gridTemplateColumns.split(' ').length;
    if (colCount < 2) {
      // Single column — no masonry needed, clear and return
      grid.style.height = '';
      return;
    }
    var colGap   = parseFloat(cs.columnGap)  || 0;
    var rowGap   = parseFloat(cs.rowGap)     || 0;
    var colW     = (grid.clientWidth - colGap * (colCount - 1)) / colCount;

    // Measure each item's natural height at the correct width
    items.forEach(function (el) {
      el.style.width    = colW + 'px';
      el.style.position = 'absolute';
    });

    var tops = new Array(colCount).fill(0);

    items.forEach(function (el) {
      // Place in the shortest column
      var col = tops.indexOf(Math.min.apply(null, tops));
      var x   = col * (colW + colGap);
      var y   = tops[col];
      el.style.left = x + 'px';
      el.style.top  = y + 'px';
      tops[col] += el.offsetHeight + rowGap;
    });

    grid.style.height = Math.max.apply(null, tops) - rowGap + 'px';
  }

  function applyAll() {
    document.querySelectorAll('.article-list').forEach(masonry);
  }

  // Run after full paint so images/fonts don't shift heights
  if (document.readyState === 'complete') {
    applyAll();
  } else {
    window.addEventListener('load', applyAll);
  }

  // Re-run on resize (debounced)
  var _rTimer;
  window.addEventListener('resize', function () {
    clearTimeout(_rTimer);
    _rTimer = setTimeout(applyAll, 120);
  });
})();
