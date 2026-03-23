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
