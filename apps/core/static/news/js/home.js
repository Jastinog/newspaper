/**
 * Homepage digest module — replaces HTMX on the homepage.
 *
 * Two responsibilities:
 *   1. Pin/unpin a section — fetch the re-rendered regions as JSON and swap them
 *      in with a View Transition (smooth cross-fade, no layout flash).
 *   2. Live updates — subscribe to the site WebSocket (window.WS) and, when the
 *      harvester sections a new article, fetch its rendered card and animate it
 *      into the top of the matching section (FLIP), keeping the list capped.
 *
 * Card behaviour (share, summary) is bound via document-level delegation in
 * share.js / summary.js, so injected cards work with no re-init.
 */
(function () {
    'use strict';

    // Only run on the digest homepage.
    if (!document.getElementById('mainGrid')) return;

    var SECTION_CAP = 10;
    var ANIM_MS = 350;
    var reduceMotion = window.matchMedia
        && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // URLs live under a language prefix (/en, /uk, …); fetching without it just
    // triggers a LocaleMiddleware 302, so build prefixed paths.
    var LANG_PREFIX = document.body.dataset.langPrefix || '';

    // ── Pin / unpin ────────────────────────────────
    document.addEventListener('click', function (e) {
        var btn = e.target.closest('.pin-section-btn');
        if (!btn) return;
        e.preventDefault();
        var url = btn.dataset.pinUrl;
        if (!url) return;

        fetch(url, { method: 'POST', headers: { 'X-Requested-With': 'fetch' } })
            .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
            .then(function (data) {
                var apply = function () {
                    var pa = document.getElementById('pinnedArea');
                    var mg = document.getElementById('mainGrid');
                    var nav = document.getElementById('sectionNav');
                    if (pa) pa.innerHTML = data.pinnedArea;
                    if (mg) mg.innerHTML = data.mainGrid;
                    if (nav) nav.outerHTML = data.sectionNav;   // partial is the #sectionNav node
                    document.dispatchEvent(new CustomEvent('home:swapped'));
                };
                if (!reduceMotion && document.startViewTransition) {
                    document.startViewTransition(apply);
                } else {
                    apply();
                }
            })
            .catch(function () { /* leave the page as-is on failure */ });
    });

    // ── Live section updates ───────────────────────
    function sectionList(slug) {
        var block = document.querySelector('.digest-section[data-section-slug="' + slug + '"]');
        return block ? block.querySelector('.summary ul') : null;
    }

    function trim(ul) {
        while (ul.children.length > SECTION_CAP) {
            ul.removeChild(ul.lastElementChild);
        }
    }

    function insertCard(ul, html) {
        var li = document.createElement('li');
        li.innerHTML = html.trim();
        if (!li.firstElementChild) return;

        if (reduceMotion) {
            ul.insertBefore(li, ul.firstElementChild);
            trim(ul);
            return;
        }

        // FLIP: record current item positions, insert, then animate everyone
        // from their old spot to the new one so nothing jumps.
        var items = Array.prototype.slice.call(ul.children);
        var before = items.map(function (el) { return el.getBoundingClientRect().top; });

        ul.insertBefore(li, ul.firstElementChild);
        li.style.opacity = '0';

        items.forEach(function (el, i) {
            var dy = before[i] - el.getBoundingClientRect().top;
            if (dy) {
                el.style.transition = 'none';
                el.style.transform = 'translateY(' + dy + 'px)';
            }
        });

        requestAnimationFrame(function () {
            items.forEach(function (el) {
                el.style.transition = 'transform ' + ANIM_MS + 'ms cubic-bezier(.22,1,.36,1)';
                el.style.transform = '';
            });
            li.style.transition = 'opacity ' + ANIM_MS + 'ms ease';
            li.style.opacity = '1';
        });

        setTimeout(function () {
            items.forEach(function (el) { el.style.transition = ''; });
            trim(ul);
        }, ANIM_MS + 50);
    }

    function onArticle(msg) {
        var ul = sectionList(msg.section_slug);
        if (!ul) return;   // section not shown on this page
        if (ul.querySelector('[data-article-id="' + msg.article_id + '"]')) return;  // already here

        fetch(LANG_PREFIX + '/card/' + msg.article_id + '/')
            .then(function (r) {
                if (r.status === 204 || !r.ok) return null;
                return r.text();
            })
            .then(function (html) {
                if (!html) return;
                // Re-check de-dup: a burst could have inserted it meanwhile.
                if (ul.querySelector('[data-article-id="' + msg.article_id + '"]')) return;
                insertCard(ul, html);
            })
            .catch(function () { /* skip on error */ });
    }

    // ── WebSocket wiring ───────────────────────────
    if (window.WS) {
        var subscribe = function () { window.WS.send('home.subscribe'); };
        window.WS.on('ws.open', subscribe);   // fires on connect + every reconnect
        window.WS.on('home.article', onArticle);
        if (window.WS.isConnected()) subscribe();   // already open before this ran
    }
})();
