/**
 * Unified WebSocket client.
 *
 * Single connection to /ws/ handles:
 *   - Analytics tracking (ping every 30s with scroll count + visited pages)
 *   - Deep dive generation progress
 *   - Any future real-time features
 *
 * Public API:
 *   WS.on(type, handler)   — listen for server messages by type
 *   WS.send(action, data)  — send action to server
 *   WS.isConnected()       — check connection state
 *   WS.getLanguage()       — get current language
 */
(function () {
    'use strict';

    // ── Config ─────────────────────────────────────
    var STORAGE_KEY = 'newspaper_client_id';
    var PING_INTERVAL = 30000;

    // ── WS State ───────────────────────────────────
    var handlers = {};
    var ws = null;
    var reconnectDelay = 2000;
    var maxReconnectDelay = 30000;
    var currentDelay = reconnectDelay;

    // ── Analytics State ────────────────────────────
    var clientId = null;
    var pingTimer = null;
    var activeTime = 0;
    var lastActiveTimestamp = null;
    var isPageVisible = true;
    var scrollCount = 0;
    var pageBuffer = [];
    var currentPath = location.pathname;

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
    function getLanguage() {
        var prefix = document.body.dataset.langPrefix || '';
        return prefix.replace(/^\//, '') || 'en';
    }

    var url = (location.protocol === 'https:' ? 'wss:' : 'ws:')
        + '//' + location.host + '/ws/?lang=' + getLanguage();

    function connect() {
        ws = new WebSocket(url);

        ws.onopen = function () {
            currentDelay = reconnectDelay;
            dispatch('ws.open', {});

            // Reset analytics state for new server-side session
            activeTime = 0;
            lastActiveTimestamp = null;
            scrollCount = 0;
            pageBuffer = [];

            // Identify client and record initial page
            send('analytics.init', {
                client_id: clientId,
                path: location.pathname,
                referrer: document.referrer || ''
            });
            currentPath = location.pathname;

            startActive();
            startPing();
        };

        ws.onmessage = function (evt) {
            var msg;
            try { msg = JSON.parse(evt.data); } catch (e) { return; }
            if (msg.type) dispatch(msg.type, msg);
        };

        ws.onclose = function () {
            ws = null;
            dispatch('ws.close', {});
            stopPing();
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

    function getActiveTime() {
        if (lastActiveTimestamp) {
            return activeTime + Math.round((Date.now() - lastActiveTimestamp) / 1000);
        }
        return activeTime;
    }

    // ── Ping (every 30s) ──────────────────────────
    function startPing() {
        stopPing();
        pingTimer = setInterval(sendPing, PING_INTERVAL);
    }

    function stopPing() {
        if (pingTimer) {
            clearInterval(pingTimer);
            pingTimer = null;
        }
    }

    function sendPing() {
        var sent = send('analytics.ping', {
            scrolls: scrollCount,
            pages: pageBuffer,
            active_time: getActiveTime()
        });
        if (sent) {
            scrollCount = 0;
            pageBuffer = [];
        }
    }

    // ── Scroll counting ───────────────────────────
    function onScroll() {
        scrollCount++;
        if (!lastActiveTimestamp) startActive();
    }

    // ── Page navigation ───────────────────────────
    function trackPageChange(newPath) {
        if (newPath !== currentPath) {
            pageBuffer.push(newPath);
            currentPath = newPath;
            scrollCount = 0;
        }
    }

    function onPopState() {
        trackPageChange(location.pathname);
    }

    // ── Visibility ────────────────────────────────
    function onVisibilityChange() {
        if (document.hidden) {
            isPageVisible = false;
            pauseActive();
            // Send final ping before going idle
            sendPing();
            stopPing();
        } else {
            isPageVisible = true;
            startActive();
            // Resume pinging — send immediately to check 5-min gap server-side
            sendPing();
            startPing();
        }
    }

    function onBeforeUnload() {
        sendPing();
    }

    // ── Init ───────────────────────────────────────
    clientId = getClientId();

    document.addEventListener('scroll', onScroll, { passive: true });
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('beforeunload', onBeforeUnload);
    window.addEventListener('popstate', onPopState);

    // HTMX pushes URL on partial navigation — track as page change
    document.addEventListener('htmx:pushedIntoHistory', function (evt) {
        trackPageChange(evt.detail.path);
    });

    startActive();
    connect();

    window.WS = { on: on, send: send, isConnected: isConnected, getLanguage: getLanguage };
})();
