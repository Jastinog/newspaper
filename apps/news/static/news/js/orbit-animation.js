/**
 * Orbit loading animation.
 *
 * Renders particles spiraling into a center node on a canvas.
 * Expects #loadingOverlay and #orbitCanvas in the DOM.
 *
 * Usage:
 *   OrbitAnimation.start();
 *   OrbitAnimation.stop();
 */
var OrbitAnimation = (function () {
    'use strict';

    var overlay, canvas, ctx, animId, tick, DPR;
    var sources, particles, accentRGB, accent;
    var ready = false;

    var NUM = 10, CENTER_R = 6, R_MIN = 2, R_MAX = 4;

    function hexRgb(hex) {
        hex = hex.replace('#', '');
        if (hex.length === 3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
        return [
            parseInt(hex.slice(0, 2), 16),
            parseInt(hex.slice(2, 4), 16),
            parseInt(hex.slice(4, 6), 16),
        ];
    }

    function createSource(i) {
        var orbit = 60 + Math.random() * 100;
        return {
            orbit: orbit, origOrbit: orbit,
            angle: (Math.PI * 2 / NUM) * i + Math.random() * 0.5,
            speed: (0.003 + Math.random() * 0.006) * (Math.random() > 0.3 ? 1 : -1),
            r: R_MIN + Math.random() * (R_MAX - R_MIN),
            drift: 0.04 + Math.random() * 0.06,
            minOrbit: 18 + Math.random() * 14,
            alpha: 0,
            phase: Math.random() * Math.PI * 2,
        };
    }

    function resize() {
        var size = Math.min(window.innerWidth, window.innerHeight, 420);
        canvas.style.width = size + 'px';
        canvas.style.height = size + 'px';
        canvas.width = size * DPR;
        canvas.height = size * DPR;
        ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    }

    function draw() {
        tick++;
        var W = canvas.width / DPR, H = canvas.height / DPR;
        var cx = W / 2, cy = H / 2;
        ctx.clearRect(0, 0, W, H);

        /* center glow + dot */
        var pulse = 1 + 0.15 * Math.sin(tick * 0.03);
        var grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, CENTER_R * 4 * pulse);
        grad.addColorStop(0, 'rgba(' + accentRGB + ',0.35)');
        grad.addColorStop(1, 'rgba(' + accentRGB + ',0)');
        ctx.beginPath(); ctx.arc(cx, cy, CENTER_R * 4 * pulse, 0, Math.PI * 2);
        ctx.fillStyle = grad; ctx.fill();
        ctx.beginPath(); ctx.arc(cx, cy, CENTER_R * pulse, 0, Math.PI * 2);
        ctx.fillStyle = accent; ctx.fill();

        /* orbiting sources */
        for (var i = 0; i < sources.length; i++) {
            var s = sources[i];
            s.angle += s.speed;
            s.orbit -= s.drift;
            if (s.orbit <= s.minOrbit) {
                var sx = cx + Math.cos(s.angle) * s.minOrbit;
                var sy = cy + Math.sin(s.angle) * s.minOrbit;
                particles.push({ x: sx, y: sy, vx: 0, vy: 0, life: 1, r: 1 + Math.random() * 1.5 });
                s.orbit = s.origOrbit;
                s.alpha = 0;
            }
            if (s.alpha < 1) s.alpha = Math.min(1, s.alpha + 0.015);

            var x = cx + Math.cos(s.angle) * s.orbit;
            var y = cy + Math.sin(s.angle) * s.orbit;

            var lineAlpha = (0.08 + 0.12 * (1 - s.orbit / s.origOrbit)) * s.alpha;
            ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y);
            ctx.strokeStyle = 'rgba(' + accentRGB + ',' + lineAlpha + ')';
            ctx.lineWidth = 0.5; ctx.stroke();

            var flicker = 0.7 + 0.3 * Math.sin(tick * 0.05 + s.phase);
            ctx.beginPath(); ctx.arc(x, y, s.r, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(' + accentRGB + ',' + (s.alpha * flicker).toFixed(2) + ')';
            ctx.fill();

            var sg = ctx.createRadialGradient(x, y, 0, x, y, s.r * 3);
            sg.addColorStop(0, 'rgba(' + accentRGB + ',' + (0.15 * s.alpha).toFixed(2) + ')');
            sg.addColorStop(1, 'rgba(' + accentRGB + ',0)');
            ctx.beginPath(); ctx.arc(x, y, s.r * 3, 0, Math.PI * 2);
            ctx.fillStyle = sg; ctx.fill();
        }

        /* data particles flying to center */
        for (var j = particles.length - 1; j >= 0; j--) {
            var p = particles[j];
            var dx = cx - p.x, dy = cy - p.y;
            var dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < 3) { particles.splice(j, 1); continue; }
            p.vx += (dx / dist) * 0.15; p.vy += (dy / dist) * 0.15;
            p.vx *= 0.96; p.vy *= 0.96;
            p.x += p.vx; p.y += p.vy;
            p.life = Math.min(dist / 60, 1);
            ctx.beginPath(); ctx.arc(p.x, p.y, p.r * p.life, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(' + accentRGB + ',' + (0.8 * p.life).toFixed(2) + ')';
            ctx.fill();
        }

        animId = requestAnimationFrame(draw);
    }

    function init() {
        overlay = document.getElementById('loadingOverlay');
        canvas = document.getElementById('orbitCanvas');
        if (!overlay || !canvas) return;

        ctx = canvas.getContext('2d');
        DPR = window.devicePixelRatio || 1;
        tick = 0;
        animId = null;

        var style = getComputedStyle(document.documentElement);
        accent = style.getPropertyValue('--accent').trim() || '#6b1520';
        accentRGB = hexRgb(accent);

        sources = [];
        particles = [];
        for (var i = 0; i < NUM; i++) sources.push(createSource(i));

        window.addEventListener('resize', function () {
            if (overlay.classList.contains('active')) resize();
        });

        ready = true;
    }

    function start() {
        if (!ready) init();
        if (!overlay) return;
        overlay.classList.add('active');
        resize();
        if (!animId) draw();
    }

    function stop() {
        if (!overlay) return;
        overlay.classList.remove('active');
        if (animId) { cancelAnimationFrame(animId); animId = null; }
    }

    /* auto-init */
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return { start: start, stop: stop };
})();
