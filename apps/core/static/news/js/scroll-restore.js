/**
 * Scroll-position restoration — remembers scroll Y per URL in
 * sessionStorage and restores it when the user returns to the page.
 * Works with both full-page navigations and HTMX content swaps.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'newspaper-scroll';
    var MAX_ENTRIES = 30;
    var SAVE_DELAY = 200;
    var timer;

    function currentUrl() {
        return location.pathname + location.search;
    }

    function readMap() {
        try {
            return JSON.parse(sessionStorage.getItem(STORAGE_KEY)) || {};
        } catch (e) {
            return {};
        }
    }

    function save() {
        var map = readMap();
        map[currentUrl()] = window.scrollY;
        var keys = Object.keys(map);
        while (keys.length > MAX_ENTRIES) { delete map[keys.shift()]; }
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(map));
    }

    function restore() {
        var y = readMap()[currentUrl()];
        if (y > 0) {
            requestAnimationFrame(function () {
                window.scrollTo(0, y);
            });
        }
    }

    function delayedRestore() {
        setTimeout(restore, 50);
    }

    window.addEventListener('scroll', function () {
        clearTimeout(timer);
        timer = setTimeout(save, SAVE_DELAY);
    }, { passive: true });

    window.addEventListener('beforeunload', save);
    window.addEventListener('DOMContentLoaded', delayedRestore);

    window.addEventListener('pageshow', function (e) {
        if (e.persisted) restore();
    });

    document.addEventListener('htmx:beforeRequest', save);
    document.addEventListener('htmx:afterSettle', delayedRestore);
})();
