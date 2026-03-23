/**
 * Similar news — 2D DAG tree (left → right).
 *
 * Level 0: current digest item (center)
 * Level 1: similar digest items + standalone articles
 * Level 2: articles of each similar digest item
 *
 * Uses dagMode('lr') so nodes never overlap.
 */
(function () {
    'use strict';

    var API = '/api/digest-items/';
    var cache = {};

    /* ── Helpers ──────────────────────────────────── */

    function el(tag, cls, text) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (text != null) n.textContent = text;
        return n;
    }

    function clearChildren(n) { while (n.firstChild) n.removeChild(n.firstChild); }
    function bd(k, fb) { return document.body.dataset[k] || fb; }
    function truncate(s, max) { return s.length > max ? s.slice(0, max) + '\u2026' : s; }

    function cssVar(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    /* ── Build DAG graph data ────────────────────── */

    function buildGraph(center, data) {
        var nodes = [{
            id: 'c', type: 'center',
            label: center.topic, summary: center.summary || '',
            imageUrl: center.imageUrl, score: 0, url: null, sub: '',
        }];
        var links = [];

        // Level 1: similar digest items → Level 2: their articles
        (data.items || []).forEach(function (d) {
            var nid = 'i' + d.id;
            nodes.push({
                id: nid, type: 'item',
                label: d.topic, summary: d.summary || '',
                sub: d.section + ' \u00b7 ' + d.date,
                score: d.score || 0,
                imageUrl: d.image_url || '', url: d.deep_dive_url,
            });
            links.push({ source: 'c', target: nid });

            (d.articles || []).forEach(function (a) {
                var aid = 'a' + a.id + '_' + d.id;
                nodes.push({
                    id: aid, type: 'article',
                    label: a.title, summary: '',
                    sub: a.feed || '', score: 0,
                    imageUrl: '', url: a.url,
                });
                links.push({ source: nid, target: aid });
            });
        });

        // Level 1: standalone similar articles (no digest item)
        (data.articles || []).forEach(function (a) {
            var aid = 'sa' + a.id;
            nodes.push({
                id: aid, type: 'article',
                label: a.title, summary: '',
                sub: a.feed || '', score: a.score || 0,
                imageUrl: '', url: a.url,
            });
            links.push({ source: 'c', target: aid });
        });

        return { nodes: nodes, links: links };
    }

    /* ── Canvas: wrap text ────────────────────────── */

    function wrapText(ctx, text, maxWidth) {
        var words = text.split(' ');
        var lines = [];
        var line = '';
        for (var i = 0; i < words.length; i++) {
            var test = line ? line + ' ' + words[i] : words[i];
            if (ctx.measureText(test).width > maxWidth && line) {
                lines.push(line);
                line = words[i];
            } else {
                line = test;
            }
        }
        if (line) lines.push(line);
        return lines;
    }

    /* ── Canvas: draw node card ──────────────────── */

    function computeLayout(node, ctx) {
        var t = node.type;
        var IMG_S = (t === 'center' || t === 'item') ? 42 : 0;
        var hasImg = IMG_S > 0 && node._img && node._img.complete && node._img.naturalWidth > 0;
        var imgW = hasImg ? IMG_S : 0;
        var STRIPE = 3;
        var PAD = 6;
        var TEXT_LEFT = STRIPE + (imgW || PAD);
        var CARD_W = t === 'center' ? 230 : t === 'item' ? 190 : 150;
        var TEXT_W = CARD_W - TEXT_LEFT - PAD - (hasImg ? PAD : 0);
        var titleSize = t === 'center' ? 9 : t === 'article' ? 6 : 7;

        ctx.font = '700 ' + titleSize + 'px "PT Serif", Georgia, serif';
        var titleLines = wrapText(ctx, node.label, TEXT_W);
        var maxLines = t === 'center' ? 3 : 2;
        if (titleLines.length > maxLines) {
            titleLines = titleLines.slice(0, maxLines);
            titleLines[maxLines - 1] += '\u2026';
        }
        var titleH = titleLines.length * titleSize * 1.35;

        var summaryLines = [];
        var summaryH = 0;
        if (node.summary && t === 'center') {
            ctx.font = '6px -apple-system, system-ui, sans-serif';
            summaryLines = wrapText(ctx, node.summary, TEXT_W);
            if (summaryLines.length > 2) summaryLines = summaryLines.slice(0, 2);
            summaryH = summaryLines.length * 7.8 + 2;
        }

        var subH = node.sub ? 9 : 0;
        var scoreH = node.score ? 9 : 0;
        var textH = PAD + titleH + summaryH + subH + scoreH + PAD;
        var CARD_H = Math.max(textH, imgW > 0 ? imgW : 0);

        var stripeColor = t === 'center' ? 'accent'
                        : t === 'item'   ? 'item'
                        :                  'fgMuted';

        return {
            CARD_W: CARD_W, CARD_H: CARD_H, STRIPE: STRIPE, PAD: PAD,
            IMG_S: IMG_S, hasImg: hasImg, imgW: imgW,
            TEXT_LEFT: TEXT_LEFT, titleSize: titleSize,
            titleLines: titleLines, titleH: titleH,
            summaryLines: summaryLines, stripeKey: stripeColor,
        };
    }

    function drawNode(node, ctx, globalScale, colors) {
        // Cache layout (recompute only if image loaded since last time)
        var imgReady = node._img && node._img.complete && node._img.naturalWidth > 0;
        if (!node._layout || (imgReady && !node._layout.hasImg)) {
            node._layout = computeLayout(node, ctx);
        }
        var L = node._layout;
        var t = node.type;

        var x = node.x - L.CARD_W / 2;
        var y = node.y - L.CARD_H / 2;

        // Background
        ctx.fillStyle = colors.bg;
        ctx.fillRect(x, y, L.CARD_W, L.CARD_H);

        // Left stripe
        var stripeColor = colors[L.stripeKey];
        ctx.fillStyle = stripeColor;
        ctx.fillRect(x, y, L.STRIPE, L.CARD_H);

        // Square image (cover-fit)
        if (L.hasImg) {
            ctx.save();
            ctx.beginPath();
            ctx.rect(x + L.STRIPE, y, L.IMG_S, L.CARD_H);
            ctx.clip();
            var ratio = node._img.naturalWidth / node._img.naturalHeight;
            var dw, dh;
            if (ratio > 1) { dh = L.CARD_H; dw = L.CARD_H * ratio; }
            else { dw = L.IMG_S; dh = L.IMG_S / ratio; }
            ctx.drawImage(node._img,
                x + L.STRIPE + (L.IMG_S - dw) / 2,
                y + (L.CARD_H - dh) / 2, dw, dh);
            ctx.restore();
        }

        // Border
        ctx.strokeStyle = t === 'center' ? colors.accent : colors.borderLight;
        ctx.lineWidth = t === 'center' ? 1.5 : 0.5;
        ctx.strokeRect(x, y, L.CARD_W, L.CARD_H);

        // Text
        var tx = x + L.TEXT_LEFT + (L.hasImg ? L.PAD : 0);
        var ty = y + L.PAD;

        ctx.font = '700 ' + L.titleSize + 'px "PT Serif", Georgia, serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillStyle = colors.fg;
        for (var i = 0; i < L.titleLines.length; i++) {
            ctx.fillText(L.titleLines[i], tx, ty);
            ty += L.titleSize * 1.35;
        }

        if (L.summaryLines.length) {
            ty += 2;
            ctx.font = '6px -apple-system, system-ui, sans-serif';
            ctx.fillStyle = colors.fgMuted;
            for (var j = 0; j < L.summaryLines.length; j++) {
                ctx.fillText(L.summaryLines[j], tx, ty);
                ty += 7.8;
            }
        }

        if (node.sub) {
            ctx.font = '5.5px -apple-system, system-ui, sans-serif';
            ctx.fillStyle = colors.fgFaint;
            ctx.fillText(truncate(node.sub, 35), tx, ty + 1);
            ty += 9;
        }

        if (node.score) {
            ctx.font = '700 6px -apple-system, system-ui, sans-serif';
            ctx.fillStyle = stripeColor;
            ctx.fillText(node.score + '%', tx, ty + 1);
        }

        node._bx = x;
        node._by = y;
        node._bw = L.CARD_W;
        node._bh = L.CARD_H;
    }

    /* ── Legend ───────────────────────────────────── */

    function legendItem(cls, text) {
        var wrap = el('div', 'similar-legend-item');
        wrap.appendChild(el('span', 'similar-legend-dot dot-' + cls));
        wrap.appendChild(el('span', null, text));
        return wrap;
    }

    /* ── Modal ───────────────────────────────────── */

    function createModal() {
        var overlay = el('div', 'similar-modal-overlay');
        var modal = el('div', 'similar-modal');

        var header = el('div', 'similar-modal-header');
        header.appendChild(el('div', 'similar-modal-title', bd('similarLabel', 'Similar news')));
        var closeBtn = el('button', 'similar-modal-close', '\u00d7');
        header.appendChild(closeBtn);
        modal.appendChild(header);

        var graphBox = el('div', 'similar-graph-container');
        modal.appendChild(graphBox);

        var legend = el('div', 'similar-modal-legend');
        legend.appendChild(legendItem('center', bd('similarCurrent', 'Current')));
        legend.appendChild(legendItem('item', bd('similarLabel', 'Similar news')));
        legend.appendChild(legendItem('article', bd('similarSources', 'Source articles')));
        modal.appendChild(legend);

        overlay.appendChild(modal);

        var fgInstance = null;
        var resizeFn = null;

        function close() {
            if (fgInstance) { fgInstance.pauseAnimation(); fgInstance = null; }
            if (resizeFn) { window.removeEventListener('resize', resizeFn); resizeFn = null; }
            overlay.remove();
        }

        closeBtn.onclick = close;
        overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
        document.addEventListener('keydown', function handler(e) {
            if (e.key === 'Escape') { close(); document.removeEventListener('keydown', handler); }
        });

        return {
            overlay: overlay,
            graphBox: graphBox,
            setFg: function (fg, onResize) { fgInstance = fg; resizeFn = onResize || null; },
        };
    }

    /* ── Render 2D DAG graph ─────────────────────── */

    function renderGraph(container, graph, modal) {
        // Preload images
        graph.nodes.forEach(function (n) {
            if (n.imageUrl) {
                var img = new Image();
                img.src = n.imageUrl;
                n._img = img;
            }
        });

        var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        var colors = {
            accent: cssVar('--accent'),
            fg: cssVar('--fg'),
            fgMuted: cssVar('--fg-muted'),
            fgFaint: cssVar('--fg-faint'),
            borderLight: cssVar('--border-light'),
            bg: cssVar('--bg'),
            item: isDark ? '#a8845c' : '#8b6e4e',
        };

        var fg = new ForceGraph()(container)
            .graphData({ nodes: graph.nodes, links: graph.links })
            .width(container.clientWidth)
            .height(container.clientHeight)
            .nodeId('id')
            .dagMode('lr')
            .dagLevelDistance(350)
            .nodeCanvasObject(function (node, ctx, gs) {
                drawNode(node, ctx, gs, colors);
            })
            .nodeCanvasObjectMode(function () { return 'replace'; })
            .nodePointerAreaPaint(function (node, color, ctx) {
                if (node._bw) {
                    ctx.fillStyle = color;
                    ctx.fillRect(node._bx, node._by, node._bw, node._bh);
                }
            })
            .linkWidth(1)
            .linkColor(function () { return isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.12)'; })
            .d3VelocityDecay(0.6)
            .onNodeClick(function (node) {
                if (node.url) window.location.href = node.url;
            })
            .onNodeHover(function (node) {
                container.style.cursor = node && node.url ? 'pointer' : 'default';
            })
            .cooldownTicks(0)
            .warmupTicks(100);

        // Strong repulsion to prevent card overlap
        fg.d3Force('charge').strength(-3000).distanceMax(600);

        // Zoom to fit after layout settles
        setTimeout(function () { fg.zoomToFit(400, 40); }, 1200);

        // Resize (cleaned up on modal close)
        var resizeTimer;
        function onResize() {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function () {
                fg.width(container.clientWidth).height(container.clientHeight);
            }, 100);
        }
        window.addEventListener('resize', onResize);

        modal.setFg(fg, onResize);
    }

    /* ── Show ────────────────────────────────────── */

    function show(centerInfo, data) {
        var graph = buildGraph(centerInfo, data);
        var m = createModal();
        document.body.appendChild(m.overlay);

        if (graph.nodes.length <= 1) {
            m.graphBox.appendChild(
                el('div', 'similar-modal-empty', bd('similarEmpty', 'No similar news found'))
            );
        } else {
            renderGraph(m.graphBox, graph, m);
        }
    }

    /* ── Fetch + launch ──────────────────────────── */

    function launch(itemId, centerInfo) {
        if (cache[itemId]) {
            show(centerInfo, cache[itemId]);
            return;
        }

        var m = createModal();
        m.graphBox.appendChild(el('div', 'similar-modal-loading', bd('similarLoading', 'Loading\u2026')));
        document.body.appendChild(m.overlay);

        fetch(API + itemId + '/similar/')
            .then(function (r) {
                if (!r.ok) throw new Error(r.status);
                return r.json();
            })
            .then(function (data) {
                cache[itemId] = data;
                m.overlay.remove();
                show(centerInfo, data);
            })
            .catch(function () {
                clearChildren(m.graphBox);
                m.graphBox.appendChild(el('div', 'similar-modal-empty', '\u2717 Error'));
            });
    }

    /* ── Click handler ───────────────────────────── */

    document.addEventListener('click', function (e) {
        var btn = e.target.closest('.similar-btn');
        if (!btn) return;
        e.preventDefault();

        if (typeof ForceGraph === 'undefined') return;

        var itemId = btn.dataset.itemId;
        var li = btn.closest('li');
        if (!li) return;

        var topicEl = li.querySelector('.item-topic');
        var summaryEl = li.querySelector('.item-summary');
        var imgEl = li.querySelector('.item-image');

        launch(itemId, {
            topic: topicEl ? topicEl.textContent.trim() : 'Item #' + itemId,
            summary: summaryEl ? summaryEl.textContent.trim() : '',
            imageUrl: imgEl ? imgEl.src : '',
        });
    });
})();
