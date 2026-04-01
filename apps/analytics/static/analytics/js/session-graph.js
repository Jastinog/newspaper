/**
 * Session geography graph — force-directed network for admin analytics.
 *
 * Country → City → Day → Session, square nodes, straight lines.
 * Uses ForceGraph.js.
 */
(function () {
    'use strict';

    var API = '/analytics/api/session-graph/';
    var container = null;
    var fgInstance = null;

    /* ── Colors ─────────────────────────────────── */

    function getColors() {
        var isDark = document.documentElement.classList.contains('dark')
            || document.documentElement.getAttribute('data-theme') === 'dark';
        return {
            isDark: isDark,
            countryFill: isDark ? 'rgba(99,102,241,0.85)' : 'rgba(79,70,229,0.85)',
            countryStroke: isDark ? '#818cf8' : '#6366f1',
            countryText: '#fff',
            cityFill: isDark ? 'rgba(34,197,94,0.8)' : 'rgba(22,163,74,0.8)',
            cityStroke: isDark ? '#4ade80' : '#22c55e',
            dayStroke: isDark ? '#c084fc' : '#a855f7',
            sessStroke: isDark ? '#facc15' : '#ca8a04',
            sessText: isDark ? '#fef9c3' : '#713f12',
            link: isDark ? 'rgba(148,163,184,0.2)' : 'rgba(100,116,139,0.15)',
        };
    }

    function nodeAge(n) { return typeof n.age === 'number' ? n.age : 0.5; }

    /* ── Rounded rect helper ──────────────────────── */

    function roundRect(ctx, x, y, w, h, r) {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.arcTo(x + w, y, x + w, y + r, r);
        ctx.lineTo(x + w, y + h - r);
        ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
        ctx.lineTo(x + r, y + h);
        ctx.arcTo(x, y + h, x, y + h - r, r);
        ctx.lineTo(x, y + r);
        ctx.arcTo(x, y, x + r, y, r);
        ctx.closePath();
    }

    /* ── Draw node — text-fitted rectangle ─────── */

    function drawNode(node, ctx, globalScale, colors) {
        var x = node.x, y = node.y;
        var type = node.type;
        var padX, padY, fill, stroke, borderW;

        if (type === 'country') {
            padX = 10; padY = 6;
            fill = colors.countryFill; stroke = colors.countryStroke; borderW = 2;
        } else if (type === 'city') {
            padX = 7; padY = 4;
            fill = colors.cityFill; stroke = colors.cityStroke; borderW = 1;
        } else if (type === 'day') {
            padX = 8; padY = 5;
            var dayOpacity = 0.9 - nodeAge(node) * 0.5;
            fill = colors.isDark
                ? 'rgba(168,85,247,' + dayOpacity + ')'
                : 'rgba(147,51,234,' + dayOpacity + ')';
            stroke = colors.dayStroke; borderW = 1.5;
        } else {
            padX = 5; padY = 3;
            var opacity = 0.9 - nodeAge(node) * 0.6;
            fill = colors.isDark
                ? 'rgba(234,179,8,' + opacity + ')'
                : 'rgba(202,138,4,' + opacity + ')';
            stroke = colors.sessStroke; borderW = 1;
        }

        // Build text lines and measure
        var lines = [];
        if (type === 'country') {
            lines.push({ text: node.label, font: 'bold 11px -apple-system, system-ui, sans-serif', color: colors.countryText });
            lines.push({ text: node.sessions + ' sess', font: '9px -apple-system, system-ui, sans-serif', color: 'rgba(255,255,255,0.75)' });
        } else if (type === 'city') {
            lines.push({ text: node.label, font: 'bold 9px -apple-system, system-ui, sans-serif', color: '#fff' });
            lines.push({ text: node.sessions + ' sess', font: '7px -apple-system, system-ui, sans-serif', color: 'rgba(255,255,255,0.7)' });
        } else if (type === 'day') {
            lines.push({ text: node.label, font: 'bold 10px -apple-system, system-ui, sans-serif', color: '#fff' });
            lines.push({ text: node.sessions + ' sess', font: '7px -apple-system, system-ui, sans-serif', color: 'rgba(255,255,255,0.7)' });
        } else {
            lines.push({ text: (node.hour || '') + ' · ' + (node.time || '0s'), font: 'bold 7px -apple-system, system-ui, sans-serif', color: colors.sessText });
        }

        // Measure each line
        var maxW = 0;
        var lineH = [];
        for (var i = 0; i < lines.length; i++) {
            ctx.font = lines[i].font;
            var m = ctx.measureText(lines[i].text);
            lines[i].w = m.width;
            if (m.width > maxW) maxW = m.width;
            var fSize = parseFloat(lines[i].font.match(/(\d+)px/)[1]);
            lines[i].h = fSize;
            lineH.push(fSize);
        }

        var gap = lines.length > 1 ? 3 : 0;
        var totalTextH = 0;
        for (var j = 0; j < lineH.length; j++) totalTextH += lineH[j];
        totalTextH += gap * (lines.length - 1);

        var rectW = maxW + padX * 2;
        var rectH = totalTextH + padY * 2;
        var rx = x - rectW / 2;
        var ry = y - rectH / 2;

        // Draw rectangle
        roundRect(ctx, rx, ry, rectW, rectH, 3);
        ctx.fillStyle = fill;
        ctx.fill();
        ctx.strokeStyle = stroke;
        ctx.lineWidth = borderW;
        ctx.stroke();

        // Draw text lines centered
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        var ty = ry + padY;
        for (var k = 0; k < lines.length; k++) {
            ctx.font = lines[k].font;
            ctx.fillStyle = lines[k].color;
            ctx.fillText(lines[k].text, x, ty);
            ty += lines[k].h + gap;
        }

        // Store bounding box for pointer area
        node._rx = rx; node._ry = ry; node._rw = rectW; node._rh = rectH;
    }

    /* ── Render graph ───────────────────────────── */

    function renderGraph(el, data) {
        var colors = getColors();

        // Initial positions: countries in a ring, cities around them, sessions around cities
        var countries = data.nodes.filter(function (n) { return n.type === 'country'; });
        var angleStep = (2 * Math.PI) / Math.max(countries.length, 1);
        var ringR = Math.max(400, countries.length * 80);

        countries.forEach(function (co, i) {
            co.x = Math.cos(angleStep * i) * ringR;
            co.y = Math.sin(angleStep * i) * ringR;
        });

        // Build parent lookup from links
        var parentMap = {};  // target id -> source id
        var childrenMap = {}; // source id -> [target ids]
        data.links.forEach(function (l) {
            parentMap[l.target] = l.source;
            if (!childrenMap[l.source]) childrenMap[l.source] = [];
            childrenMap[l.source].push(l.target);
        });

        var posById = {};
        countries.forEach(function (co) { posById[co.id] = { x: co.x, y: co.y }; });

        // Place cities near country
        data.nodes.forEach(function (n) {
            if (n.type !== 'city') return;
            var pid = parentMap[n.id];
            if (pid && posById[pid]) {
                var cp = posById[pid];
                var siblings = childrenMap[pid] || [];
                var idx = siblings.indexOf(n.id);
                var a = (2 * Math.PI * idx) / Math.max(siblings.length, 1);
                n.x = cp.x + Math.cos(a) * 180;
                n.y = cp.y + Math.sin(a) * 180;
                posById[n.id] = { x: n.x, y: n.y };
            }
        });

        // Place day nodes near city — newer closer, older further
        data.nodes.forEach(function (n) {
            if (n.type !== 'day') return;
            var pid = parentMap[n.id];
            if (pid && posById[pid]) {
                var cp = posById[pid];
                var siblings = childrenMap[pid] || [];
                var idx = siblings.indexOf(n.id);
                var a = (2 * Math.PI * idx) / Math.max(siblings.length, 1);
                var dist = 80 + nodeAge(n) * 200;
                n.x = cp.x + Math.cos(a) * dist;
                n.y = cp.y + Math.sin(a) * dist;
                posById[n.id] = { x: n.x, y: n.y };
            }
        });

        // Place sessions around their day node
        data.nodes.forEach(function (n) {
            if (n.type !== 'session') return;
            var pid = parentMap[n.id];
            if (pid && posById[pid]) {
                var cp = posById[pid];
                var siblings = childrenMap[pid] || [];
                var idx = siblings.indexOf(n.id);
                var a = (2 * Math.PI * idx) / Math.max(siblings.length, 1) + (Math.random() - 0.5) * 0.4;
                n.x = cp.x + Math.cos(a) * 50;
                n.y = cp.y + Math.sin(a) * 50;
            }
        });

        // Pin every node at its computed position — no simulation drift
        data.nodes.forEach(function (n) {
            n.fx = n.x;
            n.fy = n.y;
        });

        var fg = new ForceGraph()(el)
            .graphData(data)
            .width(el.clientWidth)
            .height(el.clientHeight)
            .nodeId('id')
            .nodeCanvasObject(function (node, ctx, gs) {
                drawNode(node, ctx, gs, colors);
            })
            .nodeCanvasObjectMode(function () { return 'replace'; })
            .nodePointerAreaPaint(function (node, color, ctx) {
                if (node._rw) {
                    ctx.fillStyle = color;
                    ctx.fillRect(node._rx - 2, node._ry - 2, node._rw + 4, node._rh + 4);
                }
            })
            .linkWidth(function (l) {
                var s = (typeof l.source === 'object') ? l.source : null;
                if (s && s.type === 'country') return 2;
                if (s && s.type === 'city') return 1.5;
                if (s && s.type === 'day') return 0.5;
                return 0.5;
            })
            .linkColor(function () { return colors.link; })
            .linkCurvature(0)
            .cooldownTicks(0)
            .onNodeHover(function (node) {
                el.style.cursor = node ? 'grab' : 'default';
            })
            .onNodeDrag(function (node) {
                node.fx = node.x;
                node.fy = node.y;
            })
            .onNodeDragEnd(function (node) {
                node.fx = node.x;
                node.fy = node.y;
            });

        // Kill all forces — layout is fully static
        fg.d3Force('charge', null);
        fg.d3Force('link', null);
        fg.d3Force('center', null);

        fgInstance = fg;
    }

    /* ── Fullscreen modal ───────────────────────── */

    function openFullscreen(data) {
        var overlay = document.createElement('div');
        overlay.className = 'sg-overlay';

        var header = document.createElement('div');
        header.className = 'sg-fs-header';
        var title = document.createElement('span');
        title.className = 'sg-fs-title';
        title.textContent = 'Session Geography';
        var closeBtn = document.createElement('button');
        closeBtn.className = 'sg-fs-close';
        closeBtn.textContent = '\u00d7';
        header.appendChild(title);
        header.appendChild(closeBtn);
        overlay.appendChild(header);

        var box = document.createElement('div');
        box.className = 'sg-fs-box';
        overlay.appendChild(box);

        document.body.appendChild(overlay);

        var fsFg = null;

        function close() {
            document.removeEventListener('keydown', onKey);
            if (fsFg) { fsFg.pauseAnimation(); fsFg = null; }
            overlay.remove();
        }
        function onKey(e) { if (e.key === 'Escape') close(); }

        closeBtn.onclick = close;
        overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
        document.addEventListener('keydown', onKey);

        requestAnimationFrame(function () {
            overlay.classList.add('sg-ready');
            var copy = JSON.parse(JSON.stringify(data));
            renderGraph(box, copy);
            fsFg = fgInstance;
        });
    }

    /* ── Init & public update ───────────────────── */

    var cachedData = null;

    function emptyMsg(parent, text) {
        while (parent.firstChild) parent.removeChild(parent.firstChild);
        var d = document.createElement('div');
        d.style.cssText = 'text-align:center;padding:40px;color:#9ca3af';
        d.textContent = text;
        parent.appendChild(d);
    }

    function loadGraph() {
        container = document.getElementById('session-graph-container');
        if (!container) return;

        fetch(API)
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(function (data) {
                cachedData = data;
                var loading = document.getElementById('session-graph-loading');
                if (loading) loading.remove();

                if (!data.nodes.length) {
                    emptyMsg(container, 'No visitor data');
                    return;
                }

                renderGraph(container, data);

                var fsBtn = document.getElementById('session-graph-fullscreen');
                if (fsBtn) {
                    fsBtn.addEventListener('click', function () {
                        if (cachedData) openFullscreen(cachedData);
                    });
                }
            })
            .catch(function (err) {
                console.error('Session graph:', err);
                var e = document.getElementById('session-graph-loading');
                if (e) e.textContent = '\u2717 Error loading data';
            });
    }

    window._updateSessionGraph = function (data) {
        cachedData = data;
        if (!container || !fgInstance) return;
        fgInstance.graphData(data);
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadGraph);
    } else {
        loadGraph();
    }
})();
