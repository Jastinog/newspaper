/**
 * Section navigation — horizontal scroll with arrow buttons.
 *
 * Manages the section nav bar on the digest page:
 * arrow visibility, scroll-by-click, active item scroll-into-view.
 */
(function () {
    'use strict';

    var list = document.getElementById('sectionNavList');
    var leftBtn = document.getElementById('sectionNavLeft');
    var rightBtn = document.getElementById('sectionNavRight');
    if (!list) return;

    var SCROLL_AMOUNT = 200;

    /* Arrow visibility */
    function updateArrows() {
        var sl = list.scrollLeft;
        var maxScroll = list.scrollWidth - list.clientWidth;
        leftBtn.classList.toggle('hidden', sl <= 1);
        rightBtn.classList.toggle('hidden', sl >= maxScroll - 1);
    }
    list.addEventListener('scroll', updateArrows, { passive: true });
    window.addEventListener('resize', updateArrows);
    updateArrows();

    leftBtn.addEventListener('click', function () {
        list.scrollBy({ left: -SCROLL_AMOUNT, behavior: 'smooth' });
    });
    rightBtn.addEventListener('click', function () {
        list.scrollBy({ left: SCROLL_AMOUNT, behavior: 'smooth' });
    });

    /* Scroll active nav item into view */
    var activeItem = list.querySelector('.section-nav-item.active');
    if (activeItem) {
        activeItem.scrollIntoView({ inline: 'center', block: 'nearest' });
    }
})();
