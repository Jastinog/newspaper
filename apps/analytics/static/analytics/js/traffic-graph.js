/**
 * Traffic graph — force-directed DAG for admin analytics.
 *
 * Level 0 (left):   Referrer source domains
 * Level 1 (center): Clients / visitors
 * Level 2 (right):  Sessions
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

    /* ── Build graph nodes & links from API data ─── */

    function buildGraph(data) {
        var nodes = [], links = [];

        (data.sources || []).forEach(function (src) {
            var srcId = 's:' + src.domain;
            nodes.push({
                id: srcId, type: 'source', _level: 0,
                label: src.domain === 'direct' ? 'Direct' : src.domain,
                sub: src.sessions + ' sess \u00b7 ' + src.clients_total + ' vis',
                meta: '', url: null,
            });

            (src.clients || []).forEach(function (c) {
                var cId = 'c:' + c.id;
                var label = c.is_bot
                    ? '\uD83E\uDD16 ' + (c.bot_name || c.browser)
                    : '\uD83D\uDC64 ' + c.browser + ' \u00b7 ' + c.os;

                nodes.push({
                    id: cId, type: c.is_bot ? 'bot' : 'client', _level: 1,
                    label: label,
                    sub: c.loc || '',
                    meta: c.sc + ' sess',
                    url: c.url || null,
                });
                links.push({ source: srcId, target: cId });

                (c.sessions || []).forEach(function (sess) {
                    var sId = 'ss:' + sess.id;
                    var check = sess.ok ? ' \u2714' : '';
                    nodes.push({
                        id: sId, type: 'session', _level: 2,
                        label: sess.pages + ' pg \u00b7 ' + sess.time + check,
                        sub: sess.date,
                        meta: '',
                        url: '/admin/analytics/session/' + sess.id + '/change/',
                    });
                    links.push({ source: cId, target: sId });
                });
            });
        });

        return { nodes: nodes, links: links };
    }

    /* ── Per-type card sizing ────────────────────── */

    var CLIENT_SIZE = { cardW: 175, stripe: 3, pad: 6, titlePx: 8.5, maxTitle: 2, subPx: 6.5, metaPx: 6.5, metaH: 10, borderW: 0.8 };

    var SIZES = {
        source:  { cardW: 200, stripe: 4, pad: 8, titlePx: 10, maxTitle: 2, subPx: 7, metaPx: 7, metaH: 12, borderW: 1.5 },
        client:  CLIENT_SIZE,
        bot:     CLIENT_SIZE,
        session: { cardW: 140, stripe: 3, pad: 5, titlePx: 7,  maxTitle: 2, subPx: 6, metaPx: 6, metaH: 10, borderW: 0.5 },
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
            source:      isDark ? '#60a5fa' : '#3b82f6',
            client:      isDark ? '#34d399' : '#22c55e',
            bot:         isDark ? '#f87171' : '#ef4444',
            session:     isDark ? '#c084fc' : '#a855f7',
            link:        isDark ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.07)',
            overlayBg:   isDark ? 'rgba(15,23,42,0.88)'   : 'rgba(255,255,255,0.85)',
        };
    }

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
            ctx.fillText(truncate(node.sub, 30), tx, ty + 1);
            ty += S.metaH;
        }

        if (node.meta) {
            ctx.font = '600 ' + S.metaPx + 'px -apple-system,system-ui,sans-serif';
            ctx.fillStyle = stripe;
            ctx.fillText(node.meta, tx, ty + 1);
        }

        node._bx = x; node._by = y; node._bw = L.cardW; node._bh = L.cardH;
    }

    /* ── Render force graph into container ────────── */

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
            .d3VelocityDecay(0.6)
            .cooldownTicks(200)
            .warmupTicks(150)
            .onNodeClick(function (n) { if (n.url) window.open(n.url, '_blank'); })
            .onNodeHover(function (n) { container.style.cursor = n && n.url ? 'pointer' : 'default'; });

        fg.d3Force('charge').strength(-2500).distanceMax(500);
        fg.d3Force('link').distance(250);

        fg.d3Force('levelX', (function () {
            var nodes;
            function force(alpha) {
                for (var i = 0; i < nodes.length; i++) {
                    var n = nodes[i];
                    var tx = n._level === 0 ? -350 : n._level === 1 ? 0 : 350;
                    n.vx += (tx - n.x) * 0.12 * alpha;
                }
            }
            force.initialize = function (_) { nodes = _; };
            return force;
        })());

        // Zoom to fit once on first frame, then smoothly when simulation stops
        var zoomed = false;
        fg.onEngineTick(function () {
            if (!zoomed) { zoomed = true; fg.zoomToFit(0, 40); }
        });
        fg.onEngineStop(function () { fg.zoomToFit(400, 40); });

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
        title.textContent = 'Visitor Sessions';
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
        [['source', 'Sources', colors.source],
         ['client', 'Visitors', colors.client],
         ['bot', 'Bots', colors.bot],
         ['session', 'Sessions', colors.session]].forEach(function (t) {
            var item = document.createElement('span');
            item.className = 'tg-legend-item';
            item.style.color = colors.fgMuted;
            var dot = document.createElement('span');
            dot.className = 'tg-legend-dot';
            dot.style.background = t[2];
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

    /* ── Init: fetch data and render inline graph ── */

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
