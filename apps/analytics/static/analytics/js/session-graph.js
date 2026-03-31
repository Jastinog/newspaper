/**
 * Session geography graph — force-directed network for admin analytics.
 *
 * Country nodes (large) → City nodes (small), sized by session count.
 * Uses ForceGraph.js (same lib as the similar-news graph).
 */
(function () {
    'use strict';

    var API = '/analytics/api/session-graph/';
    var container = null;
    var fgInstance = null;

    /* ── Helpers ─────────────────────────────────── */

    function cssVar(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    /* ── Node sizing ────────────────────────────── */

    function countryRadius(sessions) {
        return Math.max(18, Math.min(50, 10 + Math.sqrt(sessions) * 3));
    }

    function cityRadius(sessions) {
        return Math.max(6, Math.min(28, 4 + Math.sqrt(sessions) * 2));
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
            link: isDark ? 'rgba(148,163,184,0.25)' : 'rgba(100,116,139,0.2)',
            labelBg: isDark ? 'rgba(17,24,39,0.75)' : 'rgba(255,255,255,0.8)',
        };
    }

    /* ── Draw node ──────────────────────────────── */

    function drawNode(node, ctx, globalScale, colors) {
        var isCountry = node.type === 'country';
        var r = isCountry ? countryRadius(node.sessions) : cityRadius(node.sessions);
        var x = node.x, y = node.y;

        // Circle
        ctx.beginPath();
        ctx.arc(x, y, r, 0, 2 * Math.PI);
        ctx.fillStyle = isCountry ? colors.countryFill : colors.cityFill;
        ctx.fill();
        ctx.strokeStyle = isCountry ? colors.countryStroke : colors.cityStroke;
        ctx.lineWidth = isCountry ? 2 : 1;
        ctx.stroke();

        // Sessions badge (inside circle for countries)
        if (isCountry) {
            ctx.font = 'bold ' + Math.max(10, r * 0.4) + 'px -apple-system, system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillStyle = colors.countryText;
            ctx.fillText(node.sessions, x, y);
        }

        // Label below
        var fontSize = isCountry ? 11 : 8;
        if (globalScale < 0.6) fontSize = isCountry ? 14 : 10;
        ctx.font = (isCountry ? 'bold ' : '') + fontSize + 'px -apple-system, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';

        var label = node.label;
        var labelY = y + r + 3;
        var textW = ctx.measureText(label).width;

        // Background pill for readability
        ctx.fillStyle = colors.labelBg;
        ctx.fillRect(x - textW / 2 - 3, labelY - 1, textW + 6, fontSize + 4);

        ctx.fillStyle = isCountry ? colors.countryStroke : colors.cityText;
        ctx.fillText(label, x, labelY);

        // City: small session count
        if (!isCountry && node.sessions > 0) {
            var badgeFontSize = 7;
            ctx.font = badgeFontSize + 'px -apple-system, system-ui, sans-serif';
            var badgeText = node.sessions + ' sess';
            var bw = ctx.measureText(badgeText).width;
            var by = labelY + fontSize + 2;
            ctx.fillStyle = colors.labelBg;
            ctx.fillRect(x - bw / 2 - 2, by - 1, bw + 4, badgeFontSize + 3);
            ctx.fillStyle = colors.cityStroke;
            ctx.fillText(badgeText, x, by);
        }

        // Store bounding box for pointer area
        var totalH = r + 4 + fontSize + (isCountry ? 0 : 12);
        node._r = r;
        node._bx = x - Math.max(r, textW / 2 + 3);
        node._by = y - r;
        node._bw = Math.max(r * 2, textW + 6);
        node._bh = r + totalH;
    }

    /* ── Render graph ───────────────────────────── */

    function renderGraph(el, data) {
        var colors = getColors();

        // Set initial positions: countries in a circle, cities near their country
        var countries = data.nodes.filter(function (n) { return n.type === 'country'; });
        var angleStep = (2 * Math.PI) / Math.max(countries.length, 1);
        var ringR = Math.max(200, countries.length * 40);

        countries.forEach(function (co, i) {
            co.x = Math.cos(angleStep * i) * ringR;
            co.y = Math.sin(angleStep * i) * ringR;
        });

        // Place cities near their country
        var countryPos = {};
        countries.forEach(function (co) { countryPos[co.id] = { x: co.x, y: co.y }; });

        var cityIndex = {};
        data.links.forEach(function (l) {
            if (!cityIndex[l.source]) cityIndex[l.source] = [];
            cityIndex[l.source].push(l.target);
        });

        data.nodes.forEach(function (n) {
            if (n.type !== 'city') return;
            // Find parent country link
            var parentLink = data.links.find(function (l) { return l.target === n.id; });
            if (parentLink && countryPos[parentLink.source]) {
                var cp = countryPos[parentLink.source];
                var siblings = cityIndex[parentLink.source] || [];
                var idx = siblings.indexOf(n.id);
                var spread = Math.min(siblings.length, 8);
                var a = (2 * Math.PI * idx) / spread + Math.random() * 0.3;
                var dist = 80 + Math.random() * 60;
                n.x = cp.x + Math.cos(a) * dist;
                n.y = cp.y + Math.sin(a) * dist;
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
                if (node._r) {
                    ctx.beginPath();
                    ctx.arc(node.x, node.y, node._r + 5, 0, 2 * Math.PI);
                    ctx.fillStyle = color;
                    ctx.fill();
                }
            })
            .linkWidth(function (l) { return Math.max(0.5, Math.min(4, Math.sqrt(l.value) * 0.5)); })
            .linkColor(function () { return colors.link; })
            .linkCurvature(0.15)
            .d3VelocityDecay(0.4)
            .d3AlphaDecay(0.05)
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
            .cooldownTicks(80)
            .warmupTicks(100);

        // Forces
        fg.d3Force('charge').strength(function (n) {
            return n.type === 'country' ? -800 : -200;
        }).distanceMax(600);

        fg.d3Force('link').distance(function () {
            return 120;
        }).strength(0.6);

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
            // Deep-copy data so fullscreen graph has its own simulation
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

    // Allow dashboard auto-refresh to update graph data
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
