/**
 * Lock background scroll while any fullscreen overlay modal is open.
 *
 * Every modal (summary, sources, similar-news, research) appends its overlay
 * directly to <body>, so a single MutationObserver on body's children can
 * toggle `body.modal-open` (which sets overflow:hidden) without each modal
 * having to manage scroll state itself.
 */
(function () {
    'use strict';

    var SEL = '.sum-modal-overlay, .sources-modal-overlay, ' +
              '.similar-modal-overlay, .dd-modal-overlay';

    function sync() {
        var open = !!document.querySelector(SEL);
        document.body.classList.toggle('modal-open', open);
    }

    // Overlays are appended as direct children of <body>; no subtree needed.
    new MutationObserver(sync).observe(document.body, { childList: true });
})();
