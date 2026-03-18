/**
 * WebSocket client.
 *
 * Single connection to /ws/ with typed message dispatching.
 *
 * Usage:
 *   WS.on('deep_dive.ready', function(msg) { ... });
 *   WS.send('deep_dive.generate', { item_id: 123 });
 */
(function () {
    'use strict';

    var handlers = {};
    var ws = null;
    var reconnectDelay = 2000;
    var maxReconnectDelay = 30000;
    var currentDelay = reconnectDelay;

    var url = (location.protocol === 'https:' ? 'wss:' : 'ws:')
        + '//' + location.host + '/ws/';

    function connect() {
        ws = new WebSocket(url);

        ws.onopen = function () {
            currentDelay = reconnectDelay;
            dispatch('ws.open', {});
        };

        ws.onmessage = function (evt) {
            var msg;
            try { msg = JSON.parse(evt.data); } catch (e) { return; }
            if (msg.type) dispatch(msg.type, msg);
        };

        ws.onclose = function () {
            ws = null;
            dispatch('ws.close', {});
            setTimeout(connect, currentDelay);
            currentDelay = Math.min(currentDelay * 1.5, maxReconnectDelay);
        };

        ws.onerror = function () { /* onclose will fire next */ };
    }

    function dispatch(type, msg) {
        var list = handlers[type];
        if (!list) return;
        for (var i = 0; i < list.length; i++) list[i](msg);
    }

    /** Register a handler for a message type. */
    function on(type, fn) {
        if (!handlers[type]) handlers[type] = [];
        handlers[type].push(fn);
    }

    /** Send an action to the server. Returns false if not connected. */
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

    connect();

    window.WS = { on: on, send: send, isConnected: isConnected };
})();
