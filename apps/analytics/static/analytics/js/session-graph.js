/**
 * Session geography graph — force-directed network for admin analytics.
 *
 * Country → City → Session, square nodes, straight lines.
 * Uses ForceGraph.js.
 */
(function () {
    'use strict';

    var API = '/analytics/api/session-graph/';
    var container = null;
    var fgInstance = null;

    /* ── Node sizing (half-side) ────────────────── */

    function nodeHalf(node) {
        if (node.type === 'country') return Math.max(20, Math.min(50, 12 + Math.sqrt(node.sessions) * 3));
        if (node.type === 'city') return Math.max(10, Math.min(30, 6 + Math.sqrt(node.sessions) * 2));
        return 6; // session
    }

    /* ── Colors ─────────────────────────────────── */

    function getColors() {
        var isDark = document.documentElement.classList.contains('dark')
            || document.documentElement.getAttribute('data-theme') === 'dark';
        return {
            countryFill: isDark ? 'rgba(99,102,241,0.85)' : 'rgba(79,70,229,0.85)',
            countryStroke: isDark ? '#818cf8' : '#6366f1',
            countryText: '#fff',
            cityFill: isDark ? 'rgba(34,197,94,0.8)' : 'rgba(22,163,74,0.8)',
            cityStroke: isDark ? '#4ade80' : '#22c55e',
            cityText: isDark ? '#e5e7eb' : '#1f2937',
            sessFill: isDark ? 'rgba(234,179,8,0.7)' : 'rgba(202,138,4,0.7)',
            sessStroke: isDark ? '#facc15' : '#ca8a04',
            sessText: isDark ? '#fef9c3' : '#713f12',
            link: isDark ? 'rgba(148,163,184,0.2)' : 'rgba(100,116,139,0.15)',
            labelBg: isDark ? 'rgba(17,24,39,0.75)' : 'rgba(255,255,255,0.8)',
        };
    }

    /* ── Draw square node ───────────────────────── */

    function drawNode(node, ctx, globalScale, colors) {
        var h = nodeHalf(node);
        var x = node.x, y = node.y;
        var type = node.type;

        // Pick colors
        var fill, stroke, textColor;
        if (type === 'country') {
            fill = colors.countryFill; stroke = colors.countryStroke; textColor = colors.countryText;
        } else if (type === 'city') {
            fill = colors.cityFill; stroke = colors.cityStroke; textColor = colors.cityText;
        } else {
            fill = colors.sessFill; stroke = colors.sessStroke; textColor = colors.sessText;
        }

        // Square with rounded corners
        var r = Math.max(2, h * 0.15);
        ctx.beginPath();
        ctx.moveTo(x - h + r, y - h);
        ctx.lineTo(x + h - r, y - h);
        ctx.arcTo(x + h, y - h, x + h, y - h + r, r);
        ctx.lineTo(x + h, y + h - r);
        ctx.arcTo(x + h, y + h, x + h - r, y + h, r);
        ctx.lineTo(x - h + r, y + h);
        ctx.arcTo(x - h, y + h, x - h, y + h - r, r);
        ctx.lineTo(x - h, y - h + r);
        ctx.arcTo(x - h, y - h, x - h + r, y - h, r);
        ctx.closePath();
        ctx.fillStyle = fill;
        ctx.fill();
        ctx.strokeStyle = stroke;
        ctx.lineWidth = type === 'country' ? 2 : 1;
        ctx.stroke();

        // Text inside square — country: session count, city: session count, session: time
        if (type === 'country') {
            ctx.font = 'bold ' + Math.max(10, h * 0.4) + 'px -apple-system, system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = colors.countryText;
            ctx.fillText(node.sessions, x, y);
        } else if (type === 'city') {
            ctx.font = 'bold ' + Math.max(8, h * 0.45) + 'px -apple-system, system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = '#fff';
            ctx.fillText(node.sessions, x, y);
        } else {
            // Session: show time inside
            var tf = Math.max(6, h * 0.9);
            ctx.font = 'bold ' + tf + 'px -apple-system, system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = colors.sessText;
            ctx.fillText(node.time || '0s', x, y);
        }

        // Label below
        var fontSize = type === 'country' ? 11 : type === 'city' ? 9 : 7;
        if (globalScale < 0.5) fontSize += 3;
        ctx.font = (type === 'country' ? 'bold ' : '') + fontSize + 'px -apple-system, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';

        var label = node.label;
        var labelY = y + h + 3;
        var textW = ctx.measureText(label).width;

        // Background pill
        ctx.fillStyle = colors.labelBg;
        ctx.fillRect(x - textW / 2 - 3, labelY - 1, textW + 6, fontSize + 4);

        ctx.fillStyle = type === 'country' ? colors.countryStroke : type === 'city' ? colors.cityStroke : colors.sessStroke;
        ctx.fillText(label, x, labelY);

        // Store for pointer area
        node._h = h;
    }

    /* ── Render graph ───────────────────────────── */

    function renderGraph(el, data) {
        var colors = getColors();

        // Initial positions: countries in a ring, cities around them, sessions around cities
        var countries = data.nodes.filter(function (n) { return n.type === 'country'; });
        var angleStep = (2 * Math.PI) / Math.max(countries.length, 1);
        var ringR = Math.max(250, countries.length * 50);

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
                n.x = cp.x + Math.cos(a) * 120;
                n.y = cp.y + Math.sin(a) * 120;
                posById[n.id] = { x: n.x, y: n.y };
            }
        });

        // Place sessions near city
        data.nodes.forEach(function (n) {
            if (n.type !== 'session') return;
            var pid = parentMap[n.id];
            if (pid && posById[pid]) {
                var cp = posById[pid];
                var siblings = childrenMap[pid] || [];
                var idx = siblings.indexOf(n.id);
                var a = (2 * Math.PI * idx) / Math.max(siblings.length, 1) + Math.random() * 0.2;
                n.x = cp.x + Math.cos(a) * 50;
                n.y = cp.y + Math.sin(a) * 50;
            }
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
                var h = node._h || 10;
                ctx.fillStyle = color;
                ctx.fillRect(node.x - h - 2, node.y - h - 2, (h + 2) * 2, (h + 2) * 2);
            })
            .linkWidth(function (l) {
                var s = (typeof l.source === 'object') ? l.source : null;
                if (s && s.type === 'country') return 2;
                if (s && s.type === 'city') return 1;
                return 0.5;
            })
            .linkColor(function () { return colors.link; })
            .linkCurvature(0)
            .d3VelocityDecay(0.45)
            .d3AlphaDecay(0.04)
            .onNodeHover(function (node) {
                el.style.cursor = node ? 'grab' : 'default';
            })
            .onNodeDrag(function (node) {
                node.fx = node.x;
                node.fy = node.y;
            })
            .onNodeDragEnd(function (node) {
                node.fx = undefined;
                node.fy = undefined;
            })
            .cooldownTicks(100)
            .warmupTicks(120);

        // Forces — different strength per level
        fg.d3Force('charge').strength(function (n) {
            if (n.type === 'country') return -1200;
            if (n.type === 'city') return -300;
            return -60;
        }).distanceMax(800);

        fg.d3Force('link').distance(function (l) {
            var s = (typeof l.source === 'object') ? l.source : null;
            if (s && s.type === 'country') return 150;
            return 60;
        }).strength(function (l) {
            var s = (typeof l.source === 'object') ? l.source : null;
            if (s && s.type === 'country') return 0.5;
            return 0.8;
        });

        // Zoom to fit once stable
        var fitted = false;
        fg.onEngineTick(function () {
            if (!fitted) {
                fitted = true;
                fg.zoomToFit(0, 50);
            }
        });
        fg.onEngineStop(function () { fg.zoomToFit(400, 50); });

        // Resize handler
        var resizeTimer;
        function onResize() {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () {
                fg.width(el.clientWidth).height(el.clientHeight);
            }, 150);
        }
        window.addEventListener('resize', onResize);

        fgInstance = fg;
        fgInstance._onResize = onResize;
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
        setTimeout(function () { fgInstance.zoomToFit(400, 50); }, 500);
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadGraph);
    } else {
        loadGraph();
    }
})();
