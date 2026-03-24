/**
 * Traffic tree — hierarchical visitor view for admin analytics.
 *
 * Country → City → Client (collapsible, sorted by session count)
 */
(function () {
    'use strict';

    var API = '/analytics/api/traffic-graph/';
    var cachedData = null;

    /* ── Helpers ─────────────────────────────────── */

    function el(tag, cls) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        return e;
    }

    function clearEl(parent) {
        while (parent.firstChild) parent.removeChild(parent.firstChild);
    }

    function emptyMsg(parent, text) {
        clearEl(parent);
        var d = el('div', 'tg-empty');
        d.textContent = text;
        parent.appendChild(d);
    }

    function toggle(head, body) {
        var collapsed = body.classList.toggle('tg-collapsed');
        head.querySelector('.tg-chevron').textContent = collapsed ? '\u25b8' : '\u25be';
    }

    /* ── Build tree DOM ─────────────────────────── */

    function buildTree(container, data, opts) {
        clearEl(container);
        var countries = data.countries || [];
        if (!countries.length) { emptyMsg(container, 'No visitor data'); return; }

        var wrapper = el('div', 'tg-tree');
        if (opts && opts.fullscreen) wrapper.classList.add('tg-tree--fs');

        countries.forEach(function (co) {
            var coNode = el('div', 'tg-node tg-node--country');

            /* — country header — */
            var coHead = el('div', 'tg-head tg-head--country');
            var chevron = el('span', 'tg-chevron');
            chevron.textContent = '\u25be';
            coHead.appendChild(chevron);

            var flag = el('span', 'tg-flag');
            flag.textContent = co.flag;
            coHead.appendChild(flag);

            var name = el('span', 'tg-name');
            name.textContent = co.name;
            coHead.appendChild(name);

            var counts = el('span', 'tg-counts');
            var pill1 = el('span', 'tg-pill tg-pill--blue');
            pill1.textContent = co.sc + ' sess';
            var pill2 = el('span', 'tg-pill tg-pill--dim');
            pill2.textContent = co.cc + (co.cc === 1 ? ' city' : ' cities');
            counts.appendChild(pill1);
            counts.appendChild(pill2);
            coHead.appendChild(counts);

            /* — country body (expanded by default) — */
            var coBody = el('div', 'tg-body');

            (co.cities || []).forEach(function (ci) {
                var ciNode = el('div', 'tg-node tg-node--city');

                var ciHead = el('div', 'tg-head tg-head--city');
                var ciChev = el('span', 'tg-chevron');
                ciChev.textContent = '\u25b8';
                ciHead.appendChild(ciChev);

                var ciName = el('span', 'tg-name');
                ciName.textContent = ci.name;
                ciHead.appendChild(ciName);

                var ciCounts = el('span', 'tg-counts');
                var ciP1 = el('span', 'tg-pill tg-pill--teal');
                ciP1.textContent = ci.sc + ' sess';
                var ciP2 = el('span', 'tg-pill tg-pill--dim');
                ciP2.textContent = ci.cc + (ci.cc === 1 ? ' visitor' : ' visitors');
                ciCounts.appendChild(ciP1);
                ciCounts.appendChild(ciP2);
                ciHead.appendChild(ciCounts);

                /* — city body (collapsed by default) — */
                var ciBody = el('div', 'tg-body tg-collapsed');

                (ci.clients || []).forEach(function (c) {
                    var leaf = el(c.url ? 'a' : 'div', 'tg-leaf');
                    if (c.url) { leaf.href = c.url; leaf.target = '_blank'; }

                    var dot = el('span', 'tg-dot');
                    leaf.appendChild(dot);

                    var info = el('span', 'tg-leaf-info');
                    var title = el('span', 'tg-leaf-title');
                    title.textContent = c.browser + ' \u00b7 ' + c.os;
                    var device = el('span', 'tg-leaf-device');
                    device.textContent = c.device;
                    info.appendChild(title);
                    info.appendChild(device);
                    leaf.appendChild(info);

                    var stats = el('span', 'tg-leaf-stats');
                    var s1 = el('span', 'tg-stat');
                    s1.textContent = c.sc + ' sess';
                    var s2 = el('span', 'tg-stat');
                    s2.textContent = c.time;
                    var s3 = el('span', 'tg-stat');
                    s3.textContent = c.pages + ' pg';
                    stats.appendChild(s1);
                    stats.appendChild(s2);
                    stats.appendChild(s3);
                    leaf.appendChild(stats);

                    ciBody.appendChild(leaf);
                });

                ciHead.addEventListener('click', function () { toggle(ciHead, ciBody); });

                ciNode.appendChild(ciHead);
                ciNode.appendChild(ciBody);
                coBody.appendChild(ciNode);
            });

            coHead.addEventListener('click', function () { toggle(coHead, coBody); });

            coNode.appendChild(coHead);
            coNode.appendChild(coBody);
            wrapper.appendChild(coNode);
        });

        container.appendChild(wrapper);
    }

    /* ── Fullscreen modal ───────────────────────── */

    function openFullscreen() {
        var overlay = el('div', 'tg-overlay');

        var header = el('div', 'tg-fs-header');
        var title = el('span', 'tg-fs-title');
        title.textContent = 'Visitor Sessions';
        var closeBtn = el('button', 'tg-fs-close');
        closeBtn.textContent = '\u00d7';
        header.appendChild(title);
        header.appendChild(closeBtn);
        overlay.appendChild(header);

        var box = el('div', 'tg-fs-box');
        overlay.appendChild(box);

        document.body.appendChild(overlay);

        function close() {
            document.removeEventListener('keydown', onKey);
            overlay.remove();
        }
        function onKey(e) { if (e.key === 'Escape') close(); }

        closeBtn.onclick = close;
        overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
        document.addEventListener('keydown', onKey);

        requestAnimationFrame(function () {
            overlay.classList.add('tg-ready');
            buildTree(box, cachedData, { fullscreen: true });
        });
    }

    /* ── Init ─────────────────────────────────────── */

    function init() {
        var container = document.getElementById('traffic-graph-container');
        if (!container) return;

        fetch(API)
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
            .then(function (data) {
                cachedData = data;
                var loading = document.getElementById('traffic-graph-loading');
                if (loading) loading.remove();

                buildTree(container, data);

                var fsBtn = document.getElementById('traffic-graph-fullscreen');
                if (fsBtn) fsBtn.addEventListener('click', openFullscreen);
            })
            .catch(function (err) {
                console.error('Traffic graph:', err);
                var e = document.getElementById('traffic-graph-loading');
                if (e) e.textContent = '\u2717 Error loading data';
            });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else { init(); }
})();
