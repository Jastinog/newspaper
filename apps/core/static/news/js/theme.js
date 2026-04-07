/**
 * Theme picker — 4 newspaper themes.
 *
 * Reads preference from localStorage, migrates legacy values,
 * and applies immediately. Exposes setTheme() for the header picker.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'newspaper-theme';

    /* theme-id -> colour scheme (must match the FOUC script in base.html) */
    var SCHEME = {
        broadsheet: 'light',
        gazette:    'light',
        evening:    'dark',
        midnight:   'dark'
    };

    /* legacy values stored as "light" / "dark" before the 4-theme expansion */
    var MIGRATION = { light: 'broadsheet', dark: 'evening' };

    function getTheme() {
        var stored = localStorage.getItem(STORAGE_KEY);
        if (MIGRATION[stored]) {
            stored = MIGRATION[stored];
            localStorage.setItem(STORAGE_KEY, stored);
        }
        if (!(stored in SCHEME)) {
            if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
                stored = 'evening';
            } else {
                stored = 'broadsheet';
            }
        }
        return stored;
    }

    function applyTheme(id) {
        document.documentElement.setAttribute('data-theme', id);
        document.documentElement.setAttribute('data-scheme', SCHEME[id]);

        var buttons = document.querySelectorAll('.theme-picker button');
        for (var i = 0; i < buttons.length; i++) {
            var btn = buttons[i];
            if (btn.getAttribute('data-theme-id') === id) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        }
    }

    window.setTheme = function (id) {
        if (!(id in SCHEME)) return;
        localStorage.setItem(STORAGE_KEY, id);
        applyTheme(id);
    };

    applyTheme(getTheme());
})();
