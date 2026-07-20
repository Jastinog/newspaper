/**
 * Topic navigation — horizontal scroll with arrow buttons and wheel support.
 *
 * The topic bar is a single scrollable row with the native scrollbar hidden, so
 * mouse users have no built-in way to reach the off-screen topics. This adds
 * ‹ › buttons (shown only when that direction can scroll), turns a vertical
 * mouse wheel into horizontal scroll, and centres the active topic on load.
 * Re-initialises after HTMX swaps (the whole nav re-renders on hx-boost nav).
 */
(function () {
    'use strict';

    var SCROLL_AMOUNT = 240;
    var list = null;
    var leftBtn = null;
    var rightBtn = null;

    function updateArrows() {
        if (!list || !leftBtn || !rightBtn) return;
        var sl = list.scrollLeft;
        var maxScroll = list.scrollWidth - list.clientWidth;
        var overflowing = maxScroll > 1;
        leftBtn.classList.toggle('hidden', !overflowing || sl <= 1);
        rightBtn.classList.toggle('hidden', !overflowing || sl >= maxScroll - 1);
    }

    window.addEventListener('resize', updateArrows);

    function onWheel(e) {
        // Only hijack a predominantly-vertical wheel (trackpads already scroll
        // horizontally on their own via deltaX).
        if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
        var maxScroll = list.scrollWidth - list.clientWidth;
        if (maxScroll <= 1) return;
        var atStart = e.deltaY < 0 && list.scrollLeft <= 0;
        var atEnd = e.deltaY > 0 && list.scrollLeft >= maxScroll - 1;
        if (atStart || atEnd) return;  // let the page scroll at the extremes
        e.preventDefault();
        list.scrollLeft += e.deltaY;
    }

    function initTopicNav() {
        list = document.getElementById('topicNavList');
        leftBtn = document.getElementById('topicNavLeft');
        rightBtn = document.getElementById('topicNavRight');
        if (!list) return;

        list.addEventListener('scroll', updateArrows, { passive: true });
        list.addEventListener('wheel', onWheel, { passive: false });

        if (leftBtn) {
            leftBtn.onclick = function () {
                list.scrollBy({ left: -SCROLL_AMOUNT, behavior: 'smooth' });
            };
        }
        if (rightBtn) {
            rightBtn.onclick = function () {
                list.scrollBy({ left: SCROLL_AMOUNT, behavior: 'smooth' });
            };
        }

        var active = list.querySelector('.topic-nav-item.active');
        if (active) {
            active.scrollIntoView({ inline: 'center', block: 'nearest' });
        }

        updateArrows();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTopicNav);
    } else {
        initTopicNav();
    }

    // hx-boost swaps the whole body, re-rendering the nav each navigation.
    document.addEventListener('htmx:afterSwap', initTopicNav);
})();
