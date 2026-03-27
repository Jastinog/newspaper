/**
 * Unified WebSocket client.
 *
 * Single connection to /ws/ handles:
 *   - Analytics tracking (sessions, page views, scroll, clicks, heartbeat)
 *   - Deep dive generation progress
 *   - Any future real-time features
 *
 * Public API:
 *   WS.on(type, handler)   — listen for server messages by type
 *   WS.send(action, data)  — send action to server
 *   WS.isConnected()       — check connection state
 */
(function () {
    'use strict';

    // ── Config ─────────────────────────────────────
    var STORAGE_KEY = 'newspaper_client_id';
    var HEARTBEAT_INTERVAL = 30000;
    var SCROLL_THROTTLE = 2000;
    var CLICK_THROTTLE = 500;

    // ── WS State ───────────────────────────────────
    var handlers = {};
    var ws = null;
    var reconnectDelay = 2000;
    var maxReconnectDelay = 30000;
    var currentDelay = reconnectDelay;

    // ── Analytics State ────────────────────────────
    var clientId = null;
    var heartbeatTimer = null;
    var activeTime = 0;
    var lastActiveTimestamp = null;
    var isPageVisible = true;
    var hasInteraction = false;
    var currentPath = location.pathname;
    var maxScrollDepth = 0;
    var lastScrollSend = 0;
    var lastClickSend = 0;

    // ── Client ID ──────────────────────────────────
    function getClientId() {
        var id = localStorage.getItem(STORAGE_KEY);
        if (id) return id;
        id = crypto.randomUUID ? crypto.randomUUID() : generateUUID();
        localStorage.setItem(STORAGE_KEY, id);
        return id;
    }

    function generateUUID() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
            var r = Math.random() * 16 | 0;
            return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
        });
    }

    // ── Connection ─────────────────────────────────
    var url = (location.protocol === 'https:' ? 'wss:' : 'ws:')
        + '//' + location.host + '/ws/';

    function connect() {
        ws = new WebSocket(url);

        ws.onopen = function () {
            currentDelay = reconnectDelay;
            dispatch('ws.open', {});

            // Analytics: identify client (includes first page view)
            send('analytics.init', {
                client_id: clientId,
                path: location.pathname,
                referrer: document.referrer || ''
            });
            currentPath = location.pathname;
            maxScrollDepth = 0;

            startHeartbeat();
        };

        ws.onmessage = function (evt) {
            var msg;
            try { msg = JSON.parse(evt.data); } catch (e) { return; }
            if (msg.type) dispatch(msg.type, msg);
        };

        ws.onclose = function () {
            ws = null;
            dispatch('ws.close', {});
            stopHeartbeat();
            setTimeout(connect, currentDelay);
            currentDelay = Math.min(currentDelay * 1.5, maxReconnectDelay);
        };

        ws.onerror = function () { /* onclose will fire next */ };
    }

    // ── Message dispatch ───────────────────────────
    function dispatch(type, msg) {
        var list = handlers[type];
        if (!list) return;
        for (var i = 0; i < list.length; i++) list[i](msg);
    }

    function on(type, fn) {
        if (!handlers[type]) handlers[type] = [];
        handlers[type].push(fn);
    }

    function send(action, data) {
        if (!ws || ws.readyState !== WebSocket.OPEN) return false;
        var msg = { action: action };
        if (data) {
            var keys = Object.keys(data);
            for (var i = 0; i < keys.length; i++) msg[keys[i]] = data[keys[i]];
        }
        ws.send(JSON.stringify(msg));
        return true;
    }

    function isConnected() {
        return ws && ws.readyState === WebSocket.OPEN;
    }

    // ── Active time tracking ───────────────────────
    function startActive() {
        if (!lastActiveTimestamp && isPageVisible) {
            lastActiveTimestamp = Date.now();
        }
    }

    function pauseActive() {
        if (lastActiveTimestamp) {
            activeTime += Math.round((Date.now() - lastActiveTimestamp) / 1000);
            lastActiveTimestamp = null;
        }
    }

    // ── Heartbeat ──────────────────────────────────
    function startHeartbeat() {
        stopHeartbeat();
        heartbeatTimer = setInterval(flushHeartbeat, HEARTBEAT_INTERVAL);
    }

    function stopHeartbeat() {
        if (heartbeatTimer) {
            clearInterval(heartbeatTimer);
            heartbeatTimer = null;
        }
    }

    function flushHeartbeat() {
        if (lastActiveTimestamp) {
            activeTime += Math.round((Date.now() - lastActiveTimestamp) / 1000);
            lastActiveTimestamp = isPageVisible ? Date.now() : null;
        }
        send('analytics.heartbeat', {
            active_time: activeTime,
            has_interaction: hasInteraction
        });
    }

    // ── Interaction tracking ───────────────────────
    function onInteraction() {
        if (!hasInteraction) hasInteraction = true;
        startActive();
    }

    function onScroll() {
        onInteraction();
        var now = Date.now();
        if (now - lastScrollSend < SCROLL_THROTTLE) return;
        lastScrollSend = now;

        var docHeight = Math.max(
            document.body.scrollHeight,
            document.documentElement.scrollHeight
        );
        var viewportHeight = window.innerHeight;
        var scrollTop = window.scrollY || document.documentElement.scrollTop;
        var depth = docHeight > viewportHeight
            ? Math.round(((scrollTop + viewportHeight) / docHeight) * 100)
            : 100;

        if (depth > maxScrollDepth) {
            maxScrollDepth = depth;
            send('analytics.activity', {
                type: 'scroll',
                path: currentPath,
                meta: { depth: depth }
            });
        }
    }

    function onClick(e) {
        onInteraction();
        var now = Date.now();
        if (now - lastClickSend < CLICK_THROTTLE) return;
        lastClickSend = now;
        var target = e.target;
        var tag = target.tagName || '';
        var info = { tag: tag.toLowerCase() };
        if (target.href) info.href = target.href.substring(0, 200);
        if (target.id) info.id = target.id;
        send('analytics.activity', {
            type: 'click',
            path: currentPath,
            meta: info
        });
    }

    function onVisibilityChange() {
        if (document.hidden) {
            isPageVisible = false;
            pauseActive();
        } else {
            isPageVisible = true;
            startActive();
        }
    }

    function onBeforeUnload() {
        flushHeartbeat();
    }

    function onPopState() {
        if (location.pathname !== currentPath) {
            send('analytics.page_view', {
                path: location.pathname,
                referrer: document.referrer || ''
            });
            currentPath = location.pathname;
            maxScrollDepth = 0;
        }
    }

    // ── Init ───────────────────────────────────────
    clientId = getClientId();

    document.addEventListener('scroll', onScroll, { passive: true });
    document.addEventListener('click', onClick, { passive: true });
    document.addEventListener('touchstart', onInteraction, { passive: true });
    document.addEventListener('mousemove', onInteraction, { passive: true, once: true });
    document.addEventListener('keydown', onInteraction, { passive: true, once: true });
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('beforeunload', onBeforeUnload);
    window.addEventListener('popstate', onPopState);

    // HTMX pushes URL on partial navigation — track as page view
    document.addEventListener('htmx:pushedIntoHistory', function (evt) {
        var newPath = evt.detail.path;
        if (newPath !== currentPath) {
            send('analytics.page_view', { path: newPath, referrer: '' });
            currentPath = newPath;
            maxScrollDepth = 0;
        }
    });

    startActive();
    connect();

    window.WS = { on: on, send: send, isConnected: isConnected };
})();
