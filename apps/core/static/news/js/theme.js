/**
 * Theme manager — 10 newspaper themes, each in a light and a dark variant.
 *
 * Two independent preferences are stored in localStorage:
 *   newspaper-theme   -> theme family id (see THEMES below)
 *   newspaper-scheme  -> 'light' | 'dark'
 *
 * They map to two attributes on <html>: data-theme and data-scheme, which the
 * CSS custom properties in base.css are keyed on. The FOUC script in base.html
 * applies both before first paint — keep the id list / migration map in sync.
 *
 * Public API (called from the header button + modal):
 *   window.openThemeModal()  — open the picker
 *   window.setTheme(id)      — choose a theme family
 *   window.setScheme(scheme) — choose 'light' | 'dark'
 */
(function () {
    'use strict';

    var THEME_KEY = 'newspaper-theme';
    var SCHEME_KEY = 'newspaper-scheme';

    /* Theme families, in display order. Names are proper nouns (not translated). */
    var THEMES = [
        { id: 'broadsheet', name: 'Broadsheet' },
        { id: 'gazette',    name: 'Gazette' },
        { id: 'sepia',      name: 'Sepia' },
        { id: 'ink',        name: 'Ink' },
        { id: 'forest',     name: 'Forest' },
        { id: 'crimson',    name: 'Crimson' },
        { id: 'ocean',      name: 'Ocean' },
        { id: 'plum',       name: 'Plum' },
        { id: 'amber',      name: 'Amber' },
        { id: 'slate',      name: 'Slate' },
        { id: 'rose',       name: 'Rose' },
        { id: 'sky',        name: 'Sky' },
        { id: 'indigo',     name: 'Indigo' },
        { id: 'mint',       name: 'Mint' },
        { id: 'olive',      name: 'Olive' },
        { id: 'rust',       name: 'Rust' },
        { id: 'wine',       name: 'Wine' },
        { id: 'graphite',   name: 'Graphite' }
    ];
    var IDS = {};
    THEMES.forEach(function (t) { IDS[t.id] = t; });

    /* Legacy single-value ids -> [theme, scheme]. Applied once, then persisted. */
    var MIGRATION = {
        light:    ['broadsheet', 'light'],
        dark:     ['amber', 'dark'],
        evening:  ['amber', 'dark'],
        midnight: ['slate', 'dark']
    };

    var DEFAULT_THEME = 'broadsheet';
    var root = document.documentElement;

    /* ── Preference resolution ─────────────────────────────── */

    function migrate() {
        var t = localStorage.getItem(THEME_KEY);
        if (t && MIGRATION[t]) {
            var m = MIGRATION[t];
            localStorage.setItem(THEME_KEY, m[0]);
            if (!localStorage.getItem(SCHEME_KEY)) {
                localStorage.setItem(SCHEME_KEY, m[1]);
            }
        }
    }

    function getTheme() {
        var t = localStorage.getItem(THEME_KEY);
        return IDS[t] ? t : DEFAULT_THEME;
    }

    function getScheme() {
        var s = localStorage.getItem(SCHEME_KEY);
        if (s === 'light' || s === 'dark') return s;
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }
        return 'light';
    }

    /* ── Applying ──────────────────────────────────────────── */

    function apply() {
        var theme = getTheme();
        var scheme = getScheme();
        root.setAttribute('data-theme', theme);
        root.setAttribute('data-scheme', scheme);
        updateButton(theme);
        updateModal(theme, scheme);
    }

    function updateButton(theme) {
        // The label stays a fixed "Theme"; the swatch (.theme-btn-dot) tracks
        // the palette via CSS var(--accent). Surface the active family name as
        // the button's tooltip for context.
        var btn = document.getElementById('themeBtn');
        if (btn && IDS[theme]) btn.title = IDS[theme].name;
    }

    window.setTheme = function (id) {
        if (!IDS[id]) return;
        localStorage.setItem(THEME_KEY, id);
        apply();
    };

    window.setScheme = function (scheme) {
        if (scheme !== 'light' && scheme !== 'dark') return;
        localStorage.setItem(SCHEME_KEY, scheme);
        apply();
    };

    /* ── Modal ─────────────────────────────────────────────── */

    var overlay = null;

    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text != null) e.textContent = text;
        return e;
    }

    function label(key, fallback) {
        var btn = document.getElementById('themeBtn');
        return (btn && btn.getAttribute('data-l-' + key)) || fallback;
    }

    function closeModal() {
        if (overlay) overlay.remove();
        overlay = null;
        document.removeEventListener('keydown', onKey);
    }

    function onKey(e) {
        if (e.key === 'Escape') closeModal();
    }

    function buildCard(theme, scheme) {
        var card = el('button', 'theme-card');
        card.type = 'button';
        card.setAttribute('data-theme-id', theme.id);
        // The card previews its own palette by carrying the attributes the
        // CSS variables are keyed on; scheme follows the current selection.
        card.setAttribute('data-theme', theme.id);
        card.setAttribute('data-scheme', scheme);

        // Preview is a miniature front page rendered entirely in the theme's
        // own palette (bg / headline / body / accent / rules).
        var preview = el('span', 'tp-preview');
        preview.setAttribute('aria-hidden', 'true');

        var plate = el('span', 'tp-plate');
        plate.appendChild(el('span', 'tp-plate-rule'));
        plate.appendChild(el('span', 'tp-plate-word'));
        plate.appendChild(el('span', 'tp-plate-rule'));
        preview.appendChild(plate);

        preview.appendChild(el('span', 'tp-hr'));
        preview.appendChild(el('span', 'tp-headline'));

        var lede = el('span', 'tp-lede');
        lede.appendChild(el('span', 'tp-fig'));
        var lines = el('span', 'tp-lines');
        lines.appendChild(el('span', 'tp-line'));
        lines.appendChild(el('span', 'tp-line'));
        lines.appendChild(el('span', 'tp-line'));
        lede.appendChild(lines);
        preview.appendChild(lede);

        preview.appendChild(el('span', 'tp-line tp-line-wide'));
        preview.appendChild(el('span', 'tp-line tp-line-wide'));
        card.appendChild(preview);

        var foot = el('span', 'theme-card-foot');
        foot.appendChild(el('span', 'theme-card-dot'));
        foot.appendChild(el('span', 'theme-card-name', theme.name));
        foot.appendChild(el('span', 'theme-card-check', '✓'));
        card.appendChild(foot);

        card.onclick = function () {
            window.setTheme(theme.id);
        };
        return card;
    }

    function buildModal() {
        var scheme = getScheme();

        overlay = el('div', 'theme-modal-overlay');
        var modal = el('div', 'theme-modal');

        var head = el('div', 'theme-modal-head');
        head.appendChild(el('h3', 'theme-modal-title', label('appearance', 'Appearance')));
        var close = el('button', 'theme-modal-close', '✕');
        close.type = 'button';
        close.setAttribute('aria-label', label('close', 'Close'));
        close.onclick = closeModal;
        head.appendChild(close);
        modal.appendChild(head);

        /* light / dark segmented toggle with a sliding thumb */
        var seg = el('div', 'theme-scheme-toggle');
        seg.setAttribute('role', 'group');
        seg.appendChild(el('span', 'theme-scheme-thumb'));
        ['light', 'dark'].forEach(function (s) {
            var b = el('button', 'theme-scheme-btn', label(s, s === 'light' ? 'Light' : 'Dark'));
            b.type = 'button';
            b.setAttribute('data-scheme-value', s);
            b.onclick = function () { window.setScheme(s); };
            seg.appendChild(b);
        });
        modal.appendChild(seg);

        /* theme grid */
        var grid = el('div', 'theme-grid');
        THEMES.forEach(function (t) { grid.appendChild(buildCard(t, scheme)); });
        modal.appendChild(grid);

        overlay.appendChild(modal);
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) closeModal();
        });
        document.addEventListener('keydown', onKey);
        document.body.appendChild(overlay);

        updateModal(getTheme(), scheme);
    }

    function updateModal(theme, scheme) {
        if (!overlay) return;
        var cards = overlay.querySelectorAll('.theme-card');
        for (var i = 0; i < cards.length; i++) {
            var c = cards[i];
            c.setAttribute('data-scheme', scheme); // flip previews with the toggle
            c.classList.toggle('active', c.getAttribute('data-theme-id') === theme);
        }
        var toggle = overlay.querySelector('.theme-scheme-toggle');
        if (toggle) toggle.setAttribute('data-active', scheme);
        var segBtns = overlay.querySelectorAll('.theme-scheme-btn');
        for (var j = 0; j < segBtns.length; j++) {
            var s = segBtns[j];
            s.classList.toggle('active', s.getAttribute('data-scheme-value') === scheme);
        }
    }

    window.openThemeModal = function () {
        if (overlay) { closeModal(); return; }
        buildModal();
    };

    /* ── Init ──────────────────────────────────────────────── */
    migrate();
    apply();
})();
