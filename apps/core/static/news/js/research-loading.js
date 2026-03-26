/**
 * Research loading page — handles generation trigger and progress display.
 *
 * Expects a global RESEARCH_ITEM_ID variable set by the template.
 * Depends on: ws.js, orbit-animation.js
 */
(function () {
    'use strict';

    var itemId = window.RESEARCH_ITEM_ID;
    if (!itemId) return;

    var langPrefix = document.body.dataset.langPrefix || '';

    var STEP_DEFS = [
        { icon: '\u2049', label: 'Search queries' },
        { icon: '\u27A4', label: 'Embeddings' },
        { icon: '\u25CE', label: 'Article search' },
        { icon: '\u25A6', label: 'Grouping' },
        { icon: '\u270E', label: 'Synthesis' },
        { icon: '\u2713', label: 'Saving' },
    ];

    function showProgress(msg) {
        var panel = document.getElementById('deepDiveProgress');
        if (!panel) return;
        panel.style.display = 'block';

        var stepsEl = panel.querySelector('.dd-progress-steps');
        var total = msg.total_steps || 6;
        var current = msg.step || 1;

        stepsEl.textContent = '';

        for (var i = 0; i < STEP_DEFS.length && i < total; i++) {
            var s = STEP_DEFS[i];
            var num = i + 1;
            var state = '';
            if (num < current) state = ' done';
            else if (num === current) state = ' active';

            var div = document.createElement('div');
            div.className = 'dd-step' + state;

            var icon = document.createElement('span');
            icon.className = 'dd-step-icon';
            icon.textContent = s.icon;
            div.appendChild(icon);

            var label = document.createElement('span');
            label.className = 'dd-step-label';
            label.textContent = s.label;
            div.appendChild(label);

            if (num === current && msg.detail) {
                var det = document.createElement('span');
                det.className = 'dd-step-detail';
                det.textContent = msg.detail;
                div.appendChild(det);
            }
            stepsEl.appendChild(div);
        }

        var bar = panel.querySelector('.dd-progress-bar-fill');
        if (bar) bar.style.width = Math.round((current / total) * 100) + '%';
    }

    var generating = false;

    function showGeneratingUI() {
        document.getElementById('generatePrompt').style.display = 'none';
        document.getElementById('generatingState').style.display = 'block';
    }

    function startGeneration() {
        if (generating) return;
        generating = true;
        showGeneratingUI();
        WS.send('research.generate', { item_id: itemId });
    }

    document.getElementById('generateBtn').addEventListener('click', startGeneration);

    WS.on('research.state', function (msg) {
        var ready = msg.ready || [];
        var inProgress = msg.generating || [];

        if (ready.indexOf(itemId) !== -1) {
            window.location.href = langPrefix + '/research/' + itemId + '/';
            return;
        }

        if (inProgress.indexOf(itemId) !== -1) {
            startGeneration();
            return;
        }

        if (generating) {
            WS.send('research.generate', { item_id: itemId });
        }
    });

    WS.on('research.progress', function (msg) {
        if (msg.item_id === itemId) showProgress(msg);
    });

    WS.on('research.ready', function (msg) {
        if (msg.item_id === itemId) window.location.href = langPrefix + '/research/' + itemId + '/';
    });

    WS.on('research.error', function (msg) {
        if (msg.item_id === itemId) {
            generating = false;
            document.getElementById('generatingState').style.display = 'none';
            document.getElementById('loadingError').style.display = 'block';
        }
    });
})();
