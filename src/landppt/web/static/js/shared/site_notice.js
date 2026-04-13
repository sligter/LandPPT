(function () {
    const LEVELS = new Set(["info", "success", "warning", "danger"]);
    const ICONS = {
        info: "fa-circle-info",
        success: "fa-circle-check",
        warning: "fa-triangle-exclamation",
        danger: "fa-circle-exclamation",
    };

    function resolveElement(target) {
        if (!target) return null;
        if (typeof target === "string") return document.getElementById(target);
        return target;
    }

    function normalizeLevel(level) {
        return LEVELS.has(level) ? level : "info";
    }

    function hideNotice(container) {
        if (!container) return;
        container.hidden = true;
        container.className = "site-notice site-notice--hidden";
        container.replaceChildren();
    }

    function renderNotice(target, notice) {
        const container = resolveElement(target);
        if (!container) return;

        if (!notice || !notice.active) {
            hideNotice(container);
            return;
        }

        const level = normalizeLevel(String(notice.level || "").trim().toLowerCase());
        const titleText = String(notice.title || "").trim();
        const messageText = String(notice.message || "").trim();
        if (!titleText && !messageText) {
            hideNotice(container);
            return;
        }

        const iconWrap = document.createElement("div");
        iconWrap.className = "site-notice__icon";
        const icon = document.createElement("i");
        icon.className = `fas ${ICONS[level]}`;
        iconWrap.appendChild(icon);

        const content = document.createElement("div");
        content.className = "site-notice__content";

        if (titleText) {
            const title = document.createElement("div");
            title.className = "site-notice__title";
            title.textContent = titleText;
            content.appendChild(title);
        }

        if (messageText) {
            const message = document.createElement("div");
            message.className = "site-notice__message";
            message.textContent = messageText;
            content.appendChild(message);
        }

        container.className = `site-notice site-notice--${level}`;
        container.hidden = false;
        container.replaceChildren(iconWrap, content);
    }

    function applySponsorLink(target, data) {
        const link = resolveElement(target);
        if (!link || !data || !data.sponsor_page_enabled) return;
        link.href = data.sponsor_page_url || "/sponsors";
        link.classList.remove("is-hidden");
    }

    async function loadPublicSettings(options = {}) {
        const noticeContainer = resolveElement(options.noticeContainer);
        const sponsorLink = resolveElement(options.sponsorLink);

        try {
            const response = await fetch("/api/community/public-settings", {
                credentials: "same-origin",
            });
            if (!response.ok) {
                if (noticeContainer) hideNotice(noticeContainer);
                return null;
            }

            const data = await response.json();
            if (noticeContainer) renderNotice(noticeContainer, data.site_notice);
            if (sponsorLink) applySponsorLink(sponsorLink, data);
            return data;
        } catch (_error) {
            if (noticeContainer) hideNotice(noticeContainer);
            return null;
        }
    }

    window.SiteNotice = {
        loadPublicSettings,
        renderNotice,
    };
})();
