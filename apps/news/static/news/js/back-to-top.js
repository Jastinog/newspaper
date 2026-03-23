/**
 * Back-to-top button — shows after scrolling down 400px.
 */
(function () {
    'use strict';

    var btn = document.getElementById('backToTop');
    if (!btn) return;

    window.addEventListener('scroll', function () {
        btn.classList.toggle('visible', window.scrollY > 400);
    }, { passive: true });

    btn.addEventListener('click', function () {
        window.scrollTo({ top: 0 });
    });
})();
