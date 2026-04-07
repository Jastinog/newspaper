var _sourcesCache = {};

document.addEventListener("click", function (e) {
    var btn = e.target.closest(".sources-btn");
    if (btn) {
        e.stopPropagation();
        var id = btn.getAttribute("data-sources-id");
        openSources(id);
        return;
    }

    var closeBtn = e.target.closest(".sources-modal-close");
    if (closeBtn) {
        closeSources(closeBtn.closest(".sources-modal-overlay"));
        return;
    }

    if (e.target.classList.contains("sources-modal-overlay")) {
        closeSources(e.target);
    }
});

document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
        var open = document.querySelector(".sources-modal-overlay.visible");
        if (open) closeSources(open);
    }
});

function openSources(id) {
    var existing = document.getElementById("sources-modal-" + id);
    if (existing) {
        existing.style.display = "flex";
        requestAnimationFrame(function () {
            existing.classList.add("visible");
        });
        return;
    }

    if (_sourcesCache[id]) {
        showSourcesModal(id, _sourcesCache[id]);
        return;
    }

    var overlay = buildOverlay(id);
    var body = overlay.querySelector(".sources-modal-body");
    var loading = document.createElement("div");
    loading.style.cssText = "text-align:center;padding:2rem;opacity:.5";
    loading.textContent = "Loading\u2026";
    body.appendChild(loading);

    document.body.appendChild(overlay);
    overlay.style.display = "flex";
    requestAnimationFrame(function () {
        overlay.classList.add("visible");
    });

    fetch("/api/digest-items/" + id + "/sources/")
        .then(function (r) { return r.json(); })
        .then(function (data) {
            _sourcesCache[id] = data.sources || [];
            overlay.remove();
            showSourcesModal(id, _sourcesCache[id]);
        })
        .catch(function () {
            overlay.remove();
        });
}

function buildOverlay(id) {
    var overlay = document.createElement("div");
    overlay.className = "sources-modal-overlay";
    overlay.id = "sources-modal-" + id;

    var modal = document.createElement("div");
    modal.className = "sources-modal";

    var header = document.createElement("div");
    header.className = "sources-modal-header";

    var title = document.createElement("span");
    title.className = "sources-modal-title";
    header.appendChild(title);

    var closeBtn = document.createElement("button");
    closeBtn.className = "sources-modal-close";
    closeBtn.type = "button";
    closeBtn.textContent = "\u00d7";
    header.appendChild(closeBtn);

    var body = document.createElement("div");
    body.className = "sources-modal-body";

    modal.appendChild(header);
    modal.appendChild(body);
    overlay.appendChild(modal);
    return overlay;
}

function buildSourceCard(s) {
    var a = document.createElement("a");
    a.className = "source-card";
    a.href = s.url;
    a.target = "_blank";
    a.rel = "noopener";

    if (s.image_url) {
        var img = document.createElement("img");
        img.className = "source-card-img";
        img.src = s.image_url;
        img.alt = "";
        img.loading = "lazy";
        a.appendChild(img);
    } else {
        var placeholder = document.createElement("span");
        placeholder.className = "source-card-img source-card-img--placeholder";
        var icon = document.createElement("i");
        icon.className = "far fa-newspaper";
        placeholder.appendChild(icon);
        a.appendChild(placeholder);
    }

    var text = document.createElement("div");
    text.className = "source-card-text";

    var titleEl = document.createElement("span");
    titleEl.className = "source-card-title";
    titleEl.textContent = s.title;
    text.appendChild(titleEl);

    var feed = document.createElement("span");
    feed.className = "source-card-feed";
    feed.textContent = s.feed_title;
    text.appendChild(feed);

    a.appendChild(text);
    return a;
}

function showSourcesModal(id, sources) {
    var old = document.getElementById("sources-modal-" + id);
    if (old) old.remove();

    var overlay = buildOverlay(id);
    var title = overlay.querySelector(".sources-modal-title");
    title.textContent = "Sources (" + sources.length + ")";

    var body = overlay.querySelector(".sources-modal-body");
    for (var i = 0; i < sources.length; i++) {
        body.appendChild(buildSourceCard(sources[i]));
    }

    document.body.appendChild(overlay);
    overlay.style.display = "flex";
    requestAnimationFrame(function () {
        overlay.classList.add("visible");
    });
}

function closeSources(overlay) {
    overlay.classList.remove("visible");
    setTimeout(function () {
        overlay.style.display = "none";
    }, 200);
}
