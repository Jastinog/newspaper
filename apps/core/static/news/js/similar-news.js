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
    var FORCE_GRAPH_URL = 'https://cdn.jsdelivr.net/npm/force-graph/dist/force-graph.min.js';
    var _fgLoading = null;

    function ensureForceGraph(cb) {
        if (typeof ForceGraph !== 'undefined') return cb();
        if (_fgLoading) return _fgLoading.then(cb);
        _fgLoading = new Promise(function (resolve, reject) {
            var s = document.createElement('script');
            s.src = FORCE_GRAPH_URL;
            s.onload = resolve;
            s.onerror = reject;
            document.head.appendChild(s);
        });
        _fgLoading.then(cb);
    }

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

    function pushArticleNode(nodes, links, a, id, type, level, linkSrc, score) {
        var parts = [];
        if (a.feed) parts.push(a.feed);
        if (a.date) parts.push(a.date.slice(0, 10));
        nodes.push({
            id: id, type: type, _level: level,
            label: a.title, summary: '',
            sub: parts.join(' \u00b7 '), score: score,
            imageUrl: a.image_url || '', url: a.url,
        });
        links.push({ source: linkSrc, target: id });
    }

    function buildGraph(center, data) {
        var nodes = [{
            id: 'c', type: 'center', _level: 0,
            label: center.topic, summary: center.summary || '',
            imageUrl: center.imageUrl, score: 0, url: center.storyUrl || null, sub: '',
        }];
        var links = [];

        (data.items || []).forEach(function (d) {
            var nid = 'i' + d.id;
            nodes.push({
                id: nid, type: 'item', _level: 1,
                label: d.topic, summary: d.summary || '',
                sub: d.section + ' \u00b7 ' + d.date,
                score: d.score || 0,
                imageUrl: d.image_url || '', url: d.research_url,
            });
            links.push({ source: 'c', target: nid });

            (d.articles || []).forEach(function (a) {
                pushArticleNode(nodes, links, a, 'a' + a.id + '_' + d.id, 'article', 2, nid, a.score || 0);
            });
        });

        (data.sources || []).forEach(function (a) {
            pushArticleNode(nodes, links, a, 'src' + a.id, 'source', -1, 'c', 0);
        });

        (data.articles || []).forEach(function (a) {
            pushArticleNode(nodes, links, a, 'sa' + a.id, 'article', 1, 'c', a.score || 0);
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

    /* ── Per-type sizing constants ────────────────── */

    var SIZES = {
        center:  { cardW: 360, imgMin: 72, stripe: 5, pad: 10, titlePx: 14, maxTitle: 4, sumPx: 9, maxSum: 3, subPx: 8, scorePx: 9, metaH: 13, borderW: 2.5, stripeKey: 'accent'  },
        item:    { cardW: 210, imgMin: 42, stripe: 3, pad: 6, titlePx:  8, maxTitle: 3, sumPx: 6, maxSum: 2, subPx: 6, scorePx: 7, metaH:  9, borderW: 0.8, stripeKey: 'item'   },
        article: { cardW: 160, imgMin: 32, stripe: 3, pad: 6, titlePx: 6.5, maxTitle: 2, sumPx: 0, maxSum: 0, subPx: 5.5, scorePx: 7, metaH: 10, borderW: 0.5, stripeKey: 'fgMuted' },
        source:  { cardW: 140, imgMin: 28, stripe: 2, pad: 5, titlePx: 6, maxTitle: 2, sumPx: 0, maxSum: 0, subPx: 5, scorePx: 6, metaH: 9, borderW: 0.6, stripeKey: 'source' },
    };

    /* ── Canvas: compute node card layout ─────────── */

    function computeLayout(node, ctx) {
        var S = SIZES[node.type];
        var hasImg = node._img && node._img.complete && node._img.naturalWidth > 0;

        // Estimate text width from card width minus image + padding
        var textLeftEst = S.stripe + S.imgMin + S.pad;
        var textW = S.cardW - textLeftEst - S.pad;

        ctx.font = '700 ' + S.titlePx + 'px "PT Serif", Georgia, serif';
        var titleLines = wrapText(ctx, node.label, textW);
        if (titleLines.length > S.maxTitle) {
            titleLines = titleLines.slice(0, S.maxTitle);
            titleLines[S.maxTitle - 1] += '\u2026';
        }
        var titleH = titleLines.length * S.titlePx * 1.35;

        var summaryLines = [];
        var summaryH = 0;
        if (node.summary && S.sumPx > 0) {
            ctx.font = S.sumPx + 'px -apple-system, system-ui, sans-serif';
            summaryLines = wrapText(ctx, node.summary, textW);
            if (summaryLines.length > S.maxSum) summaryLines = summaryLines.slice(0, S.maxSum);
            summaryH = summaryLines.length * (S.sumPx * 1.3) + 2;
        }

        var subH = node.sub ? S.metaH : 0;
        var scoreH = node.score ? S.metaH : 0;
        var textH = S.pad + titleH + summaryH + subH + scoreH + S.pad;

        // Image is a square that fills the full card height
        var cardH = Math.max(textH, S.imgMin);
        var imgS = cardH;
        var textLeft = S.stripe + imgS + S.pad;
        var cardW = textLeft + textW + S.pad;

        return {
            S: S, cardW: cardW, cardH: cardH, imgS: imgS, hasImg: hasImg,
            textLeft: textLeft, titleLines: titleLines, titleH: titleH,
            summaryLines: summaryLines,
        };
    }

    function drawNode(node, ctx, globalScale, colors) {
        // Cache layout (recompute only if image loaded since last time)
        var imgReady = node._img && node._img.complete && node._img.naturalWidth > 0;
        if (!node._layout || (imgReady && !node._layout.hasImg)) {
            node._layout = computeLayout(node, ctx);
        }
        var L = node._layout;
        var S = L.S;

        var x = node.x - L.cardW / 2;
        var y = node.y - L.cardH / 2;

        // Background
        ctx.fillStyle = colors.bg;
        ctx.fillRect(x, y, L.cardW, L.cardH);

        // Left stripe
        var stripeColor = colors[S.stripeKey];
        ctx.fillStyle = stripeColor;
        ctx.fillRect(x, y, S.stripe, L.cardH);

        // Square image: full card height
        var imgX = x + S.stripe;
        var imgY = y;
        if (L.hasImg) {
            ctx.save();
            ctx.beginPath();
            ctx.rect(imgX, imgY, L.imgS, L.imgS);
            ctx.clip();
            var ratio = node._img.naturalWidth / node._img.naturalHeight;
            var dw, dh;
            if (ratio > 1) { dh = L.imgS; dw = L.imgS * ratio; }
            else { dw = L.imgS; dh = L.imgS / ratio; }
            ctx.drawImage(node._img,
                imgX + (L.imgS - dw) / 2,
                imgY + (L.imgS - dh) / 2, dw, dh);
            ctx.restore();
        } else {
            // Placeholder: tinted square + doc icon
            ctx.fillStyle = colors.borderLight;
            ctx.fillRect(imgX, imgY, L.imgS, L.imgS);
            var iconSize = L.imgS * 0.38;
            var cx = imgX + L.imgS / 2;
            var cy = imgY + L.imgS / 2;
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

        // Border color matches the left stripe
        ctx.strokeStyle = stripeColor;
        ctx.lineWidth = S.borderW;
        ctx.strokeRect(x, y, L.cardW, L.cardH);

        // Text
        var tx = x + L.textLeft;
        var ty = y + S.pad;

        ctx.font = '700 ' + S.titlePx + 'px "PT Serif", Georgia, serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'top';
        ctx.fillStyle = colors.fg;
        for (var i = 0; i < L.titleLines.length; i++) {
            ctx.fillText(L.titleLines[i], tx, ty);
            ty += S.titlePx * 1.35;
        }

        if (L.summaryLines.length) {
            ty += 2;
            ctx.font = S.sumPx + 'px -apple-system, system-ui, sans-serif';
            ctx.fillStyle = colors.fgMuted;
            for (var j = 0; j < L.summaryLines.length; j++) {
                ctx.fillText(L.summaryLines[j], tx, ty);
                ty += S.sumPx * 1.3;
            }
        }

        if (node.sub) {
            ctx.font = S.subPx + 'px -apple-system, system-ui, sans-serif';
            ctx.fillStyle = colors.fgFaint;
            ctx.fillText(truncate(node.sub, 40), tx, ty + 1);
            ty += S.metaH;
        }

        if (node.score) {
            ctx.font = '700 ' + S.scorePx + 'px -apple-system, system-ui, sans-serif';
            ctx.fillStyle = colors.accent;
            ctx.fillText(node.score + '%', tx, ty + 1);
        }

        // Store clickable areas: image + title
        node._imgBox = { x: imgX, y: imgY, w: L.imgS, h: L.cardH };
        node._titleBox = { x: x + L.textLeft, y: y + S.pad, w: L.cardW - L.textLeft - S.pad, h: L.titleLines.length * S.titlePx * 1.35 };

        node._bx = x;
        node._by = y;
        node._bw = L.cardW;
        node._bh = L.cardH;
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
        legend.appendChild(legendItem('source', bd('similarSources', 'Source articles')));
        legend.appendChild(legendItem('center', bd('similarCurrent', 'Current')));
        legend.appendChild(legendItem('item', bd('similarDigest', 'Digest news')));
        legend.appendChild(legendItem('article', bd('similarArticles', 'Articles')));
        modal.appendChild(legend);

        overlay.appendChild(modal);

        var fgInstance = null;
        var resizeFn = null;

        function onKey(e) {
            if (e.key === 'Escape') close();
        }

        function close() {
            if (fgInstance) { fgInstance.pauseAnimation(); fgInstance = null; }
            if (resizeFn) { window.removeEventListener('resize', resizeFn); resizeFn = null; }
            document.removeEventListener('keydown', onKey);
            overlay.remove();
        }

        closeBtn.onclick = close;
        overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
        document.addEventListener('keydown', onKey);

        return {
            overlay: overlay,
            graphBox: graphBox,
            reveal: function () { overlay.classList.add('ready'); },
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

        // Pre-calculate initial positions so graph starts in structured layout
        var LEVEL_X = { '-1': 500, '0': 0, '1': -500, '2': -900 };
        var VERT_SPACING = 180;
        var byLevel = {};
        graph.nodes.forEach(function (n) {
            var lvl = n._level;
            if (!byLevel[lvl]) byLevel[lvl] = [];
            byLevel[lvl].push(n);
        });
        Object.keys(byLevel).forEach(function (lvl) {
            var group = byLevel[lvl];
            var totalH = (group.length - 1) * VERT_SPACING;
            group.forEach(function (n, idx) {
                n.x = LEVEL_X[n._level] || 0;
                n.y = -totalH / 2 + idx * VERT_SPACING;
            });
        });

        var isDark = document.documentElement.getAttribute('data-scheme') === 'dark';
        var colors = {
            accent: isDark ? '#d4a24e' : '#b8862a',
            fg: cssVar('--fg'),
            fgMuted: isDark ? '#7a8fa3' : '#5a6a7a',
            fgFaint: cssVar('--fg-faint'),
            borderLight: cssVar('--border-light'),
            bg: cssVar('--bg'),
            item: isDark ? '#c47a6c' : '#a35d4f',
            source: isDark ? '#5bab9e' : '#3a8a7d',
        };

        // 4 distinct link colors by relationship type
        var linkStyles = {
            centerSource:  isDark ? 'rgba(77,184,164,0.55)'  : 'rgba(58,150,134,0.5)',    // mint
            centerItem:    isDark ? 'rgba(224,168,50,0.55)'   : 'rgba(190,140,36,0.5)',    // yellow
            centerArticle: isDark ? 'rgba(107,143,196,0.55)'  : 'rgba(80,116,168,0.5)',    // blue
            itemArticle:   isDark ? 'rgba(212,122,122,0.55)'  : 'rgba(180,94,94,0.5)',     // pink
        };

        function linkColorByRelation(link) {
            var s = link.source;
            var t = link.target;
            var sType = (typeof s === 'object') ? s.type : '';
            var tType = (typeof t === 'object') ? t.type : '';
            if (tType === 'source') return linkStyles.centerSource;
            if (sType === 'center' && tType === 'item') return linkStyles.centerItem;
            if (sType === 'center' && tType === 'article') return linkStyles.centerArticle;
            if (sType === 'item' && tType === 'article') return linkStyles.itemArticle;
            return linkStyles.centerItem;
        }

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
            .linkWidth(1.2)
            .linkColor(linkColorByRelation)
            .linkCurvature(0)
            .linkDirectionalArrowLength(6)
            .linkDirectionalArrowRelPos(1)
            .linkDirectionalArrowColor(linkColorByRelation)
            .d3VelocityDecay(0.85)
            .d3AlphaDecay(0.1)
            .onNodeClick(function (node, event) {
                if (!node.url) return;
                var rect = container.querySelector('canvas').getBoundingClientRect();
                var pt = fg.screen2GraphCoords(event.clientX - rect.left, event.clientY - rect.top);
                function hitBox(b) {
                    return b && pt.x >= b.x && pt.x <= b.x + b.w && pt.y >= b.y && pt.y <= b.y + b.h;
                }
                if (hitBox(node._imgBox) || hitBox(node._titleBox)) {
                    window.location.href = node.url;
                }
            })
            .onNodeHover(function (node, prevNode) {
                container.style.cursor = node ? 'grab' : 'default';
            })
            .onNodeDrag(function (node) {
                node.fx = node.x;
                node.fy = node.y;
            })
            .onNodeDragEnd(function (node) {
                node.fx = undefined;
                node.fy = undefined;
            })
            .cooldownTicks(60)
            .warmupTicks(150);

        // Moderate repulsion to prevent card overlap
        fg.d3Force('charge').strength(-2000).distanceMax(500);

        // Link preferred distance
        fg.d3Force('link').distance(250);

        // Structured column layout: sources → center → items → articles
        fg.d3Force('levelX', (function () {
            var nodes;
            function force(alpha) {
                // Group nodes by level for vertical distribution
                var byLevel = {};
                for (var i = 0; i < nodes.length; i++) {
                    var lvl = nodes[i]._level;
                    if (!byLevel[lvl]) byLevel[lvl] = [];
                    byLevel[lvl].push(nodes[i]);
                }

                for (var i = 0; i < nodes.length; i++) {
                    var n = nodes[i];
                    var tx = LEVEL_X[n._level] || 0;

                    // Strong horizontal pull to keep columns strict
                    n.vx += (tx - n.x) * 0.5 * alpha;

                    // Vertical spread: distribute evenly within each column
                    var group = byLevel[n._level];
                    if (group.length > 1) {
                        var idx = group.indexOf(n);
                        var spacing = 180;
                        var totalH = (group.length - 1) * spacing;
                        var ty = -totalH / 2 + idx * spacing;
                        n.vy += (ty - n.y) * 0.15 * alpha;
                    } else {
                        // Single node in column — pull to vertical center
                        n.vy += (0 - n.y) * 0.15 * alpha;
                    }
                }
            }
            force.initialize = function (_) { nodes = _; };
            return force;
        })());

        // Reveal modal once graph has warmed up and first frame is painted
        var revealed = false;

        // Zoom-to-fit once on first frame, then smoothly when simulation stops
        fg.onEngineTick(function () {
            if (!revealed) {
                revealed = true;
                fg.zoomToFit(0, 40);
                modal.reveal();
            }
        });
        fg.onEngineStop(function () { fg.zoomToFit(300, 40); });

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

    /* ── Populate modal with graph or empty message ─ */

    function populateGraph(m, centerInfo, data) {
        clearChildren(m.graphBox);
        var graph = buildGraph(centerInfo, data);
        if (graph.nodes.length <= 1) {
            m.graphBox.appendChild(
                el('div', 'similar-modal-empty', bd('similarEmpty', 'No similar news found'))
            );
            m.reveal();
        } else {
            renderGraph(m.graphBox, graph, m);
        }
    }

    /* ── Fetch + launch ──────────────────────────── */

    function launch(itemId, centerInfo) {
        var m = createModal();
        document.body.appendChild(m.overlay);

        if (cache[itemId]) {
            populateGraph(m, centerInfo, cache[itemId]);
            return;
        }

        m.graphBox.appendChild(el('div', 'similar-modal-loading', bd('similarLoading', 'Loading\u2026')));
        m.reveal();

        fetch(API + itemId + '/similar/')
            .then(function (r) {
                if (!r.ok) throw new Error(r.status);
                return r.json();
            })
            .then(function (data) {
                cache[itemId] = data;
                populateGraph(m, centerInfo, data);
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

        var itemId = btn.dataset.itemId;
        var container = btn.closest('li') || btn.closest('.story-detail');
        if (!container) return;

        var topicEl = container.querySelector('.item-topic') || container.querySelector('h1');
        var summaryEl = container.querySelector('.item-summary') || container.querySelector('.article-content p');
        var imgEl = container.querySelector('.item-image') || container.querySelector('.story-hero img');

        var centerInfo = {
            topic: topicEl ? topicEl.textContent.trim() : 'Item #' + itemId,
            summary: summaryEl ? summaryEl.textContent.trim() : '',
            imageUrl: imgEl ? imgEl.src : '',
            storyUrl: (topicEl && topicEl.href) || window.location.pathname,
        };

        ensureForceGraph(function () { launch(itemId, centerInfo); });
    });
})();
