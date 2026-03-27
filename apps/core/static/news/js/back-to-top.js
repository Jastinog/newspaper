/**
 * Back-to-top button — shows after scrolling down 400px.
 * Re-binds the click handler after HTMX content swaps.
 */
(function () {
    'use strict';

    var btn = null;

    function onScroll() {
        if (btn) btn.classList.toggle('visible', window.scrollY > 400);
    }

    window.addEventListener('scroll', onScroll, { passive: true });

    function initBackToTop() {
        btn = document.getElementById('backToTop');
        if (!btn) return;
        btn.onclick = function () { window.scrollTo({ top: 0 }); };
    }

    initBackToTop();

    document.addEventListener('htmx:afterSwap', function (evt) {
        if (evt.detail.target.id === 'contentArea') {
            initBackToTop();
        }
    });
})();
