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

    /** Get topic text for an item from the DOM. */
    function getTopicText(itemId) {
        var link = document.querySelector(
            'a.item-topic[data-item-id="' + itemId + '"]'
        );
        if (link) {
            var text = link.textContent.trim();
            return text.length > 40 ? text.substring(0, 37) + '...' : text;
        }
        return 'Deep Dive #' + itemId;
    }

    /* ── Toast notification ────────────────────────────── */

    function showToast(topic, url) {
        var toast = document.createElement('div');
        toast.className = 'dd-toast';

        function dismiss() {
            toast.classList.remove('dd-toast-visible');
            setTimeout(function () { toast.remove(); }, 300);
        }

        var text = document.createElement('div');
        text.className = 'dd-toast-text';

        var label = document.createElement('div');
        label.className = 'dd-toast-label';
        label.textContent = document.body.dataset.ddReady || 'Deep dive ready';
        text.appendChild(label);

        var topicEl = document.createElement('div');
        topicEl.className = 'dd-toast-topic';
        topicEl.textContent = topic;
        text.appendChild(topicEl);

        toast.appendChild(text);

        var link = document.createElement('a');
        link.className = 'dd-toast-link';
        link.href = url;
        link.textContent = document.body.dataset.ddRead || 'Read \u2192';
        toast.appendChild(link);

        var close = document.createElement('button');
        close.className = 'dd-toast-close';
        close.textContent = '\u00d7';
        close.onclick = dismiss;
        toast.appendChild(close);

        document.body.appendChild(toast);
        void toast.offsetHeight; /* trigger reflow for transition */
        toast.classList.add('dd-toast-visible');

        setTimeout(function () {
            if (toast.parentNode) dismiss();
        }, 15000);
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
            container.appendChild(buildItemRow(keys[i], pending[keys[i]]));
        }
    }

    function buildItemRow(itemId, p) {
        var row = document.createElement('div');
        row.className = 'dd-item';

        if (p.url) {
            row.classList.add('ready');
        } else if (p.error) {
            row.classList.add('errored');
        }

        var header = document.createElement('div');
        header.className = 'dd-item-header';

        var topic = document.createElement('span');
        topic.className = 'dd-item-topic';
        topic.textContent = p.topic;
        header.appendChild(topic);

        if (p.url) {
            var link = document.createElement('a');
            link.className = 'dd-item-link';
            link.href = p.url;
            link.textContent = document.body.dataset.ddRead || 'Read \u2192';
            header.appendChild(link);
        } else if (p.error) {
            var errSpan = document.createElement('span');
            errSpan.className = 'dd-item-error';
            errSpan.textContent = '\u2717';
            header.appendChild(errSpan);
        } else {
            var status = document.createElement('span');
            status.className = 'dd-item-status';
            status.textContent = (p.step || 0) + '/' + (p.totalSteps || 6);
            header.appendChild(status);
        }

        row.appendChild(header);

        if (!p.url && !p.error) {
            var barWrap = document.createElement('div');
            barWrap.className = 'dd-item-bar';
            var barFill = document.createElement('div');
            barFill.className = 'dd-item-bar-fill';
            var pct = Math.round(((p.step || 0) / (p.totalSteps || 6)) * 100);
            barFill.style.width = pct + '%';
            barWrap.appendChild(barFill);
            row.appendChild(barWrap);

            if (p.step && p.stepId) {
                var stepRow = document.createElement('div');
                stepRow.className = 'dd-item-step';

                var icon = STEP_ICONS[p.stepId];
                stepRow.textContent = (icon ? icon + ' ' : '') + (p.label || p.stepId);
                if (p.detail) {
                    var det = document.createElement('span');
                    det.className = 'dd-item-detail';
                    det.textContent = p.detail;
                    stepRow.appendChild(det);
                }
                row.appendChild(stepRow);
            }
        }

        return row;
    }

    function cleanupFinished() {
        Object.keys(pending).forEach(function (k) {
            if (pending[k].error) {
                setTimeout(function () {
                    delete pending[k];
                    renderPanel();
                }, 5000);
            }
        });
    }

    /* ── WS handlers ─────────────────────────────────── */

    WS.on('init', function (msg) {
        var dives = msg.deep_dives || {};
        var readyIds = dives.ready || [];
        readyIds.forEach(markReady);

        /* Reconnect recovery: re-send generate for any still-pending items */
        var keys = Object.keys(pending);
        for (var i = 0; i < keys.length; i++) {
            var p = pending[keys[i]];
            if (!p.url && !p.error) {
                var id = parseInt(keys[i], 10);
                if (readyIds.indexOf(id) !== -1) {
                    // Finished while disconnected
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

        showToast(p.topic, msg.url);
        cleanupFinished();
    });

    WS.on('deep_dive.error', function (msg) {
        if (!hasPending(msg.item_id)) return;
        pending[msg.item_id].error =
            msg.message || document.body.dataset.errorGeneration || 'Error';
        renderPanel();
        cleanupFinished();
    });

    /* ── Click handlers ──────────────────────────────── */

    document.querySelectorAll('.deep-dive-link').forEach(function (link) {
        link.addEventListener('click', function (e) {
            e.preventDefault();
            var itemId = parseInt(this.dataset.itemId, 10);
            var href = this.getAttribute('href');

            /* Already generated — navigate directly */
            if (this.closest('li').classList.contains('deep-dive-ready')) {
                window.location.href = href;
                return;
            }

            /* Already pending — ignore duplicate click */
            if (hasPending(itemId)) return;

            /* WS not available — fallback to HTTP */
            if (!WS.send('deep_dive.generate', { item_id: itemId })) {
                window.location.href = href;
                return;
            }

            pending[itemId] = {
                topic: getTopicText(itemId),
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
