/**
 * Deep dive feature — supports multiple concurrent generations.
 *
 * Marks digest items that have a ready deep dive, handles generation
 * requests via the WS client, and shows per-item progress in a panel.
 *
 * Depends on: ws.js, orbit-animation.js
 */
(function () {
    'use strict';

    /* ── State ────────────────────────────────────────── */

    // pending: { itemId: { topic, step, totalSteps, stepId, detail, url, error } }
    var pending = {};
    var progressPanel = null;

    var STEP_DEFS = [
        { id: 'queries',   icon: '\u2049' },
        { id: 'embedding', icon: '\u27A4' },
        { id: 'search',    icon: '\u25CE' },
        { id: 'grouping',  icon: '\u25A6' },
        { id: 'synthesis', icon: '\u270E' },
        { id: 'saving',    icon: '\u2713' },
    ];

    function pendingCount() {
        var n = 0;
        for (var k in pending) {
            if (pending.hasOwnProperty(k) && !pending[k].url && !pending[k].error) n++;
        }
        return n;
    }

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

        // Clear
        while (container.firstChild) container.removeChild(container.firstChild);

        for (var i = 0; i < keys.length; i++) {
            var itemId = keys[i];
            var p = pending[itemId];
            container.appendChild(buildItemRow(itemId, p));
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

        // Header: topic + status
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
            link.textContent = '\u2192';
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

        // Progress bar (only for in-progress)
        if (!p.url && !p.error) {
            var barWrap = document.createElement('div');
            barWrap.className = 'dd-item-bar';
            var barFill = document.createElement('div');
            barFill.className = 'dd-item-bar-fill';
            var pct = Math.round(((p.step || 0) / (p.totalSteps || 6)) * 100);
            barFill.style.width = pct + '%';
            barWrap.appendChild(barFill);
            row.appendChild(barWrap);

            // Current step indicator
            if (p.step && p.stepId) {
                var stepRow = document.createElement('div');
                stepRow.className = 'dd-item-step';

                var def = null;
                for (var i = 0; i < STEP_DEFS.length; i++) {
                    if (STEP_DEFS[i].id === p.stepId) { def = STEP_DEFS[i]; break; }
                }
                stepRow.textContent = (def ? def.icon + ' ' : '') + (p.label || p.stepId);
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
        // Remove ready/errored items after a delay
        var keys = Object.keys(pending);
        for (var i = 0; i < keys.length; i++) {
            if (pending[keys[i]].url || pending[keys[i]].error) {
                (function(k) {
                    setTimeout(function () {
                        delete pending[k];
                        renderPanel();
                        if (pendingCount() === 0) OrbitAnimation.stop();
                    }, 4000);
                })(keys[i]);
            }
        }
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
        pending[msg.item_id].url = msg.url;
        pending[msg.item_id].step = pending[msg.item_id].totalSteps || 6;
        renderPanel();

        // If this was the only pending item, redirect directly
        if (pendingCount() === 0 && Object.keys(pending).length === 1) {
            window.location.href = msg.url;
            return;
        }

        cleanupFinished();
    });

    WS.on('deep_dive.error', function (msg) {
        if (!hasPending(msg.item_id)) return;
        pending[msg.item_id].error = msg.message;
        renderPanel();
        cleanupFinished();

        if (pendingCount() === 0) {
            OrbitAnimation.stop();
        }
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
            OrbitAnimation.start();
        });
    });
})();
