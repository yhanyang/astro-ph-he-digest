/* Action row (star · note · similar · wiki · like · dislike) for the paper cards of the
 * search / similar / recommend pages. Mirrors the buttons of the daily reports:
 *  - stars use the same localStorage keys as the reports (arxiv-report:<date>:<id>:starred),
 *    so they show up in both places and on the Starred page;
 *  - notes, likes and dislikes go to the same server routes (/note, /feedback).
 */
(function () {
  'use strict';

  var ICONS = {
    star: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.8l-5.2 2.7 1-5.8-4.2-4.1 5.8-.8L12 3.5z"/></svg>',
    'star-filled': '<svg class="is-filled" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.8l-5.2 2.7 1-5.8-4.2-4.1 5.8-.8L12 3.5z"/></svg>',
    note: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a8 8 0 0 1-8 8H8l-4 3v-5.5A8 8 0 1 1 21 12z"/></svg>',
    'note-filled': '<svg class="is-filled" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a8 8 0 0 1-8 8H8l-4 3v-5.5A8 8 0 1 1 21 12z"/></svg>',
    similar: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="12" r="2.5"/><circle cx="17" cy="6" r="2.5"/><circle cx="17" cy="18" r="2.5"/><path d="M8.3 10.8 14.7 7.2M8.3 13.2l6.4 3.6"/></svg>',
    wiki: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 3.5h6a4 4 0 0 1 4 4V21a3 3 0 0 0-3-3H2z"/><path d="M22 3.5h-6a4 4 0 0 0-4 4V21a3 3 0 0 1 3-3h7z"/></svg>',
    'thumb-up': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10v11M7 10l4-7a2 2 0 0 1 3.7 1.3L14 10h5.2a2 2 0 0 1 2 2.3l-1.4 7A2 2 0 0 1 17.8 21H7M7 10H4a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3"/></svg>',
    'thumb-up-filled': '<svg class="is-filled" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10v11M7 10l4-7a2 2 0 0 1 3.7 1.3L14 10h5.2a2 2 0 0 1 2 2.3l-1.4 7A2 2 0 0 1 17.8 21H7M7 10H4a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3"/></svg>',
    'thumb-down': '<svg viewBox="0 0 24 24" aria-hidden="true"><path transform="scale(1,-1) translate(0,-24)" d="M7 10v11M7 10l4-7a2 2 0 0 1 3.7 1.3L14 10h5.2a2 2 0 0 1 2 2.3l-1.4 7A2 2 0 0 1 17.8 21H7M7 10H4a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3"/></svg>',
    'thumb-down-filled': '<svg class="is-filled" viewBox="0 0 24 24" aria-hidden="true"><path transform="scale(1,-1) translate(0,-24)" d="M7 10v11M7 10l4-7a2 2 0 0 1 3.7 1.3L14 10h5.2a2 2 0 0 1 2 2.3l-1.4 7A2 2 0 0 1 17.8 21H7M7 10H4a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3"/></svg>'
  };

  function setIcon(btn, name) { btn.innerHTML = ICONS[name] || ''; }

  function btn(cls, icon, title) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'paper-action-btn ' + cls;
    b.title = title;
    b.setAttribute('aria-label', title);
    setIcon(b, icon);
    return b;
  }

  function link(cls, icon, title, href) {
    var a = document.createElement('a');
    a.className = 'paper-action-btn ' + cls;
    a.title = title;
    a.setAttribute('aria-label', title);
    a.href = href;
    setIcon(a, icon);
    return a;
  }

  // --- stars: same storage layout as the reports --------------------------------------
  function stateBase(d) { return 'arxiv-report:' + d.date + ':' + d.arxivId; }
  function isStarred(d) {
    try { return localStorage.getItem(stateBase(d) + ':starred') === '1'; } catch (_e) { return false; }
  }
  function snapshot(d) {
    return {
      url: d.url, arxivId: d.arxivId, titleEn: d.title, authors: d.authors,
      question: '', method: '', result: '', caveat: '',
      reportDate: d.date, reportHref: '/r/' + d.date + '#p' + d.number, number: d.number,
      status: 'submitted', statusLabel: '', statusVisible: false, methodTag: ''
    };
  }
  function toggleStar(d, b) {
    var on = !isStarred(d);
    try {
      if (on) {
        localStorage.setItem(stateBase(d) + ':starred', '1');
        if (!localStorage.getItem(stateBase(d) + ':paper')) {
          localStorage.setItem(stateBase(d) + ':paper', JSON.stringify(snapshot(d)));
        }
      } else {
        localStorage.removeItem(stateBase(d) + ':starred');
      }
    } catch (_e) {}
    syncStar(d, b);
  }
  function syncStar(d, b) {
    var on = isStarred(d);
    setIcon(b, on ? 'star-filled' : 'star');
    b.classList.toggle('is-active', on);
    b.title = on ? 'Remove star' : 'Mark as starred';
    b.setAttribute('aria-label', b.title);
  }

  // --- personal note ------------------------------------------------------------------
  function openNoteDialog(d, noteBtn, card) {
    var current = d.note || '';
    var backdrop = document.createElement('div');
    backdrop.className = 'note-dialog-backdrop';
    var dlg = document.createElement('div');
    dlg.className = 'note-dialog';
    var h = document.createElement('h4');
    h.textContent = 'Personal note · ' + d.pid;
    var ta = document.createElement('textarea');
    ta.value = current;
    ta.placeholder = 'Why this paper matters, what to check, who to tell…';
    var row = document.createElement('div');
    row.className = 'row';
    var cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancel';
    var del = document.createElement('button'); del.type = 'button'; del.textContent = 'Delete'; del.hidden = !current;
    var save = document.createElement('button'); save.type = 'button'; save.className = 'primary'; save.textContent = 'Save';
    function close() { backdrop.remove(); }
    function submit(text) {
      save.disabled = del.disabled = true;
      fetch('/note/' + encodeURIComponent(d.date) + '/' + encodeURIComponent(d.pid), {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: text})
      }).then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j.ok) throw new Error(j.error || 'failed');
          d.note = text.trim();
          setIcon(noteBtn, d.note ? 'note-filled' : 'note');
          noteBtn.classList.toggle('is-active', !!d.note);
          var p = card.querySelector('.paper-note');
          if (d.note) {
            if (!p) { p = document.createElement('p'); p.className = 'paper-note'; card.appendChild(p); }
            p.innerHTML = '<strong>Note:</strong> ';
            p.appendChild(document.createTextNode(d.note));
          } else if (p) { p.remove(); }
          close();
        })
        .catch(function (err) { save.disabled = del.disabled = false; alert('Saving the note failed: ' + err.message); });
    }
    cancel.addEventListener('click', close);
    del.addEventListener('click', function () { submit(''); });
    save.addEventListener('click', function () { submit(ta.value); });
    backdrop.addEventListener('click', function (e) { if (e.target === backdrop) close(); });
    row.appendChild(cancel); row.appendChild(del); row.appendChild(save);
    dlg.appendChild(h); dlg.appendChild(ta); dlg.appendChild(row);
    backdrop.appendChild(dlg);
    document.body.appendChild(backdrop);
    ta.focus();
  }

  // --- like / dislike -----------------------------------------------------------------
  function collapse(card, done) {
    var h = card.getBoundingClientRect().height;
    card.style.overflow = 'hidden';
    card.style.maxHeight = h + 'px';
    card.style.transition = 'max-height .45s ease, opacity .3s ease, margin .45s ease, padding .45s ease';
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        card.style.opacity = '0'; card.style.maxHeight = '0px';
        card.style.marginTop = '0'; card.style.marginBottom = '0';
        card.style.paddingTop = '0'; card.style.paddingBottom = '0';
      });
    });
    setTimeout(done, 480);
  }

  function build(row) {
    var d = {
      pid: row.dataset.pid, date: row.dataset.date, number: row.dataset.number,
      arxivId: row.dataset.arxivId || row.dataset.pid, url: row.dataset.url,
      title: row.dataset.title || '', authors: row.dataset.authors || '',
      verdict: row.dataset.verdict || '', note: row.dataset.note || '',
      full: row.dataset.full === '1'
    };
    var card = row.closest('.sanity-card') || row.parentElement;
    row.innerHTML = '';

    var star = btn('star-toggle-btn', 'star', 'Mark as starred');
    syncStar(d, star);
    star.addEventListener('click', function () { toggleStar(d, star); });
    row.appendChild(star);

    var note = btn('note-btn' + (d.note ? ' is-active' : ''), d.note ? 'note-filled' : 'note', 'Personal note');
    note.addEventListener('click', function () { openNoteDialog(d, note, card); });
    row.appendChild(note);

    row.appendChild(link('similar-link', 'similar', 'Similar papers', '/similar/' + encodeURIComponent(d.pid)));
    row.appendChild(link('wiki-link', 'wiki', 'Open wiki note', '/wiki/papers/' + encodeURIComponent(d.pid) + '.html'));

    var like = btn('like-btn', 'thumb-up', ''), dislike = btn('dislike-btn', 'thumb-down', '');
    function syncVerdict() {
      var liked = d.verdict === 'like', ignored = d.verdict === 'dislike';
      setIcon(like, liked ? 'thumb-up-filled' : 'thumb-up');
      like.classList.toggle('is-active', liked);
      like.title = liked ? 'Remove like' : (d.full ? 'Like (feeds recommendations)' : 'Like and promote to a full digest');
      like.setAttribute('aria-label', like.title);
      setIcon(dislike, ignored ? 'thumb-down-filled' : 'thumb-down');
      dislike.classList.toggle('is-active', ignored);
      dislike.title = ignored ? 'Follow this paper again' : 'Dismiss: not for me';
      dislike.setAttribute('aria-label', dislike.title);
      card.classList.toggle('is-liked', liked);
      card.classList.toggle('is-dismissed', ignored);
    }
    function send(kind, b) {
      var active = d.verdict === kind;
      var verdict = active ? 'clear' : kind;
      var willPromote = kind === 'like' && !active && !d.full;
      if (willPromote && !confirm('Promote ' + d.pid + ' to a full digest? This calls the LLM and takes about a minute.')) return;
      like.disabled = dislike.disabled = true;
      b.classList.add('is-busy');
      fetch('/feedback/' + encodeURIComponent(d.date) + '/' + encodeURIComponent(d.pid) + '/' + verdict, {method: 'POST'})
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j.ok) throw new Error(j.error || 'failed');
          d.verdict = verdict === 'clear' ? '' : verdict;
          if (j.promoted) d.full = true;
          like.disabled = dislike.disabled = false;
          b.classList.remove('is-busy');
          syncVerdict();
          var list = card.closest('.sanity-list');
          if (d.verdict === 'dislike' && list && list.dataset.kind === 'recommend') {
            collapse(card, function () { card.remove(); });
          }
        })
        .catch(function (err) {
          like.disabled = dislike.disabled = false;
          b.classList.remove('is-busy');
          alert('Feedback failed: ' + err.message);
        });
    }
    like.addEventListener('click', function () { send('like', like); });
    dislike.addEventListener('click', function () { send('dislike', dislike); });
    syncVerdict();
    row.appendChild(like);
    row.appendChild(dislike);
  }

  function init(root) {
    (root || document).querySelectorAll('.paper-actions[data-pid]:not([data-ready])').forEach(function (row) {
      row.dataset.ready = '1';
      build(row);
    });
  }

  document.addEventListener('DOMContentLoaded', function () { init(document); });
  // Results injected later (HTMX swaps, the Recommend button) get their buttons too.
  new MutationObserver(function (muts) {
    muts.forEach(function (m) {
      m.addedNodes.forEach(function (n) { if (n.nodeType === 1) init(n); });
    });
  }).observe(document.documentElement, {childList: true, subtree: true});
  window.initPaperActions = init;
})();
