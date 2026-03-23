/**
 * Similar news — 2D DAG tree (left → right).
 *
 * Level 0: current digest item (center)
 * Level 1: similar digest items + standalone articles
 * Level 2: articles of each similar digest item
 *
 * Connected nodes are pulled LEFT of center; root stays right.
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
            id: 'c', type: 'center', _level: 0,
            label: center.topic, summary: center.summary || '',
            imageUrl: center.imageUrl, score: 0, url: null, sub: '',
        }];
        var links = [];

        // Level 1: similar digest items → Level 2: their articles
        (data.items || []).forEach(function (d) {
            var nid = 'i' + d.id;
            nodes.push({
                id: nid, type: 'item', _level: 1,
                label: d.topic, summary: d.summary || '',
                sub: d.section + ' \u00b7 ' + d.date,
                score: d.score || 0,
                imageUrl: d.image_url || '', url: d.deep_dive_url,
            });
            links.push({ source: 'c', target: nid });

            (d.articles || []).forEach(function (a) {
                var aid = 'a' + a.id + '_' + d.id;
                nodes.push({
                    id: aid, type: 'article', _level: 2,
                    label: a.title, summary: '',
                    sub: a.feed || '', score: 0,
                    imageUrl: a.image_url || '', url: a.url,
                });
                links.push({ source: nid, target: aid });
            });
        });

        // Level 1: standalone similar articles (no digest item)
        (data.articles || []).forEach(function (a) {
            var aid = 'sa' + a.id;
            nodes.push({
                id: aid, type: 'article', _level: 1,
                label: a.title, summary: '',
                sub: a.feed || '', score: a.score || 0,
                imageUrl: a.image_url || '', url: a.url,
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
        var hasImg = node._img && node._img.complete && node._img.naturalWidth > 0;
        var IMG_MIN = t === 'center' ? 56 : t === 'item' ? 42 : 32;
        var STRIPE = t === 'center' ? 4 : 3;
        var PAD = t === 'center' ? 8 : 6;
        // First pass: compute text height with estimated text width
        var CARD_W = t === 'center' ? 280 : t === 'item' ? 210 : 160;
        var TEXT_LEFT_EST = STRIPE + IMG_MIN + PAD;
        var TEXT_W = CARD_W - TEXT_LEFT_EST - PAD;
        var titleSize = t === 'center' ? 11 : t === 'item' ? 8 : 6.5;

        ctx.font = '700 ' + titleSize + 'px "PT Serif", Georgia, serif';
        var titleLines = wrapText(ctx, node.label, TEXT_W);
        var maxLines = t === 'center' ? 4 : t === 'item' ? 3 : 2;
        if (titleLines.length > maxLines) {
            titleLines = titleLines.slice(0, maxLines);
            titleLines[maxLines - 1] += '\u2026';
        }
        var titleH = titleLines.length * titleSize * 1.35;

        var summaryLines = [];
        var summaryH = 0;
        if (node.summary && (t === 'center' || t === 'item')) {
            var sumSize = t === 'center' ? 7 : 6;
            var sumMax = t === 'center' ? 3 : 2;
            ctx.font = sumSize + 'px -apple-system, system-ui, sans-serif';
            summaryLines = wrapText(ctx, node.summary, TEXT_W);
            if (summaryLines.length > sumMax) summaryLines = summaryLines.slice(0, sumMax);
            summaryH = summaryLines.length * (sumSize * 1.3) + 2;
        }

        var subH = node.sub ? (t === 'center' ? 11 : 9) : 0;
        var scoreH = node.score ? (t === 'center' ? 11 : 9) : 0;
        var textH = PAD + titleH + summaryH + subH + scoreH + PAD;
        // Image is a square that fills the full card height
        var CARD_H = Math.max(textH, IMG_MIN);
        var IMG_S = CARD_H;
        var TEXT_LEFT = STRIPE + IMG_S + PAD;
        CARD_W = TEXT_LEFT + TEXT_W + PAD;

        var stripeColor = t === 'center' ? 'accent'
                        : t === 'item'   ? 'item'
                        :                  'fgMuted';

        return {
            CARD_W: CARD_W, CARD_H: CARD_H, STRIPE: STRIPE, PAD: PAD,
            IMG_S: IMG_S, hasImg: hasImg,
            TEXT_LEFT: TEXT_LEFT, titleSize: titleSize,
            titleLines: titleLines, titleH: titleH,
            summaryLines: summaryLines, summarySize: node.summary ? (t === 'center' ? 7 : 6) : 0,
            stripeKey: stripeColor,
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

        // Square image: full card height
        var imgX = x + L.STRIPE;
        var imgY = y;
        if (L.hasImg) {
            ctx.save();
            ctx.beginPath();
            ctx.rect(imgX, imgY, L.IMG_S, L.IMG_S);
            ctx.clip();
            var ratio = node._img.naturalWidth / node._img.naturalHeight;
            var dw, dh;
            if (ratio > 1) { dh = L.IMG_S; dw = L.IMG_S * ratio; }
            else { dw = L.IMG_S; dh = L.IMG_S / ratio; }
            ctx.drawImage(node._img,
                imgX + (L.IMG_S - dw) / 2,
                imgY + (L.IMG_S - dh) / 2, dw, dh);
            ctx.restore();
        } else {
            // Placeholder: tinted square + doc icon
            ctx.fillStyle = colors.borderLight;
            ctx.fillRect(imgX, imgY, L.IMG_S, L.IMG_S);
            var iconSize = L.IMG_S * 0.38;
            var cx = imgX + L.IMG_S / 2;
            var cy = imgY + L.IMG_S / 2;
            ctx.strokeStyle = colors.fgFaint;
            ctx.lineWidth = 0.8;
            var hw = iconSize * 0.4, hh = iconSize * 0.5;
            ctx.strokeRect(cx - hw, cy - hh, hw * 2, hh * 2);
            ctx.beginPath();
            ctx.moveTo(cx - hw + 2, cy - hh * 0.2);
            ctx.lineTo(cx + hw - 2, cy - hh * 0.2);
            ctx.moveTo(cx - hw + 2, cy + hh * 0.3);
            ctx.lineTo(cx + hw - 2, cy + hh * 0.3);
            ctx.stroke();
        }

        // Border
        ctx.strokeStyle = t === 'center' ? colors.accent : colors.borderLight;
        ctx.lineWidth = t === 'center' ? 2 : t === 'item' ? 0.8 : 0.5;
        ctx.strokeRect(x, y, L.CARD_W, L.CARD_H);

        // Text
        var tx = x + L.TEXT_LEFT;
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
            ctx.font = L.summarySize + 'px -apple-system, system-ui, sans-serif';
            ctx.fillStyle = colors.fgMuted;
            for (var j = 0; j < L.summaryLines.length; j++) {
                ctx.fillText(L.summaryLines[j], tx, ty);
                ty += L.summarySize * 1.3;
            }
        }

        if (node.sub) {
            var subSize = t === 'center' ? 7 : t === 'item' ? 6 : 5.5;
            ctx.font = subSize + 'px -apple-system, system-ui, sans-serif';
            ctx.fillStyle = colors.fgFaint;
            ctx.fillText(truncate(node.sub, 40), tx, ty + 1);
            ty += t === 'center' ? 11 : 9;
        }

        if (node.score) {
            var scoreSize = t === 'center' ? 8 : t === 'item' ? 7 : 6;
            ctx.font = '700 ' + scoreSize + 'px -apple-system, system-ui, sans-serif';
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
            .cooldownTicks(200)
            .warmupTicks(150);

        // Strong repulsion to prevent card overlap
        fg.d3Force('charge').strength(-3000).distanceMax(600);

        // Link preferred distance (matches level spacing)
        fg.d3Force('link').distance(350);

        // Pull connected nodes LEFT: center stays right, items middle, articles far-left
        fg.d3Force('levelX', (function () {
            var nodes;
            function force(alpha) {
                for (var i = 0; i < nodes.length; i++) {
                    var n = nodes[i];
                    var tx = n._level === 0 ? 0 : n._level === 1 ? -350 : -700;
                    n.vx += (tx - n.x) * 0.12 * alpha;
                }
            }
            force.initialize = function (_) { nodes = _; };
            return force;
        })());

        // Continuous zoom-to-fit while simulation runs, then once more when it stops
        fg.onEngineTick(function () { fg.zoomToFit(0, 40); });
        fg.onEngineStop(function () { fg.zoomToFit(400, 40); });

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
            // Let the browser paint the modal+blur first, then init the heavy graph
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    renderGraph(m.graphBox, graph, m);
                });
            });
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
