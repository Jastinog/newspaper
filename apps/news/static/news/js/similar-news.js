/**
 * Similar news — shows semantically similar digest items.
 *
 * Click the "≈" button on a digest item to fetch and display
 * related news items from the same or recent digests.
 */
(function () {
    'use strict';

    var API_PREFIX = '/api/digest-items/';
    var cache = {};

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }

    function clearChildren(node) {
        while (node.firstChild) node.removeChild(node.firstChild);
    }

    /** Find or create the panel container inside the item's <li>. */
    function getPanel(li, itemId) {
        var existing = li.querySelector('.similar-panel');
        if (existing) return existing;

        var panel = el('div', 'similar-panel');
        panel.setAttribute('data-similar-for', itemId);
        li.appendChild(panel);
        return panel;
    }

    function removePanel(li) {
        var panel = li.querySelector('.similar-panel');
        if (panel) panel.remove();
    }

    function renderLoading(panel) {
        clearChildren(panel);
        panel.appendChild(el('div', 'similar-panel-loading', '\u2026'));
    }

    function renderEmpty(panel) {
        clearChildren(panel);
        var body = document.body;
        var msg = body.dataset.similarEmpty || 'No similar news found';
        panel.appendChild(el('div', 'similar-panel-empty', msg));
    }

    function renderItems(panel, items) {
        clearChildren(panel);

        var body = document.body;
        var label = el('div', 'similar-panel-label', body.dataset.similarLabel || 'Similar news');
        panel.appendChild(label);

        var list = el('ul', 'similar-panel-list');

        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            var li = el('li', 'similar-panel-item');

            if (item.image_url) {
                var img = document.createElement('img');
                img.className = 'similar-panel-thumb';
                img.src = item.image_url;
                img.alt = '';
                img.loading = 'lazy';
                li.appendChild(img);
            }

            var bodyDiv = el('div', 'similar-panel-body');

            var link = el('a', 'similar-panel-topic', item.topic);
            link.href = item.deep_dive_url;
            bodyDiv.appendChild(link);

            var meta = el('div', 'similar-panel-meta', item.section + ' \u00b7 ' + item.date);
            bodyDiv.appendChild(meta);

            li.appendChild(bodyDiv);
            list.appendChild(li);
        }

        panel.appendChild(list);
    }

    function fetchSimilar(itemId, panel) {
        if (cache[itemId]) {
            var items = cache[itemId];
            if (items.length === 0) renderEmpty(panel);
            else renderItems(panel, items);
            return;
        }

        renderLoading(panel);

        fetch(API_PREFIX + itemId + '/similar/')
            .then(function (r) {
                if (!r.ok) throw new Error(r.status);
                return r.json();
            })
            .then(function (data) {
                var items = data.items || [];
                cache[itemId] = items;
                if (items.length === 0) renderEmpty(panel);
                else renderItems(panel, items);
            })
            .catch(function () {
                clearChildren(panel);
                panel.appendChild(el('div', 'similar-panel-empty', '\u2717 Error'));
            });
    }

    /* ── Click handler ───────────────────────────────── */

    document.addEventListener('click', function (e) {
        var btn = e.target.closest('.similar-btn');
        if (!btn) return;

        e.preventDefault();
        var itemId = btn.dataset.itemId;
        var li = btn.closest('li');
        if (!li) return;

        // Toggle: if panel exists, remove it
        if (btn.classList.contains('active')) {
            btn.classList.remove('active');
            removePanel(li);
            return;
        }

        // Close any other open panels
        document.querySelectorAll('.similar-btn.active').forEach(function (other) {
            other.classList.remove('active');
            var otherLi = other.closest('li');
            if (otherLi) removePanel(otherLi);
        });

        btn.classList.add('active');
        var panel = getPanel(li, itemId);
        fetchSimilar(itemId, panel);
    });
})();
