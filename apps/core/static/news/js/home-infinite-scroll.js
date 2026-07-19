/*
 * Home feed infinite scroll — pre-fetch the next page before the user hits
 * the bottom.
 *
 * htmx's built-in `intersect` trigger only understands `root` and `threshold`;
 * it silently ignores `root-margin`, so the sentinel only fires once it is
 * actually in the viewport. We drive the intersection ourselves with a real
 * rootMargin so the next page loads while the sentinel is still ~1200px below
 * the fold, then hand off to htmx via a custom `loadmore` event.
 */
(function () {
    if (!('IntersectionObserver' in window) || !window.htmx) return;

    var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            observer.unobserve(entry.target);
            window.htmx.trigger(entry.target, 'loadmore');
        });
    }, { rootMargin: '1200px 0px' });

    function attach() {
        document.querySelectorAll('.home-more').forEach(function (el) {
            observer.observe(el);
        });
    }

    document.addEventListener('DOMContentLoaded', attach);
    // A swap replaces the old sentinel with a fresh one (or the next page's).
    document.body.addEventListener('htmx:afterSwap', attach);
})();
