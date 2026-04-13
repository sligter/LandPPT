function $(sel, root = document) {
    return root.querySelector(sel);
}

function $all(sel, root = document) {
    return Array.from(root.querySelectorAll(sel));
}

function setBusy(btn, busy, label) {
    if (!btn) return;
    btn.disabled = !!busy;
    if (!busy) {
        if (label) btn.dataset.originalLabel = label;
        btn.innerHTML = btn.dataset.originalLabel || btn.innerHTML;
        return;
    }
    btn.dataset.originalLabel = btn.dataset.originalLabel || btn.innerHTML;
    btn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i><span>${label || "处理中..."}</span>`;
}

function renderAlert(area, message, type = "danger") {
    if (!area) return;
    const icon = type === "success" ? "fa-check-circle" : "fa-exclamation-circle";
    const cls = type === "success" ? "alert--success" : "alert--danger";
    area.innerHTML = `
        <div class="alert ${cls}">
            <i class="fas ${icon}"></i>
            <div>${escapeHtml(message)}</div>
        </div>
    `;
}

function escapeHtml(str) {
    return String(str)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function getTurnstileToken() {
    const tokenInput =
        $('input[name="turnstile_token"]') ||
        $('input[name="cf-turnstile-response"]');
    return tokenInput ? tokenInput.value.trim() : "";
}

const TURNSTILE_LAZY_SCRIPT_ID = "landppt-turnstile-lazy-script";
const TURNSTILE_LAZY_SCRIPT_FALLBACK = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
const turnstileLazyState = {
    scriptPromise: null,
    widgetId: null,
};

function getRegisterAlertArea() {
    return $("#registerAlert");
}

function getRegistrationInviteConfig() {
    const raw = window.authRegistrationConfig || {};
    return {
        inviteCodeRequired: raw.inviteCodeRequired !== false && raw.inviteCodeRequired !== "false",
    };
}

function syncRegistrationInviteUi() {
    const config = getRegistrationInviteConfig();
    const inviteInputs = [$("#reg_invite_code"), $("#invite_code")].filter(Boolean);

    inviteInputs.forEach((input) => {
        input.required = config.inviteCodeRequired;
/*
        input.placeholder = config.inviteCodeRequired
            ? "输入邀请码后再注册"
            : "可选：填写邀请码领取邀请奖励";

        const label = document.querySelector(`label[for="${input.id}"]`);
        if (label) {
            label.textContent = config.inviteCodeRequired ? "邀请码" : "邀请码（选填）";
        }
    });

    });
*/
        input.placeholder = config.inviteCodeRequired
            ? "Enter invite code before registering"
            : "Optional: enter an invite code for invite rewards";

        const label = document.querySelector(`label[for="${input.id}"]`);
        if (label) {
            label.textContent = config.inviteCodeRequired ? "Invite Code" : "Invite Code (Optional)";
        }
    });

    $all(".js-register-oauth").forEach((link) => {
        link.dataset.inviteRequired = config.inviteCodeRequired ? "true" : "false";
    });
}

function resolveTurnstileErrorMessage(error) {
    const raw = String(
        (error && (error.message || error.toString && error.toString())) || error || ""
    );
    if (raw.includes("110200")) {
        return "Turnstile 未通过域名校验：请在 Cloudflare Turnstile 控制台将当前域名加入允许列表。";
    }
    return `人机验证加载失败：${raw || "未知错误"}`;
}

function renderTurnstileError(error) {
    const area = getRegisterAlertArea();
    if (area) {
        renderAlert(area, resolveTurnstileErrorMessage(error), "danger");
    }
}

function getLazyTurnstileContainer() {
    return $("[data-turnstile-lazy=\"1\"]");
}

function isLazyTurnstileEnabled() {
    return !!getLazyTurnstileContainer();
}

function isTurnstileApiReady() {
    return !!(window.turnstile && typeof window.turnstile.render === "function");
}

function ensureTurnstileScriptLoaded() {
    if (isTurnstileApiReady()) return Promise.resolve(window.turnstile);

    if (turnstileLazyState.scriptPromise) {
        return turnstileLazyState.scriptPromise;
    }

    const container = getLazyTurnstileContainer();
    if (!container) return Promise.resolve(null);

    const scriptSrc = (container.dataset.turnstileScriptSrc || TURNSTILE_LAZY_SCRIPT_FALLBACK).trim();

    turnstileLazyState.scriptPromise = new Promise((resolve, reject) => {
        let script = document.getElementById(TURNSTILE_LAZY_SCRIPT_ID);
        if (!script) {
            script = document.createElement("script");
            script.id = TURNSTILE_LAZY_SCRIPT_ID;
            script.src = scriptSrc;
            script.async = true;
            script.defer = true;
            document.head.appendChild(script);
        }

        const checkReady = () => {
            if (isTurnstileApiReady()) {
                resolve(window.turnstile);
                return true;
            }
            return false;
        };

        if (checkReady()) return;

        script.addEventListener("load", () => {
            if (checkReady()) return;
            reject(new Error("Turnstile script loaded but API is unavailable"));
        }, { once: true });
        script.addEventListener("error", () => {
            reject(new Error("Failed to load Turnstile script"));
        }, { once: true });
    }).catch((error) => {
        turnstileLazyState.scriptPromise = null;
        renderTurnstileError(error);
        throw error;
    });

    return turnstileLazyState.scriptPromise;
}

async function ensureLazyTurnstileWidget() {
    if (!isLazyTurnstileEnabled()) return true;
    if (turnstileLazyState.widgetId !== null) return true;

    const container = getLazyTurnstileContainer();
    if (!container) return false;

    await ensureTurnstileScriptLoaded();
    if (!isTurnstileApiReady()) {
        throw new Error("Turnstile API not ready");
    }

    const mountNode = container.querySelector("[data-turnstile-widget]") || container;
    const sitekey = (container.dataset.turnstileSitekey || "").trim();
    if (!sitekey) {
        throw new Error("Missing Turnstile sitekey");
    }

    const options = {
        sitekey,
        theme: (container.dataset.turnstileTheme || "auto").trim(),
        language: (container.dataset.turnstileLanguage || "zh-cn").trim().toLowerCase(),
    };
    const responseFieldName = (container.dataset.turnstileResponseFieldName || "").trim();
    if (responseFieldName) {
        options["response-field-name"] = responseFieldName;
    }
    options["error-callback"] = (code) => {
        turnstileLazyState.widgetId = null;
        renderTurnstileError(new Error(`[Cloudflare Turnstile] Error: ${code}`));
    };

    try {
        turnstileLazyState.widgetId = window.turnstile.render(mountNode, options);
    } catch (error) {
        turnstileLazyState.widgetId = null;
        renderTurnstileError(error);
        return false;
    }
    return true;
}

function hasTurnstileWidget() {
    if (isLazyTurnstileEnabled()) {
        return turnstileLazyState.widgetId !== null;
    }
    return !!$(".cf-turnstile");
}

function resetTurnstile() {
    try {
        if (window.turnstile && typeof window.turnstile.reset === "function") {
            if (turnstileLazyState.widgetId !== null) {
                window.turnstile.reset(turnstileLazyState.widgetId);
            } else {
                window.turnstile.reset();
            }
        }
    } catch {
        // ignore
    }
}

function initTabs() {
    const tabs = $all(".auth-tabs button[data-tab]");
    const indicator = $(".auth-tabs__indicator");
    const panels = $all(".panel[data-panel]");
    if (!tabs.length || !panels.length) return;

    const setTab = (tab) => {
        const target = tabs.find((t) => t.dataset.tab === tab) ? tab : tabs[0].dataset.tab;
        tabs.forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === target)));
        panels.forEach((p) => p.classList.toggle("is-active", p.dataset.panel === target));

        if (target === "register") {
            void ensureLazyTurnstileWidget();
        }

        if (indicator) {
            const active = tabs.find((t) => t.dataset.tab === target);
            if (active) {
                const idx = tabs.indexOf(active);
                indicator.style.transform = `translateX(${idx * 100}%)`;
            }
        }
    };

    tabs.forEach((btn) => {
        btn.addEventListener("click", () => setTab(btn.dataset.tab));
    });

    const initial = (document.body.dataset.initialTab || "").trim();
    setTab(initial || "login");
}

function initTyping() {
    const nodes = $all("[data-typing-words]");
    if (!nodes.length) return;

    const reduceMotion =
        window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    nodes.forEach((node, idx) => {
        const raw = (node.getAttribute("data-typing-words") || "").trim();
        const words = raw
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);
        if (!words.length) return;

        if (reduceMotion) {
            node.textContent = words.join(" / ");
            return;
        }

        let w = 0;
        let i = 0;
        let dir = 1; // 1 typing, -1 deleting
        const typeDelay = 80;
        const deleteDelay = 45;
        const pauseFull = 900;
        const pauseEmpty = 220;

        const tick = () => {
            const word = words[w];
            if (dir === 1) {
                i += 1;
                node.textContent = word.slice(0, i);
                if (i >= word.length) {
                    dir = -1;
                    setTimeout(tick, pauseFull);
                    return;
                }
                setTimeout(tick, typeDelay);
            } else {
                i -= 1;
                node.textContent = word.slice(0, Math.max(0, i));
                if (i <= 0) {
                    dir = 1;
                    w = (w + 1) % words.length;
                    setTimeout(tick, pauseEmpty);
                    return;
                }
                setTimeout(tick, deleteDelay);
            }
        };

        // small stagger
        setTimeout(tick, 120 + idx * 240);
    });
}

function openAfterCodeSection(root = document) {
    const section = root.querySelector(".js-after-code");
    if (!section) return;
    if (section.classList.contains("is-open")) return;
    section.classList.add("is-open");
    section.querySelectorAll("[data-unlock-on-code=\"1\"]").forEach((el) => {
        el.disabled = false;
    });
    const focusEl = section.querySelector("input:not([type=hidden]):not([disabled])");
    if (focusEl) focusEl.focus();
}

function initPasswordToggles() {
    $all(".js-toggle-password").forEach((btn) => {
        btn.addEventListener("click", () => {
            const targetId = btn.dataset.target;
            const input = targetId ? document.getElementById(targetId) : null;
            if (!input) return;
            const isPassword = input.type === "password";
            input.type = isPassword ? "text" : "password";
            btn.innerHTML = isPassword ? '<i class="fas fa-eye-slash"></i>' : '<i class="fas fa-eye"></i>';
        });
    });
}

function initLoginSubmit() {
    const form = $("#loginFormElement");
    const btn = $("#loginBtn");
    if (!form) return;
    form.addEventListener("submit", () => {
        setBusy(btn, true, "登录中...");
    });
}

function initRegisterSubmit() {
    const form = $("#registerFormElement");
    const btn = $("#registerBtn");
    const alertArea = $("#registerAlert");
    if (!form) return;

    const pwd = $("#reg_password") || $("#password");
    const confirm = $("#reg_confirm") || $("#confirm_password");
    if (pwd && confirm) {
        confirm.addEventListener("input", () => {
            if (confirm.value !== pwd.value) {
                confirm.setCustomValidity("两次密码输入不一致");
            } else {
                confirm.setCustomValidity("");
            }
        });
    }

    form.addEventListener("submit", (e) => {
        const after = form.querySelector(".js-after-code");
        if (after && !after.classList.contains("is-open")) {
            e.preventDefault();
            renderAlert(alertArea, "请先发送验证码，发送成功后再继续填写注册信息。", "danger");
            return;
        }
        setBusy(btn, true, "注册中...");
    });
}

function initSendCode() {
    const btn = $("#sendCodeBtn") || $(".js-send-code");
    const emailInput = $("#reg_email") || $("#email");
    const inviteInput = $("#reg_invite_code") || $("#invite_code");
    const alertArea = $("#registerAlert");
    if (!btn || !emailInput) return;

    let countdown = 0;
    const tick = () => {
        if (countdown <= 0) {
            btn.disabled = false;
            btn.textContent = btn.dataset.label || "发送验证码";
            return;
        }
        btn.textContent = `${countdown}s`;
        countdown -= 1;
        setTimeout(tick, 1000);
    };

    const validateEmail = (email) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

    btn.dataset.label = btn.textContent.trim() || "发送验证码";
    btn.addEventListener("click", async () => {
        const email = emailInput.value.trim();
        if (!email) {
            renderAlert(alertArea, "请先输入邮箱地址。", "danger");
            return;
        }
        if (!validateEmail(email)) {
            renderAlert(alertArea, "请输入有效的邮箱地址。", "danger");
            return;
        }

        if (isLazyTurnstileEnabled()) {
            try {
                const loaded = await ensureLazyTurnstileWidget();
                if (!loaded) {
                    renderAlert(alertArea, "人机验证尚未就绪，请稍后重试。", "danger");
                    return;
                }
            } catch (e) {
                renderAlert(alertArea, resolveTurnstileErrorMessage(e), "danger");
                return;
            }
        }

        if (hasTurnstileWidget()) {
            const token = getTurnstileToken();
            if (!token) {
                renderAlert(alertArea, "请先完成人机验证，通过后才可发送验证码。", "danger");
                return;
            }
        }

        btn.disabled = true;
        btn.textContent = "发送中...";
        try {
            const res = await fetch("/auth/api/send-code", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    email,
                    code_type: "register",
                    invite_code: inviteInput ? inviteInput.value.trim() : "",
                    turnstile_token: getTurnstileToken(),
                }),
            });
            const data = await readJsonSafely(res);
            if (res.ok && data && data.success) {
                renderAlert(alertArea, "验证码已发送到您的邮箱，请查收。", "success");
                countdown = 60;
                tick();
                openAfterCodeSection(formOrDocument(btn));
            } else {
                const msg =
                    (data && data.message) ||
                    (res.status >= 500 ? "服务器开小差了，请稍后再试。" : `发送失败（${res.status}）`);
                renderAlert(alertArea, msg, "danger");
                btn.disabled = false;
                btn.textContent = btn.dataset.label || "发送验证码";
                resetTurnstile();
            }
        } catch (e) {
            renderAlert(alertArea, `发送失败：${e.message || e}`, "danger");
            btn.disabled = false;
            btn.textContent = btn.dataset.label || "发送验证码";
            resetTurnstile();
        }
    });
}

function initRegisterOauthButtons() {
    const links = $all(".js-register-oauth");
    if (!links.length) return;

    links.forEach((link) => {
        link.addEventListener("click", (event) => {
            const inviteInputId = (link.dataset.inviteInput || "").trim();
            const inviteInput = inviteInputId ? document.getElementById(inviteInputId) : null;
            const inviteCode = inviteInput ? inviteInput.value.trim() : "";
            const alertArea = getRegisterAlertArea();
            const inviteRequired = (link.dataset.inviteRequired || "true") === "true";

            if (inviteRequired && !inviteCode) {
                event.preventDefault();
                renderAlert(alertArea, "请先填写邀请码，再选择注册渠道。", "danger");
                if (inviteInput) inviteInput.focus();
                return;
            }

            const target = new URL(link.getAttribute("href"), window.location.origin);
            if (inviteCode) {
                target.searchParams.set("invite_code", inviteCode);
            } else {
                target.searchParams.delete("invite_code");
            }
            if (!target.searchParams.get("redirect_url")) {
                target.searchParams.set("redirect_url", "/dashboard");
            }
            event.preventDefault();
            window.location.href = target.toString();
        });
    });
}

async function readJsonSafely(res) {
    try {
        const ct = (res.headers && res.headers.get && res.headers.get("content-type")) || "";
        if (ct.includes("application/json")) {
            return await res.json();
        }
        const text = await res.text();
        try {
            return JSON.parse(text);
        } catch {
            return { success: false, message: text || `请求失败（${res.status}）` };
        }
    } catch (e) {
        return { success: false, message: e && e.message ? e.message : String(e) };
    }
}

function formOrDocument(el) {
    const form = el && el.closest ? el.closest("form") : null;
    return form || document;
}

document.addEventListener("DOMContentLoaded", () => {
    syncRegistrationInviteUi();
    initTabs();
    initTyping();
    initPasswordToggles();
    initLoginSubmit();
    initRegisterSubmit();
    initSendCode();
    initRegisterOauthButtons();

    // Server-side render may require the expanded area visible (e.g., validation errors)
    $all(".js-after-code.is-open").forEach((section) => {
        section.querySelectorAll("[data-unlock-on-code=\"1\"]").forEach((el) => {
            el.disabled = false;
        });
    });
});
