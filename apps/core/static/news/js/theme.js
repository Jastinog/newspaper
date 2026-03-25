/**
 * Theme toggle — light/dark mode.
 *
 * Reads preference from localStorage and applies it immediately.
 * Exposes toggleTheme() globally for the header button.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'newspaper-theme';

    function getTheme() {
        return localStorage.getItem(STORAGE_KEY) || 'light';
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        var icon = document.querySelector('.theme-icon');
        if (icon) icon.textContent = theme === 'dark' ? '\u2600' : '\u263E';
    }

    window.toggleTheme = function () {
        var next = getTheme() === 'dark' ? 'light' : 'dark';
        localStorage.setItem(STORAGE_KEY, next);
        applyTheme(next);
    };

    applyTheme(getTheme());
})();
