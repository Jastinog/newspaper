document.addEventListener("click", function (e) {
    var btn = e.target.closest(".sources-btn");
    if (btn) {
        e.stopPropagation();
        var id = btn.getAttribute("data-sources-id");
        var overlay = document.getElementById("sources-modal-" + id);
        if (overlay) {
            // move to body so it's not clipped by positioned parents
            document.body.appendChild(overlay);
            overlay.style.display = "flex";
            requestAnimationFrame(function () {
                overlay.classList.add("visible");
            });
        }
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

function closeSources(overlay) {
    overlay.classList.remove("visible");
    setTimeout(function () {
        overlay.style.display = "none";
    }, 200);
}
