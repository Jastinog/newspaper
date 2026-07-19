/**
 * Curator "⋯" menu on home-feed cards (staff only).
 *
 * The menu markup is rendered by the server only for staff, so this script is a
 * no-op for regular visitors. Its one action — "Hide this source" — POSTs to the
 * hide_feed endpoint, then removes every card of that feed from the page.
 *
 * Labels come from window.ARTICLE_MENU_I18N (localized server-side); each lookup
 * falls back to English. CSRF token is exposed as window.NEWS_CSRF.
 *
 * Click handling is delegated on document so it survives HTMX infinite-scroll swaps.
 */
(function () {
    'use strict';

    var I18N = window.ARTICLE_MENU_I18N || {};

    // Visibility is driven purely by [aria-expanded] in CSS, so the only state
    // to flip is the button's attribute — the popover follows via an adjacent-
    // sibling rule. Only one menu is ever open at a time.
    function closeAllMenus() {
        var open = document.querySelectorAll('.home-item-menu-btn[aria-expanded="true"]');
        for (var i = 0; i < open.length; i++) open[i].setAttribute('aria-expanded', 'false');
    }

    function toggleMenu(btn) {
        var wasOpen = btn.getAttribute('aria-expanded') === 'true';
        closeAllMenus();
        if (!wasOpen) btn.setAttribute('aria-expanded', 'true');
    }

    function removeFeedCards(feedId) {
        var cards = document.querySelectorAll('.home-item[data-feed-id="' + feedId + '"]');
        for (var i = 0; i < cards.length; i++) cards[i].remove();
    }

    function hideFeed(actionBtn) {
        var card = actionBtn.closest('.home-item[data-feed-id]');
        if (!card) return;
        var feedId = card.dataset.feedId;
        var title = card.dataset.feedTitle || '';
        var url = actionBtn.dataset.hideUrl;
        if (!feedId || !url) return;

        var prompt = (I18N.confirmHide || 'Hide all news from "{title}"?').replace('{title}', title);
        if (!window.confirm(prompt)) return;

        actionBtn.disabled = true;
        fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': window.NEWS_CSRF || '', 'X-Requested-With': 'XMLHttpRequest' },
            credentials: 'same-origin'
        }).then(function (resp) {
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        }).then(function () {
            closeAllMenus();
            removeFeedCards(feedId);
        }).catch(function () {
            actionBtn.disabled = false;
            window.alert(I18N.hideError || 'Could not hide this source. Please try again.');
        });
    }

    document.addEventListener('click', function (e) {
        var trigger = e.target.closest('[data-menu-trigger]');
        if (trigger) {
            e.preventDefault();
            toggleMenu(trigger);
            return;
        }
        var action = e.target.closest('[data-hide-feed]');
        if (action) {
            e.preventDefault();
            hideFeed(action);
            return;
        }
        // Click anywhere else closes any open menu.
        closeAllMenus();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeAllMenus();
    });
})();
