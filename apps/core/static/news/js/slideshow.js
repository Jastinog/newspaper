/**
 * Image slideshow for digest items.
 * Items with multiple source-article images cycle through them
 * in 3 staggered streams so changes never overlap.
 */
(function () {
    'use strict';

    var INTERVAL = 13000; /* 10s stable + 3s crossfade */
    var STREAMS = 3;
    var timers = [];

    function advance(el) {
        var imgs = el.querySelectorAll('.item-hero-card__img');
        if (imgs.length < 2) return;

        var cur = -1;
        for (var i = 0; i < imgs.length; i++) {
            if (imgs[i].classList.contains('active')) { cur = i; break; }
        }
        var next = (cur + 1) % imgs.length;
        if (cur >= 0) imgs[cur].classList.remove('active');
        imgs[next].classList.add('active');

        var card = el.closest('.item-hero-card');
        if (card) {
            var blurs = card.querySelectorAll('.item-hero-card__blur');
            if (blurs.length === 2) {
                var top = blurs[1];
                var bot = blurs[0];
                if (top.classList.contains('active')) {
                    /* top is visible — set new image on bottom, fade top out */
                    bot.style.backgroundImage = "url('" + imgs[next].src + "')";
                    top.classList.remove('active');
                } else {
                    /* bottom is visible — set new image on top, fade top in */
                    top.style.backgroundImage = "url('" + imgs[next].src + "')";
                    top.classList.add('active');
                }
            }
        }
    }

    function clear() {
        timers.forEach(function (id) { clearTimeout(id); });
        timers = [];
    }

    function init() {
        clear();
        var slides = document.querySelectorAll('.item-slideshow');
        if (!slides.length) return;

        var groups = [[], [], []];
        slides.forEach(function (el, i) { groups[i % STREAMS].push(el); });

        groups.forEach(function (group, idx) {
            if (!group.length) return;
            var delay = INTERVAL + Math.round(idx * INTERVAL / STREAMS);

            function tick() {
                group.forEach(advance);
                timers.push(setTimeout(tick, INTERVAL));
            }
            timers.push(setTimeout(tick, delay));
        });
    }

    init();

    document.addEventListener('htmx:afterSettle', function (e) {
        if (e.detail.target.id === 'contentArea') init();
    });
})();
