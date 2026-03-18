/**
 * Deep dive feature.
 *
 * Marks digest items that have a ready deep dive, handles generation
 * requests via the WS client, and redirects when ready.
 *
 * Depends on: ws.js, orbit-animation.js
 */
(function () {
    'use strict';

    var pendingItemId = null;

    /** Add "deep-dive-ready" class to an item's <li>. */
    function markReady(itemId) {
        var link = document.querySelector(
            '.deep-dive-link[data-item-id="' + itemId + '"]'
        );
        if (link) link.closest('li').classList.add('deep-dive-ready');
    }

    /* ── WS handlers ─────────────────────────────────── */

    WS.on('init', function (msg) {
        var dives = msg.deep_dives || {};
        (dives.ready || []).forEach(markReady);
    });

    WS.on('deep_dive.ready', function (msg) {
        markReady(msg.item_id);
        if (msg.item_id === pendingItemId) {
            pendingItemId = null;
            window.location.href = msg.url;
        }
    });

    WS.on('deep_dive.error', function (msg) {
        if (msg.item_id === pendingItemId) {
            pendingItemId = null;
            OrbitAnimation.stop();
            alert('Помилка генерації: ' + msg.message);
        }
    });

    /* ── Click handlers ──────────────────────────────── */

    document.querySelectorAll('.deep-dive-link').forEach(function (link) {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            var itemId = parseInt(this.dataset.itemId, 10);
            var href = this.getAttribute('href');

            /* Already generated — navigate directly */
            if (this.closest('li').classList.contains('deep-dive-ready')) {
                window.location.href = href;
                return;
            }

            /* WS not available — fallback to HTTP */
            if (!WS.send('deep_dive.generate', { item_id: itemId })) {
                window.location.href = href;
                return;
            }

            pendingItemId = itemId;
            OrbitAnimation.start();
        });
    });
})();
