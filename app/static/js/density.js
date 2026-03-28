/**
 * density.js — Article card density/compression behaviour.
 * Handles first-sentence extraction and tap-to-expand interaction.
 */
(function () {
  'use strict';

  var MAX_CHARS = 300;
  var MAX_WORDS = 50;

  // ── First-sentence extraction ─────────────────────────────────────────────

  function splitFirstSentence(text) {
    // Find first natural sentence ending within char limit
    var limited = text.length > MAX_CHARS ? text.slice(0, MAX_CHARS + 40) : text;
    var m = limited.match(/^([\s\S]+?[.!?])(?:\s|$)/);
    if (m) {
      var words = m[1].trim().split(/\s+/).filter(Boolean);
      if (words.length <= MAX_WORDS) {
        return { first: m[1].trim(), rest: text.slice(m.index + m[0].length).trim() };
      }
    }
    // Fallback: word/char cap
    var words = text.trim().split(/\s+/).filter(Boolean);
    var kept = words.slice(0, MAX_WORDS).join(' ');
    if (kept.length > MAX_CHARS) kept = text.slice(0, MAX_CHARS);
    return { first: kept + '\u2026', rest: '' };
  }

  // ── Prepare cards: inject .first-sentence / .rest-of-snippet spans ────────

  function prepareCards() {
    document.querySelectorAll('.article-card:not(.redactional-card)').forEach(function (card) {
      var snippet = card.querySelector('.article-snippet');
      if (!snippet) return;

      var fullText = snippet.textContent.trim();
      if (!fullText) return;

      var split = splitFirstSentence(fullText);

      var firstSpan = document.createElement('span');
      firstSpan.className = 'first-sentence';
      firstSpan.textContent = split.first;

      snippet.textContent = '';
      snippet.appendChild(firstSpan);

      if (split.rest) {
        var restSpan = document.createElement('span');
        restSpan.className = 'rest-of-snippet';
        restSpan.textContent = ' ' + split.rest;
        snippet.appendChild(restSpan);
      }

      // ── Click handler ───────────────────────────────────────────────────

      card.addEventListener('click', function (e) {
        var density = document.documentElement.getAttribute('data-density');
        if (density === 'full') return; // normal link behaviour

        // Always let the external ↗ link through
        if (e.target.closest('.ext-indicator')) return;

        e.preventDefault();
        e.stopPropagation();

        if (card.classList.contains('density-expanded')) {
          // Second interaction: navigate to article detail
          var link = card.querySelector('.article-title a');
          if (link) window.location.href = link.href;
        } else {
          // First interaction: expand this card, collapse others
          document.querySelectorAll('.article-card.density-expanded').forEach(function (other) {
            if (other !== card) other.classList.remove('density-expanded');
          });
          card.classList.add('density-expanded');
          window.dispatchEvent(new Event('resize'));
        }
      });
    });
  }

  document.addEventListener('DOMContentLoaded', prepareCards);

})();
