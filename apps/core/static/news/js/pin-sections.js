/**
 * Pin / unpin digest sections.
 *
 * Stores pinned section slugs in a cookie so the server can
 * render pinned sections separately on the next page load.
 */
(function () {
    'use strict';

    var COOKIE_NAME = 'pinned_sections';
    var MAX_AGE = 365 * 24 * 60 * 60; // 1 year

    function getPinned() {
        var match = document.cookie.match(new RegExp('(?:^|; )' + COOKIE_NAME + '=([^;]*)'));
        if (!match || !match[1]) return [];
        return match[1].split(',').filter(Boolean);
    }

    function savePinned(slugs) {
        var value = slugs.join(',');
        document.cookie = COOKIE_NAME + '=' + value +
            '; path=/; max-age=' + MAX_AGE + '; SameSite=Lax';
    }

    function togglePin(slug) {
        var pinned = getPinned();
        var idx = pinned.indexOf(slug);
        if (idx === -1) {
            pinned.push(slug);
        } else {
            pinned.splice(idx, 1);
        }
        savePinned(pinned);
        location.reload();
    }

    document.addEventListener('click', function (e) {
        var btn = e.target.closest('.pin-section-btn');
        if (!btn) return;
        e.preventDefault();
        var slug = btn.getAttribute('data-section-slug');
        if (slug) togglePin(slug);
    });
})();
