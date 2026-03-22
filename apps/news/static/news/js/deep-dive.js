/**
 * Deep dive feature — supports multiple concurrent generations.
 *
 * Shows progress inline on the digest card: the current step label
 * in place of the "details →" link.
 *
 * Depends on: ws.js
 */
(function () {
    'use strict';

    /* ── Helpers ──────────────────────────────────────── */

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }

    function bodyData(key, fallback) {
        return document.body.dataset[key] || fallback;
    }

    /* ── State ────────────────────────────────────────── */

    var pending = {};

    var STEP_ICONS = {
        queries:   '\u2049',
        embedding: '\u27A4',
        search:    '\u25CE',
        grouping:  '\u25A6',
        synthesis: '\u270E',
        saving:    '\u2713',
    };

    function hasPending(itemId) {
        return pending.hasOwnProperty(itemId);
    }

    /** Find the <li> and hint link for a given item id. */
    function getCardEls(itemId) {
        var link = document.querySelector(
            '.deep-dive-link[data-item-id="' + itemId + '"]'
        );
        var li = link ? link.closest('li') : null;
        return { link: link, li: li };
    }

    /** Add "deep-dive-ready" class to an item's <li>. */
    function markReady(itemId) {
        var c = getCardEls(itemId);
        if (c.li) c.li.classList.add('deep-dive-ready');
    }

    /* ── Inline progress rendering ───────────────────── */

    /** Inject step label into the card. */
    function injectProgress(itemId) {
        var c = getCardEls(itemId);
        if (!c.li) return;

        // Hide the original link, show step label
        if (c.link && !c.link._ddHidden) {
            c.link._ddHidden = true;
            c.link.style.display = 'none';
            var step = el('span', 'dd-inline-step', '0/6');
            step.setAttribute('data-dd-step', itemId);
            c.link.parentNode.insertBefore(step, c.link.nextSibling);
        }
    }

    /** Update step label on the card. */
    function updateProgress(itemId, p) {
        var c = getCardEls(itemId);
        if (!c.li) return;

        // Update step label
        var stepEl = c.li.querySelector('[data-dd-step="' + itemId + '"]');
        if (stepEl) {
            var icon = p.stepId ? (STEP_ICONS[p.stepId] || '') : '';
            var label = p.label || p.stepId || '';
            var counter = (p.step || 0) + '/' + (p.totalSteps || 6);
            stepEl.textContent = (icon ? icon + ' ' : '') + label + ' ' + counter;
        }
    }

    /** Remove inline progress, restore the link. */
    function cleanupProgress(itemId) {
        var c = getCardEls(itemId);
        if (!c.li) return;

        var stepEl = c.li.querySelector('[data-dd-step="' + itemId + '"]');
        if (stepEl) stepEl.remove();

        if (c.link) {
            c.link.style.display = '';
            c.link._ddHidden = false;
        }
    }

    /** Show error state on the card. */
    function showError(itemId, message) {
        var c = getCardEls(itemId);
        if (!c.li) return;

        var stepEl = c.li.querySelector('[data-dd-step="' + itemId + '"]');
        if (stepEl) {
            stepEl.className = 'dd-inline-step dd-error';
            stepEl.textContent = '\u2717 ' + (message || bodyData('errorGeneration', 'Error'));
        }
    }

    /* ── Modal ─────────────────────────────────────────── */

    function img(className, src) {
        var node = el('img', className);
        node.src = src;
        node.alt = '';
        return node;
    }

    function showModal(p, url) {
        var overlay = el('div', 'dd-modal-overlay');
        var modal = el('div', 'dd-modal');

        if (p.imageUrl) {
            modal.appendChild(img('dd-modal-image', p.imageUrl));
        }

        modal.appendChild(el('div', 'dd-modal-check', '\u2713'));
        modal.appendChild(el('div', 'dd-modal-title', bodyData('ddReady', 'Deep dive ready')));
        modal.appendChild(el('div', 'dd-modal-topic', p.topic));

        if (p.summary) {
            modal.appendChild(el('div', 'dd-modal-summary', p.summary));
        }

        var actions = el('div', 'dd-modal-actions');

        var readBtn = el('a', 'dd-modal-btn dd-modal-btn-primary', bodyData('ddRead', 'Read'));
        readBtn.href = url;
        actions.appendChild(readBtn);

        var closeBtn = el('button', 'dd-modal-btn dd-modal-btn-secondary', bodyData('ddClose', 'Close'));
        closeBtn.onclick = function () { overlay.remove(); };
        actions.appendChild(closeBtn);

        modal.appendChild(actions);
        overlay.appendChild(modal);

        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) overlay.remove();
        });

        document.body.appendChild(overlay);
    }

    /* ── WS handlers ─────────────────────────────────── */

    WS.on('deep_dive.state', function (msg) {
        var readyIds = msg.ready || [];
        readyIds.forEach(markReady);

        var keys = Object.keys(pending);
        for (var i = 0; i < keys.length; i++) {
            var p = pending[keys[i]];
            if (!p.url && !p.error) {
                var id = parseInt(keys[i], 10);
                if (readyIds.indexOf(id) !== -1) {
                    p.url = '/deep-dive/' + id + '/';
                    cleanupProgress(id);
                    markReady(id);
                } else {
                    WS.send('deep_dive.generate', { item_id: id });
                }
            }
        }
    });

    WS.on('deep_dive.progress', function (msg) {
        if (!hasPending(msg.item_id)) return;
        var p = pending[msg.item_id];
        p.step = msg.step;
        p.totalSteps = msg.total_steps;
        p.stepId = msg.step_id;
        p.label = msg.label;
        updateProgress(msg.item_id, p);
    });

    WS.on('deep_dive.ready', function (msg) {
        markReady(msg.item_id);

        if (!hasPending(msg.item_id)) return;
        var p = pending[msg.item_id];
        p.url = msg.url;
        p.step = p.totalSteps || 6;

        cleanupProgress(msg.item_id);
        showModal(p, msg.url);

        delete pending[msg.item_id];
    });

    WS.on('deep_dive.error', function (msg) {
        if (!hasPending(msg.item_id)) return;
        var p = pending[msg.item_id];
        p.error = msg.message || bodyData('errorGeneration', 'Error');

        showError(msg.item_id, p.error);

        setTimeout(function () {
            cleanupProgress(msg.item_id);
            delete pending[msg.item_id];
        }, 5000);
    });

    /* ── Click handlers ──────────────────────────────── */

    document.querySelectorAll('.deep-dive-link').forEach(function (link) {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            var itemId = parseInt(this.dataset.itemId, 10);
            var href = this.getAttribute('href');
            var li = this.closest('li');

            if (li.classList.contains('deep-dive-ready')) {
                window.location.href = href;
                return;
            }

            if (hasPending(itemId)) return;

            if (!WS.send('deep_dive.generate', { item_id: itemId })) {
                window.location.href = href;
                return;
            }

            var topicEl = li.querySelector('.item-topic');
            var summaryEl = li.querySelector('.item-summary');
            var imageEl = li.querySelector('.item-image');

            pending[itemId] = {
                topic: topicEl ? topicEl.textContent.trim() : 'Deep Dive #' + itemId,
                summary: summaryEl ? summaryEl.textContent.trim() : '',
                imageUrl: imageEl ? imageEl.src : '',
                step: 0,
                totalSteps: 6,
                stepId: null,
                label: null,
                url: null,
                error: null,
            };

            injectProgress(itemId);
        });
    });
})();
