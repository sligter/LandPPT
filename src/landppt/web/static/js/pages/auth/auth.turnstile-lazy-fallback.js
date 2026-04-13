(() => {
    if (typeof window === "undefined" || typeof document === "undefined") return;
    if (typeof window.ensureLazyTurnstileWidget === "function") return;
    if (window.__landpptTurnstileLazyFallbackBooted) return;
    window.__landpptTurnstileLazyFallbackBooted = true;

    const SCRIPT_ID = "landppt-turnstile-fallback-script";
    const DEFAULT_SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

    const qs = (selector, root = document) => root.querySelector(selector);
    const registerAlert = () => qs("#registerAlert");

    const showAlert = (message) => {
        const area = registerAlert();
        if (!area) return;
        area.innerHTML = `
        <div class="alert alert--danger">
            <i class="fas fa-exclamation-circle"></i>
            <div>${String(message || "人机验证加载失败")}</div>
        </div>
    `;
    };

    const resolveErrorMessage = (error) => {
        const raw = String(
            (error && (error.message || (typeof error.toString === "function" && error.toString()))) || error || ""
        );
        if (raw.includes("110200")) {
            return "Turnstile 未通过域名校验：请在 Cloudflare Turnstile 控制台将当前域名加入允许列表。";
        }
        return `人机验证加载失败：${raw || "未知错误"}`;
    };

    const getContainer = () => qs("[data-turnstile-lazy=\"1\"]");

    const hasRenderedWidget = (container) => {
        if (!container) return false;
        if (container.dataset.turnstileRendered === "1") return true;
        return !!container.querySelector("iframe[src*=\"challenges.cloudflare.com\"]");
    };

    const ensureScript = (container) => new Promise((resolve, reject) => {
        if (window.turnstile && typeof window.turnstile.render === "function") {
            resolve(window.turnstile);
            return;
        }

        let script = document.getElementById(SCRIPT_ID);
        if (!script) {
            script = document.createElement("script");
            script.id = SCRIPT_ID;
            script.src = (container?.dataset?.turnstileScriptSrc || DEFAULT_SCRIPT_SRC).trim();
            script.async = true;
            script.defer = true;
            document.head.appendChild(script);
        }

        const onReady = () => {
            if (window.turnstile && typeof window.turnstile.render === "function") {
                resolve(window.turnstile);
                return true;
            }
            return false;
        };

        if (onReady()) return;

        script.addEventListener("load", () => {
            if (onReady()) return;
            reject(new Error("Turnstile API unavailable after script load"));
        }, { once: true });
        script.addEventListener("error", () => reject(new Error("Failed to load Turnstile script")), { once: true });
    });

    const renderWidget = async () => {
        const container = getContainer();
        if (!container || hasRenderedWidget(container)) return true;

        await ensureScript(container);
        const turnstile = window.turnstile;
        if (!turnstile || typeof turnstile.render !== "function") {
            throw new Error("Turnstile API not ready");
        }

        const mountNode = qs("[data-turnstile-widget]", container) || container;
        const sitekey = (container.dataset.turnstileSitekey || "").trim();
        if (!sitekey) throw new Error("Missing Turnstile sitekey");

        const options = {
            sitekey,
            theme: (container.dataset.turnstileTheme || "auto").trim(),
            language: (container.dataset.turnstileLanguage || "zh-cn").trim().toLowerCase(),
            "error-callback": (code) => showAlert(resolveErrorMessage(new Error(`[Cloudflare Turnstile] Error: ${code}`))),
        };

        const responseFieldName = (container.dataset.turnstileResponseFieldName || "").trim();
        if (responseFieldName) options["response-field-name"] = responseFieldName;

        turnstile.render(mountNode, options);
        container.dataset.turnstileRendered = "1";
        return true;
    };

    const maybeRenderForRegisterTab = () => {
        const selected = qs(".auth-tabs button[aria-selected=\"true\"]");
        if (selected && selected.dataset.tab !== "register") return;
        renderWidget().catch((error) => showAlert(resolveErrorMessage(error)));
    };

    const bindRegisterTab = () => {
        const tabs = Array.from(document.querySelectorAll(".auth-tabs button[data-tab]"));
        tabs
            .filter((button) => button.dataset.tab === "register")
            .forEach((button) => {
                button.addEventListener("click", () => {
                    renderWidget().catch((error) => showAlert(resolveErrorMessage(error)));
                });
            });
    };

    const bootstrap = () => {
        if (!getContainer()) return;
        bindRegisterTab();
        const initialTab = (document.body?.dataset?.initialTab || "").trim().toLowerCase();
        if (initialTab === "register") {
            renderWidget().catch((error) => showAlert(resolveErrorMessage(error)));
            return;
        }
        maybeRenderForRegisterTab();
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
    } else {
        bootstrap();
    }
})();
