/**
 * Traffic graph — force-directed DAG for admin analytics.
 *
 * Level 0 (right):   Countries
 * Level 1 (center):  Cities
 * Level 2 (left):    Clients (humans only, with aggregated stats)
 */
(function () {
    'use strict';

    var API = '/analytics/api/traffic-graph/';
    var cachedData = null;

    /* ── Helpers ─────────────────────────────────── */

    function truncate(s, max) { return s.length > max ? s.slice(0, max) + '\u2026' : s; }

    function wrapText(ctx, text, maxWidth) {
        var words = text.split(/\s+/);
        var lines = [], line = '';
        for (var i = 0; i < words.length; i++) {
            var test = line ? line + ' ' + words[i] : words[i];
            if (ctx.measureText(test).width > maxWidth && line) {
                lines.push(line); line = words[i];
            } else { line = test; }
        }
        if (line) lines.push(line);
        return lines;
    }

    function emptyMsg(parent, text) {
        while (parent.firstChild) parent.removeChild(parent.firstChild);
        var d = document.createElement('div');
        d.style.cssText = 'display:flex;align-items:center;justify-content:center;height:100%;color:#94a3b8;font-size:14px';
        d.textContent = text;
        parent.appendChild(d);
    }

    /* ── Build graph: country → city → client ────── */

    function buildGraph(data) {
        var nodes = [], links = [];

        (data.countries || []).forEach(function (co) {
            var coId = 'co:' + co.name;
            nodes.push({
                id: coId, type: 'country', _level: 0,
                label: co.flag + ' ' + co.name,
                sub: co.cc + ' cities',
                meta: '', url: null,
            });

            (co.cities || []).forEach(function (ci) {
                var ciId = 'ci:' + co.name + ':' + ci.name;
                nodes.push({
                    id: ciId, type: 'city', _level: 1,
                    label: ci.name,
                    sub: ci.cc + ' visitors',
                    meta: '', url: null,
                });
                links.push({ source: coId, target: ciId });

                (ci.clients || []).forEach(function (c) {
                    var cId = 'c:' + c.id;
                    nodes.push({
                        id: cId, type: 'client', _level: 2,
                        label: c.browser + ' \u00b7 ' + c.os,
                        sub: c.device,
                        meta: c.sc + ' sess \u00b7 ' + c.time + ' \u00b7 ' + c.pages + ' pg',
                        url: c.url || null,
                    });
                    links.push({ source: ciId, target: cId });
                });
            });
        });

        return { nodes: nodes, links: links };
    }

    /* ── Per-type card sizing ────────────────────── */

    var SIZES = {
        country: { cardW: 180, stripe: 4, pad: 8, titlePx: 10, maxTitle: 2, subPx: 7,   metaPx: 7,   metaH: 12, borderW: 1.5 },
        city:    { cardW: 160, stripe: 3, pad: 7, titlePx: 9,  maxTitle: 2, subPx: 6.5, metaPx: 6.5, metaH: 11, borderW: 1 },
        client:  { cardW: 210, stripe: 3, pad: 6, titlePx: 8,  maxTitle: 2, subPx: 6,   metaPx: 6,   metaH: 10, borderW: 0.8 },
    };

    /* ── Detect admin dark mode ──────────────────── */

    function getColors() {
        var html = document.documentElement;
        var isDark = html.classList.contains('dark')
            || html.getAttribute('data-theme') === 'dark'
            || html.getAttribute('data-mode') === 'dark';
        return {
            bg:          isDark ? '#1e293b' : '#ffffff',
            fg:          isDark ? '#e2e8f0' : '#1e293b',
            fgMuted:     isDark ? '#94a3b8' : '#64748b',
            fgFaint:     isDark ? '#475569' : '#cbd5e1',
            borderLight: isDark ? '#334155' : '#e2e8f0',
            country:     isDark ? '#60a5fa' : '#3b82f6',   // blue
            city:        isDark ? '#2dd4bf' : '#14b8a6',   // teal
            client:      isDark ? '#34d399' : '#22c55e',   // green
            link:        isDark ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.07)',
            overlayBg:   isDark ? 'rgba(15,23,42,0.88)'   : 'rgba(255,255,255,0.85)',
        };
    }

    var LEGEND = [
        ['country', 'Countries'],
        ['city',    'Cities'],
        ['client',  'Visitors'],
    ];

    /* ── Compute card layout metrics ─────────────── */

    function computeLayout(node, ctx) {
        var S = SIZES[node.type];
        var textW = S.cardW - S.stripe - S.pad * 2;

        ctx.font = '700 ' + S.titlePx + 'px -apple-system,system-ui,sans-serif';
        var titleLines = wrapText(ctx, node.label, textW);
        if (titleLines.length > S.maxTitle) {
            titleLines = titleLines.slice(0, S.maxTitle);
            titleLines[S.maxTitle - 1] += '\u2026';
        }
        var titleH = titleLines.length * S.titlePx * 1.35;
        var subH = node.sub ? S.metaH : 0;
        var metaH = node.meta ? S.metaH : 0;
        var cardH = S.pad + titleH + subH + metaH + S.pad;

        return { S: S, cardW: S.cardW, cardH: cardH, textW: textW, titleLines: titleLines };
    }

    /* ── Canvas: draw a single node card ─────────── */

    function drawNode(node, ctx, gs, colors) {
        if (!node._layout) node._layout = computeLayout(node, ctx);
        var L = node._layout, S = L.S;
        var x = node.x - L.cardW / 2, y = node.y - L.cardH / 2;

        ctx.fillStyle = colors.bg;
        ctx.fillRect(x, y, L.cardW, L.cardH);

        var stripe = colors[node.type] || colors.fgMuted;
        ctx.fillStyle = stripe;
        ctx.fillRect(x, y, S.stripe, L.cardH);

        ctx.strokeStyle = stripe;
        ctx.lineWidth = S.borderW;
        ctx.strokeRect(x, y, L.cardW, L.cardH);

        var tx = x + S.stripe + S.pad, ty = y + S.pad;
        ctx.font = '700 ' + S.titlePx + 'px -apple-system,system-ui,sans-serif';
        ctx.textAlign = 'left'; ctx.textBaseline = 'top';
        ctx.fillStyle = colors.fg;
        for (var i = 0; i < L.titleLines.length; i++) {
            ctx.fillText(L.titleLines[i], tx, ty);
            ty += S.titlePx * 1.35;
        }

        if (node.sub) {
            ctx.font = S.subPx + 'px -apple-system,system-ui,sans-serif';
            ctx.fillStyle = colors.fgMuted;
            ctx.fillText(truncate(node.sub, 35), tx, ty + 1);
            ty += S.metaH;
        }

        if (node.meta) {
            ctx.font = '600 ' + S.metaPx + 'px -apple-system,system-ui,sans-serif';
            ctx.fillStyle = stripe;
            ctx.fillText(truncate(node.meta, 40), tx, ty + 1);
        }

        node._bx = x; node._by = y; node._bw = L.cardW; node._bh = L.cardH;
    }

    /* ── Render force graph into container ────────── */

    var LEVEL_X = { 0: 350, 1: 0, 2: -350 };

    function render(container, graphData) {
        var colors = getColors();

        var fg = new ForceGraph()(container)
            .graphData(graphData)
            .width(container.clientWidth)
            .height(container.clientHeight)
            .nodeId('id')
            .nodeCanvasObject(function (n, ctx, gs) { drawNode(n, ctx, gs, colors); })
            .nodeCanvasObjectMode(function () { return 'replace'; })
            .nodePointerAreaPaint(function (n, c, ctx) {
                if (n._bw) { ctx.fillStyle = c; ctx.fillRect(n._bx, n._by, n._bw, n._bh); }
            })
            .linkWidth(1)
            .linkColor(function () { return colors.link; })
            .d3VelocityDecay(0.85)
            .d3AlphaDecay(0.1)
            .cooldownTicks(60)
            .warmupTicks(150)
            .onNodeClick(function (n) { if (n.url) window.open(n.url, '_blank'); })
            .onNodeHover(function (n) { container.style.cursor = n && n.url ? 'pointer' : 'default'; })
            .onNodeDrag(function (n) { n.fx = n.x; n.fy = n.y; })
            .onNodeDragEnd(function (n) { n.fx = undefined; n.fy = undefined; });

        fg.d3Force('charge').strength(-3000).distanceMax(600);
        fg.d3Force('link').distance(350);

        fg.d3Force('levelX', (function () {
            var nodes;
            function force(alpha) {
                for (var i = 0; i < nodes.length; i++) {
                    var n = nodes[i];
                    var tx = LEVEL_X[n._level] || 0;
                    n.vx += (tx - n.x) * 0.12 * alpha;
                }
            }
            force.initialize = function (_) { nodes = _; };
            return force;
        })());

        var zoomed = false;
        fg.onEngineTick(function () {
            if (!zoomed) { zoomed = true; fg.zoomToFit(0, 40); }
        });
        fg.onEngineStop(function () { fg.zoomToFit(300, 40); });

        var timer;
        function onResize() {
            clearTimeout(timer);
            timer = setTimeout(function () {
                graphData.nodes.forEach(function (n) { delete n._layout; });
                fg.width(container.clientWidth).height(container.clientHeight);
            }, 100);
        }
        window.addEventListener('resize', onResize);

        return { fg: fg, cleanup: function () { window.removeEventListener('resize', onResize); } };
    }

    /* ── Fullscreen modal ────────────────────────── */

    function openFullscreen() {
        var colors = getColors();

        var overlay = document.createElement('div');
        overlay.className = 'tg-overlay';
        overlay.style.background = colors.overlayBg;

        var header = document.createElement('div');
        header.className = 'tg-header';
        var title = document.createElement('span');
        title.className = 'tg-title';
        title.textContent = 'Visitors';
        title.style.color = colors.fgMuted;
        header.appendChild(title);
        var closeBtn = document.createElement('button');
        closeBtn.className = 'tg-close';
        closeBtn.textContent = '\u00d7';
        closeBtn.style.color = colors.fgMuted;
        header.appendChild(closeBtn);
        overlay.appendChild(header);

        var box = document.createElement('div');
        box.className = 'tg-fullscreen-box';
        overlay.appendChild(box);

        var legend = document.createElement('div');
        legend.className = 'tg-legend';
        LEGEND.forEach(function (t) {
            var item = document.createElement('span');
            item.className = 'tg-legend-item';
            item.style.color = colors.fgMuted;
            var dot = document.createElement('span');
            dot.className = 'tg-legend-dot';
            dot.style.background = colors[t[0]];
            item.appendChild(dot);
            item.appendChild(document.createTextNode(t[1]));
            legend.appendChild(item);
        });
        overlay.appendChild(legend);

        document.body.appendChild(overlay);

        var instance = null;
        function onKey(e) {
            if (e.key === 'Escape') close();
        }
        function close() {
            if (instance) { instance.fg.pauseAnimation(); instance.cleanup(); }
            document.removeEventListener('keydown', onKey);
            overlay.remove();
        }
        closeBtn.onclick = close;
        overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
        document.addEventListener('keydown', onKey);

        var freshData = buildGraph(cachedData);
        requestAnimationFrame(function () {
            overlay.classList.add('tg-ready');
            instance = render(box, freshData);
        });
    }

    /* ── Init ─────────────────────────────────────── */

    function init() {
        var container = document.getElementById('traffic-graph-container');
        if (!container) return;
        if (typeof ForceGraph === 'undefined') { setTimeout(init, 100); return; }

        fetch(API)
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(function (data) {
                cachedData = data;
                var loading = document.getElementById('traffic-graph-loading');
                if (loading) loading.remove();

                var graph = buildGraph(data);
                if (!graph.nodes.length) {
                    emptyMsg(container, 'No traffic data');
                    return;
                }

                render(container, graph);

                var fsBtn = document.getElementById('traffic-graph-fullscreen');
                if (fsBtn) fsBtn.addEventListener('click', function () { openFullscreen(); });
            })
            .catch(function (err) {
                console.error('Traffic graph:', err);
                var el = document.getElementById('traffic-graph-loading');
                if (el) el.textContent = '\u2717 Error loading graph';
            });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else { init(); }
})();
