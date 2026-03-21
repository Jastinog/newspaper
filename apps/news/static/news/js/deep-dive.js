/**
 * Deep dive feature — supports multiple concurrent generations.
 *
 * Marks digest items that have a ready deep dive, handles generation
 * requests via the WS client, and shows per-item progress in a panel.
 * Non-blocking: user can continue browsing while deep dives generate.
 *
 * Depends on: ws.js
 */
(function () {
    'use strict';

    /* ── Helpers ──────────────────────────────────────── */

    /** Create a DOM element with a class name and optional text content. */
    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }

    /** Read an i18n data attribute from <body>, with a fallback. */
    function bodyData(key, fallback) {
        return document.body.dataset[key] || fallback;
    }

    /* ── State ────────────────────────────────────────── */

    var pending = {};
    var progressPanel = null;

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

    /** Add "deep-dive-ready" class to an item's <li>. */
    function markReady(itemId) {
        var link = document.querySelector(
            '.deep-dive-link[data-item-id="' + itemId + '"]'
        );
        if (link) link.closest('li').classList.add('deep-dive-ready');
    }

    /** Extract full item data from the DOM for display in panel/modal. */
    function getItemData(itemId) {
        var hint = document.querySelector(
            '.deep-dive-link[data-item-id="' + itemId + '"]'
        );
        var li = hint ? hint.closest('li') : null;
        if (!li) return { topic: 'Deep Dive #' + itemId, summary: '', imageUrl: '' };

        var topicEl = li.querySelector('.item-topic');
        var summaryEl = li.querySelector('.item-summary');
        var imageEl = li.querySelector('.item-image');

        return {
            topic: topicEl ? topicEl.textContent.trim() : 'Deep Dive #' + itemId,
            summary: summaryEl ? summaryEl.textContent.trim() : '',
            imageUrl: imageEl ? imageEl.src : '',
        };
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

    /* ── Progress panel rendering ────────────────────── */

    function getPanel() {
        if (!progressPanel) {
            progressPanel = document.getElementById('deepDiveProgress');
        }
        return progressPanel;
    }

    function renderPanel() {
        var panel = getPanel();
        if (!panel) return;

        var container = panel.querySelector('.dd-progress-items');
        if (!container) return;

        var keys = Object.keys(pending);
        if (keys.length === 0) {
            panel.classList.remove('active');
            return;
        }

        panel.classList.add('active');
        container.textContent = '';

        for (var i = 0; i < keys.length; i++) {
            container.appendChild(buildItemRow(pending[keys[i]]));
        }
    }

    function buildStatusIndicator(p) {
        if (p.url) return el('span', 'dd-item-done', '\u2713');
        if (p.error) return el('span', 'dd-item-error', '\u2717');
        return el('span', 'dd-item-status', (p.step || 0) + '/' + (p.totalSteps || 6));
    }

    function buildItemRow(p) {
        var row = el('div', 'dd-item');

        if (p.url) row.classList.add('ready');
        else if (p.error) row.classList.add('errored');

        if (p.imageUrl) {
            row.appendChild(img('dd-item-image', p.imageUrl));
        }

        row.appendChild(el('div', 'dd-item-topic', p.topic));

        if (p.summary) {
            row.appendChild(el('div', 'dd-item-summary', p.summary));
        }

        var header = el('div', 'dd-item-header');
        header.appendChild(buildStatusIndicator(p));
        row.appendChild(header);

        if (p.url || p.error) return row;

        var barWrap = el('div', 'dd-item-bar');
        var barFill = el('div', 'dd-item-bar-fill');
        var pct = Math.round(((p.step || 0) / (p.totalSteps || 6)) * 100);
        barFill.style.width = pct + '%';
        barWrap.appendChild(barFill);
        row.appendChild(barWrap);

        if (p.step && p.stepId) {
            var icon = STEP_ICONS[p.stepId];
            var stepRow = el('div', 'dd-item-step', (icon ? icon + ' ' : '') + (p.label || p.stepId));
            if (p.detail) {
                stepRow.appendChild(el('span', 'dd-item-detail', p.detail));
            }
            row.appendChild(stepRow);
        }

        return row;
    }

    function cleanupFinished() {
        Object.keys(pending).forEach(function (k) {
            var p = pending[k];
            if ((p.url || p.error) && !p._cleaning) {
                p._cleaning = true;
                setTimeout(function () {
                    delete pending[k];
                    renderPanel();
                }, 5000);
            }
        });
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
                    markReady(id);
                } else {
                    WS.send('deep_dive.generate', { item_id: id });
                }
            }
        }
        renderPanel();
        cleanupFinished();
    });

    WS.on('deep_dive.progress', function (msg) {
        if (!hasPending(msg.item_id)) return;
        var p = pending[msg.item_id];
        p.step = msg.step;
        p.totalSteps = msg.total_steps;
        p.stepId = msg.step_id;
        p.label = msg.label;
        p.detail = msg.detail;
        renderPanel();
    });

    WS.on('deep_dive.ready', function (msg) {
        markReady(msg.item_id);

        if (!hasPending(msg.item_id)) return;
        var p = pending[msg.item_id];
        p.url = msg.url;
        p.step = p.totalSteps || 6;
        renderPanel();

        showModal(p, msg.url);
        cleanupFinished();
    });

    WS.on('deep_dive.error', function (msg) {
        if (!hasPending(msg.item_id)) return;
        pending[msg.item_id].error = msg.message || bodyData('errorGeneration', 'Error');
        renderPanel();
        cleanupFinished();
    });

    /* ── Click handlers ──────────────────────────────── */

    document.querySelectorAll('.deep-dive-link').forEach(function (link) {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            var itemId = parseInt(this.dataset.itemId, 10);
            var href = this.getAttribute('href');

            if (this.closest('li').classList.contains('deep-dive-ready')) {
                window.location.href = href;
                return;
            }

            if (hasPending(itemId)) return;

            if (!WS.send('deep_dive.generate', { item_id: itemId })) {
                window.location.href = href;
                return;
            }

            var data = getItemData(itemId);
            pending[itemId] = {
                topic: data.topic,
                summary: data.summary,
                imageUrl: data.imageUrl,
                step: 0,
                totalSteps: 6,
                stepId: null,
                label: null,
                detail: null,
                url: null,
                error: null,
            };

            renderPanel();
        });
    });
})();
