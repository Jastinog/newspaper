/**
 * Article "Summary" — on-demand summary in a modal.
 *
 * Clicking a card's image or "Summary" button opens a modal that:
 *   - shows live generation progress (over WebSocket), or
 *   - renders an already-stored summary instantly (server marks such cards).
 *
 * UI labels come from window.SUMMARY_I18N (localized server-side); each lookup
 * falls back to the original Russian so the feature works without the catalog.
 *
 * Depends on: ws.js
 */
(function () {
    'use strict';

    var I18N = window.SUMMARY_I18N || {};

    /* ── DOM helpers ──────────────────────────────────── */

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }

    /** Split a summary blob into paragraph nodes on blank/newlines. */
    function paragraphs(container, text) {
        var parts = String(text || '').split(/\n+/);
        for (var i = 0; i < parts.length; i++) {
            var p = parts[i].trim();
            if (p) container.appendChild(el('p', null, p));
        }
    }

    /* ── Modal state (one at a time) ──────────────────── */

    var overlay = null;   // current overlay element
    var modal = null;     // current modal element
    var openId = null;    // article id the open modal belongs to
    var openCard = null;  // the <article> that opened it
    var openToken = null; // page-issued summary token for the open article

    function closeModal() {
        if (overlay) overlay.remove();
        overlay = null;
        modal = null;
        openId = null;
        openCard = null;
        openToken = null;
        document.removeEventListener('keydown', onKey);
    }

    function onKey(e) {
        if (e.key === 'Escape') closeModal();
    }

    function buildModal(title, imageSrc) {
        overlay = el('div', 'sum-modal-overlay');
        modal = el('div', 'sum-modal');

        var head = el('div', 'sum-modal-head');
        head.appendChild(el('span', 'sum-modal-badge', 'AI'));
        head.appendChild(el('span', 'sum-modal-kicker', I18N.kicker || 'Суть'));
        var close = el('button', 'sum-modal-close', '✕');
        close.type = 'button';
        close.setAttribute('aria-label', I18N.close || 'Закрыть');
        close.onclick = closeModal;
        head.appendChild(close);
        modal.appendChild(head);

        if (imageSrc) {
            var figure = el('div', 'sum-modal-image');
            var img = el('img');
            img.src = imageSrc;
            img.alt = '';
            img.loading = 'lazy';
            figure.appendChild(img);
            modal.appendChild(figure);
        }

        if (title) modal.appendChild(el('h3', 'sum-modal-title', title));

        // Content region — swapped between progress / result / error.
        modal._content = el('div', 'sum-modal-content');
        modal.appendChild(modal._content);

        overlay.appendChild(modal);
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) closeModal();
        });
        document.addEventListener('keydown', onKey);
        document.body.appendChild(overlay);
    }

    /* ── Content states ───────────────────────────────── */

    function renderProgress(step, total, label) {
        if (!modal) return;
        var content = modal._content;
        content.innerHTML = '';

        var box = el('div', 'sum-progress');
        box.appendChild(el('div', 'sum-spinner'));
        box.appendChild(el('div', 'sum-progress-label', label || I18N.genSummary || 'Генерирую пересказ…'));

        var t = total || 3;
        var s = step || 0;
        var track = el('div', 'sum-progress-track');
        var fill = el('div', 'sum-progress-fill');
        fill.style.width = Math.round((s / t) * 100) + '%';
        track.appendChild(fill);
        box.appendChild(track);

        box.appendChild(el('div', 'sum-progress-step', s + ' / ' + t));
        content.appendChild(box);
    }

    function renderResult(articleId, data) {
        if (!modal || openId !== articleId) return;
        var content = modal._content;
        content.innerHTML = '';

        var body = el('div', 'sum-result-body');
        paragraphs(body, data.summary);
        content.appendChild(body);

        if (data.conclusion) {
            var concl = el('div', 'sum-result-concl');
            concl.appendChild(el('span', 'sum-result-concl-label', I18N.takeaway || 'Вывод'));
            concl.appendChild(el('p', null, data.conclusion));
            content.appendChild(concl);
        }

        var actions = el('div', 'sum-modal-actions');
        if (openCard) {
            var orig = openCard.querySelector('.home-orig-btn');
            if (orig) {
                var a = el('a', 'sum-modal-btn sum-modal-btn-secondary', (I18N.original || 'Оригинал') + ' ↗');
                a.href = orig.href;
                a.target = '_blank';
                a.rel = 'noopener';
                actions.appendChild(a);
            }
        }
        var done = el('button', 'sum-modal-btn sum-modal-btn-primary', I18N.close || 'Закрыть');
        done.type = 'button';
        done.onclick = closeModal;
        actions.appendChild(done);
        content.appendChild(actions);
    }

    function renderError(articleId, message) {
        if (!modal || openId !== articleId) return;
        var content = modal._content;
        content.innerHTML = '';

        var box = el('div', 'sum-error');
        box.appendChild(el('div', 'sum-error-icon', '⚠'));
        box.appendChild(el('div', 'sum-error-msg', message || I18N.errorGeneric || 'Не удалось сделать пересказ.'));

        var retry = el('button', 'sum-modal-btn sum-modal-btn-primary', I18N.retry || 'Повторить');
        retry.type = 'button';
        retry.onclick = function () { requestSummary(articleId); };
        box.appendChild(retry);
        content.appendChild(box);
    }

    /* ── Request flow ─────────────────────────────────── */

    function requestSummary(articleId) {
        renderProgress(0, 3, I18N.sending || 'Отправляю запрос…');
        var language = (window.WS && WS.getLanguage) ? WS.getLanguage() : 'en';
        var payload = { article_id: articleId, language: language };
        if (openToken) payload.token = openToken;
        if (!WS.send('summary.generate', payload)) {
            renderError(articleId, I18N.noConnection || 'Нет соединения с сервером. Попробуйте ещё раз.');
        }
    }

    function openFor(card) {
        var articleId = parseInt(card.dataset.articleId, 10);
        if (!articleId) return;

        var titleEl = card.querySelector('.home-item-title');
        var title = titleEl ? titleEl.textContent.trim() : '';

        var imgEl = card.querySelector('.home-item-thumb img');
        var imageSrc = imgEl ? imgEl.currentSrc || imgEl.src : '';

        buildModal(title, imageSrc);
        openId = articleId;
        openCard = card;
        openToken = card.dataset.summaryToken || null;
        requestSummary(articleId);
    }

    /* ── WS handlers ──────────────────────────────────── */

    WS.on('summary.generating', function (msg) {
        if (openId !== msg.article_id) return;
        renderProgress(1, 3, I18N.reading || 'Читаю статью');
    });

    WS.on('summary.progress', function (msg) {
        if (openId !== msg.article_id) return;
        // Progress labels are localized client-side (the server streams step numbers only).
        renderProgress(msg.step, msg.total_steps, I18N.generating || 'Генерирую…');
    });

    WS.on('summary.ready', function (msg) {
        // Mark the card as having a summary for future instant opens.
        var card = document.querySelector('.home-item[data-article-id="' + msg.article_id + '"]');
        if (card) markCardReady(card);
        renderResult(msg.article_id, msg);
    });

    WS.on('summary.error', function (msg) {
        renderError(msg.article_id, msg.message);
    });

    function markCardReady(card) {
        card.classList.add('has-summary');
        var badge = card.querySelector('.home-item-badge-text');
        if (badge) badge.textContent = I18N.summaryReady || 'Суть готова';
        var label = card.querySelector('.home-sum-btn-label');
        if (label) label.textContent = I18N.readSummary || 'Читать суть';
    }

    /* ── Click delegation (survives HTMX infinite-scroll swaps) ── */

    document.addEventListener('click', function (e) {
        var trigger = e.target.closest('[data-summary-trigger]');
        if (!trigger) return;
        var card = trigger.closest('.home-item[data-article-id]');
        if (!card) return;
        e.preventDefault();
        openFor(card);
    });
})();
