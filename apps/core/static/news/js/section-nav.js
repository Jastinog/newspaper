/**
 * Section navigation — horizontal scroll with arrow buttons.
 *
 * Manages the section nav bar on the digest page:
 * arrow visibility, scroll-by-click, active item scroll-into-view.
 * Re-initialises after HTMX content swaps.
 */
(function () {
    'use strict';

    var SCROLL_AMOUNT = 200;
    var list = null;
    var leftBtn = null;
    var rightBtn = null;

    function updateArrows() {
        if (!list || !leftBtn || !rightBtn) return;
        var sl = list.scrollLeft;
        var maxScroll = list.scrollWidth - list.clientWidth;
        leftBtn.classList.toggle('hidden', sl <= 1);
        rightBtn.classList.toggle('hidden', sl >= maxScroll - 1);
    }

    // Register window resize once — it updates whichever list/buttons are current
    window.addEventListener('resize', updateArrows);

    function initSectionNav() {
        list = document.getElementById('sectionNavList');
        leftBtn = document.getElementById('sectionNavLeft');
        rightBtn = document.getElementById('sectionNavRight');
        if (!list || !leftBtn || !rightBtn) return;

        list.addEventListener('scroll', updateArrows, { passive: true });
        updateArrows();

        leftBtn.onclick = function () {
            list.scrollBy({ left: -SCROLL_AMOUNT, behavior: 'smooth' });
        };
        rightBtn.onclick = function () {
            list.scrollBy({ left: SCROLL_AMOUNT, behavior: 'smooth' });
        };

        var activeItem = list.querySelector('.section-nav-item.active');
        if (activeItem) {
            activeItem.scrollIntoView({ inline: 'center', block: 'nearest' });
        }
    }

    initSectionNav();

    document.addEventListener('htmx:afterSwap', function (evt) {
        var id = evt.detail.target.id;
        if (id === 'sectionNav' || id === 'contentArea') {
            initSectionNav();
        }
    });
})();
