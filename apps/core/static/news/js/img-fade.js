/**
 * Progressive image reveal — fade card images in when they finish loading,
 * instead of a hard pop-in.
 *
 * Deferral itself is native (`loading="lazy"` keeps off-screen images from being
 * fetched until they near the viewport); this only smooths their appearance.
 * Gated on the `img-fade` class added below, so with JS disabled the CSS never
 * hides anything and every image stays visible.
 */
(function () {
    'use strict';

    var SEL = '.home-item-thumb img, .article-row-visual img, .result-image';

    document.documentElement.classList.add('img-fade');

    function reveal(img) { img.classList.add('is-loaded'); }

    // `load`/`error` don't bubble, so listen in the capture phase — this catches
    // every matching image, including lazy ones and cards injected later
    // (infinite scroll, live WS insert), with a single listener.
    document.addEventListener('load', function (e) {
        var t = e.target;
        if (t.tagName === 'IMG' && t.matches(SEL)) reveal(t);
    }, true);
    document.addEventListener('error', function (e) {
        var t = e.target;
        if (t.tagName === 'IMG' && t.matches(SEL)) reveal(t);  // don't leave broken imgs hidden
    }, true);

    // Images already decoded (cached, or finished before this ran) fire no load
    // event — reveal them directly. Exposed so freshly-inserted cards can rescan.
    function revealComplete(root) {
        (root || document).querySelectorAll(SEL).forEach(function (img) {
            if (img.complete && img.naturalWidth > 0) reveal(img);
        });
    }
    window.ImgFade = revealComplete;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { revealComplete(); });
    } else {
        revealComplete();
    }
})();
