/**
 * Card "Share" button — native share sheet where available, clipboard fallback.
 *
 * Delegated so it survives HTMX infinite-scroll / digest swaps. A button carries
 * `data-url` (a site-relative article URL) and `data-title`. On clipboard
 * fallback the icon briefly flips to a checkmark for feedback.
 */
(function () {
    'use strict';

    document.addEventListener('click', function (e) {
        var btn = e.target.closest('.share-btn');
        if (!btn) return;
        e.preventDefault();

        var raw = btn.dataset.url || '';
        var url = /^https?:\/\//.test(raw) ? raw : window.location.origin + raw;
        var title = btn.dataset.title || document.title;

        if (navigator.share) {
            navigator.share({ title: title, url: url }).catch(function () {});
            return;
        }
        if (navigator.clipboard) {
            navigator.clipboard.writeText(url).then(function () {
                var icon = btn.querySelector('i');
                if (!icon) return;
                var orig = icon.className;
                icon.className = 'fas fa-check';
                setTimeout(function () { icon.className = orig; }, 2000);
            }).catch(function () {});
        }
    });
})();
