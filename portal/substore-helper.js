(function () {
  const PANEL_ID = "substore-quick-import";
  const PANEL_STYLE_ID = "substore-quick-import-style";

  function normalizeUrl(value) {
    const raw = (value || "")
      .trim()
      .split(/\r?\n/)
      .map((item) => item.trim())
      .find(Boolean) || "";
    if (!raw) return "";
    if (/^https?:\/\//i.test(raw)) return raw;
    return "";
  }

  function deriveNameFromUrl(value) {
    const url = normalizeUrl(value);
    if (!url) return "";
    try {
      const parsed = new URL(url);
      return (parsed.hostname || "subscription").replace(/^www\./i, "");
    } catch {
      return "";
    }
  }

  function getLabelText(input) {
    const field = input.closest(".field") || input.closest(".nut-form-item") || input.parentElement;
    return (field && field.textContent ? field.textContent : "").replace(/\s+/g, "");
  }

  function isVisible(el) {
    if (!el || !(el instanceof HTMLElement)) return false;
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden";
  }

  function setNativeValue(input, nextValue) {
    const setter = Object.getOwnPropertyDescriptor(input.__proto__, "value")?.set;
    if (setter) {
      setter.call(input, nextValue);
    } else {
      input.value = nextValue;
    }
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function findCandidateInputs() {
    return Array.from(document.querySelectorAll("input, textarea")).filter(
      (el) => isVisible(el) && !el.disabled && !el.readOnly
    );
  }

  function findUrlInput(inputs) {
    const withUrlValue = inputs.find((input) => normalizeUrl(input.value));
    if (withUrlValue) return withUrlValue;

    return inputs.find((input) => {
      const label = getLabelText(input).toLowerCase();
      const placeholder = (input.getAttribute("placeholder") || "").toLowerCase();
      return (
        label.includes("链接") ||
        label.includes("url") ||
        placeholder.includes("https://") ||
        placeholder.includes("支持多行和参数") ||
        placeholder.includes("填写值或链接")
      );
    });
  }

  function findNameInput(inputs) {
    return (
      inputs.find((input) => {
        if (input.tagName.toLowerCase() !== "input") return false;
        const label = getLabelText(input);
        return label.includes("名称") && !label.includes("显示");
      }) ||
      inputs.find((input) => {
        if (input.tagName.toLowerCase() !== "input") return false;
        const placeholder = input.getAttribute("placeholder") || "";
        return placeholder.includes("标识名称") || placeholder.includes("名称");
      })
    );
  }

  function findDisplayNameInput(inputs) {
    return inputs.find((input) => {
      if (input.tagName.toLowerCase() !== "input") return false;
      const label = getLabelText(input);
      return label.includes("显示名称");
    });
  }

  function autoFillNames() {
    const inputs = findCandidateInputs();
    const urlInput = findUrlInput(inputs);
    const nameInput = findNameInput(inputs);
    if (!urlInput || !nameInput) return;

    const derivedName = deriveNameFromUrl(urlInput.value);
    if (!derivedName) return;

    const currentName = (nameInput.value || "").trim();
    if (!currentName || nameInput.dataset.autofilled === "true") {
      setNativeValue(nameInput, derivedName);
      nameInput.dataset.autofilled = "true";
    }

    const displayNameInput = findDisplayNameInput(inputs);
    if (displayNameInput) {
      const currentDisplay = (displayNameInput.value || "").trim();
      if (!currentDisplay || displayNameInput.dataset.autofilled === "true") {
        setNativeValue(displayNameInput, derivedName);
        displayNameInput.dataset.autofilled = "true";
      }
    }
  }

  function isSubManagementPage() {
    return /\/substore\/(?:subs)?(?:[/?#]|$)/.test(window.location.pathname);
  }

  function ensurePanelStyle() {
    if (document.getElementById(PANEL_STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = PANEL_STYLE_ID;
    style.textContent = `
      #${PANEL_ID} {
        position: fixed;
        right: 18px;
        top: 72px;
        z-index: 2147483646;
        width: min(360px, calc(100vw - 36px));
        padding: 16px;
        border-radius: 18px;
        border: 1px solid rgba(16, 35, 24, 0.14);
        background: rgba(255, 251, 245, 0.97);
        box-shadow: 0 18px 36px rgba(17, 26, 20, 0.18);
        backdrop-filter: blur(10px);
        font: 14px/1.5 "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
        color: #172018;
      }
      #${PANEL_ID}[data-hidden="true"] {
        display: none;
      }
      #${PANEL_ID} .ssh-title {
        margin: 0 0 6px;
        font-size: 16px;
        font-weight: 700;
      }
      #${PANEL_ID} .ssh-meta {
        margin: 0 0 12px;
        color: #647262;
        font-size: 12px;
        line-height: 1.6;
      }
      #${PANEL_ID} .ssh-group {
        display: grid;
        gap: 8px;
        margin-top: 10px;
      }
      #${PANEL_ID} .ssh-label {
        font-size: 12px;
        color: #647262;
      }
      #${PANEL_ID} input,
      #${PANEL_ID} select,
      #${PANEL_ID} button {
        font: inherit;
      }
      #${PANEL_ID} input,
      #${PANEL_ID} select {
        width: 100%;
        min-height: 42px;
        padding: 10px 12px;
        border: 1px solid rgba(16, 35, 24, 0.14);
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.94);
        color: #172018;
      }
      #${PANEL_ID} .ssh-row {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }
      #${PANEL_ID} .ssh-btn {
        border: 0;
        border-radius: 999px;
        padding: 10px 14px;
        cursor: pointer;
        font-weight: 700;
        color: #fff;
        background: linear-gradient(135deg, #1f7a57, #d28a37);
      }
      #${PANEL_ID} .ssh-btn.secondary {
        color: #172018;
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(16, 35, 24, 0.14);
      }
      #${PANEL_ID} .ssh-btn:disabled {
        opacity: 0.65;
        cursor: not-allowed;
      }
      #${PANEL_ID} .ssh-notice {
        min-height: 18px;
        font-size: 12px;
        color: #647262;
      }
      #${PANEL_ID} .ssh-notice.error {
        color: #b74c3f;
      }
      #${PANEL_ID} .ssh-divider {
        margin-top: 12px;
        padding-top: 12px;
        border-top: 1px dashed rgba(16, 35, 24, 0.14);
      }
      @media (max-width: 760px) {
        #${PANEL_ID} {
          left: 10px;
          right: 10px;
          top: auto;
          bottom: 10px;
          width: auto;
        }
      }
    `;
    document.head.appendChild(style);
  }

  async function api(path, options) {
    const response = await fetch(`/manage-api${path}`, {
      headers: {
        "Content-Type": "application/json",
      },
      ...(options || {}),
    });
    const payload = await response.json();
    if (!response.ok || payload.status !== "success") {
      throw new Error(payload.message || "请求失败");
    }
    return payload.data;
  }

  function setNotice(panel, message, isError) {
    const notice = panel.querySelector("[data-role='notice']");
    if (!notice) return;
    notice.textContent = message || "";
    notice.className = `ssh-notice${isError ? " error" : ""}`;
  }

  function buildOptionLabel(item) {
    const typeText = item.kind === "collection" ? "组合" : "单条";
    if (item.displayName) {
      return `[${typeText}] ${item.displayName} (${item.name})`;
    }
    return `[${typeText}] ${item.name}`;
  }

  function readSelectedSource(panel) {
    const select = panel.querySelector("[data-role='source-select']");
    const value = select ? select.value : "";
    if (!value) return null;
    const [kind, name] = value.split("::");
    if (!kind || !name) return null;
    return { kind, name };
  }

  function renderSourceOptions(panel, sources, selectedValue) {
    const select = panel.querySelector("[data-role='source-select']");
    const switchButton = panel.querySelector("[data-role='switch']");
    if (!select || !switchButton) return;

    const flat = [...(sources.subs || []), ...(sources.collections || [])];
    select.innerHTML = "";
    if (!flat.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "当前没有可切换的配置";
      select.appendChild(option);
      switchButton.disabled = true;
      return;
    }

    flat.forEach((item) => {
      const option = document.createElement("option");
      option.value = `${item.kind}::${item.name}`;
      option.textContent = buildOptionLabel(item);
      if (selectedValue && option.value === selectedValue) {
        option.selected = true;
      }
      select.appendChild(option);
    });
    switchButton.disabled = false;
  }

  async function refreshPanel(panel, statusMessage) {
    const [sources, status] = await Promise.all([api("/sources"), api("/status")]);
    const selectedKind = status.config.sourceKind || "sub";
    const selectedName = status.config.sourceName || "";
    const selectedValue = selectedName ? `${selectedKind}::${selectedName}` : "";
    renderSourceOptions(panel, sources, selectedValue);
    const current = panel.querySelector("[data-role='current']");
    if (current) {
      current.textContent = status.config.sourceUrl || "当前未绑定配置";
    }
    if (statusMessage) {
      setNotice(panel, statusMessage, false);
    }
  }

  async function handleImport(panel) {
    const input = panel.querySelector("[data-role='url']");
    const button = panel.querySelector("[data-role='import']");
    const url = normalizeUrl(input ? input.value : "");
    if (!url) {
      setNotice(panel, "请先输入有效的订阅链接", true);
      return;
    }

    button.disabled = true;
    setNotice(panel, "正在下载并应用订阅...", false);
    try {
      const result = await api("/source-url", {
        method: "POST",
        body: JSON.stringify({ url }),
      });
      await api("/sync", {
        method: "POST",
        body: "{}",
      });
      await refreshPanel(panel, `已应用: ${result.display_name || result.name}`);
    } catch (error) {
      setNotice(panel, error.message || "下载失败", true);
    } finally {
      button.disabled = false;
    }
  }

  async function handleSwitch(panel) {
    const button = panel.querySelector("[data-role='switch']");
    const selected = readSelectedSource(panel);
    if (!selected) {
      setNotice(panel, "当前没有可切换的配置", true);
      return;
    }

    button.disabled = true;
    setNotice(panel, "正在切换配置...", false);
    try {
      await api("/source", {
        method: "POST",
        body: JSON.stringify({
          mode: "substore",
          kind: selected.kind,
          name: selected.name,
        }),
      });
      await api("/sync", {
        method: "POST",
        body: "{}",
      });
      await refreshPanel(panel, `已切换到: ${selected.name}`);
    } catch (error) {
      setNotice(panel, error.message || "切换失败", true);
    } finally {
      button.disabled = false;
    }
  }

  async function ensureQuickPanel() {
    const hidden = !isSubManagementPage();
    let panel = document.getElementById(PANEL_ID);
    if (panel) {
      panel.dataset.hidden = hidden ? "true" : "false";
      if (!hidden) {
        await refreshPanel(panel);
      }
      return;
    }
    if (hidden) return;

    ensurePanelStyle();
    panel = document.createElement("section");
    panel.id = PANEL_ID;
    panel.innerHTML = `
      <div class="ssh-title">快速导入</div>
      <p class="ssh-meta">在订阅管理里直接输入订阅地址，下载后立即生成并切换配置，不再跳到首页处理。</p>
      <div class="ssh-group">
        <label class="ssh-label" for="ssh-url-input">订阅地址</label>
        <input id="ssh-url-input" data-role="url" type="url" placeholder="https://example.com/subscription" />
      </div>
      <div class="ssh-row">
        <button class="ssh-btn" data-role="import" type="button">下载并应用</button>
        <button class="ssh-btn secondary" data-role="refresh" type="button">刷新</button>
      </div>
      <div class="ssh-divider">
        <div class="ssh-group">
          <label class="ssh-label" for="ssh-source-select">切换已有配置</label>
          <select id="ssh-source-select" data-role="source-select"></select>
        </div>
        <div class="ssh-row">
          <button class="ssh-btn secondary" data-role="switch" type="button">切换配置</button>
        </div>
      </div>
      <div class="ssh-divider ssh-meta">
        当前生效配置：<span data-role="current">加载中...</span>
      </div>
      <div class="ssh-notice" data-role="notice"></div>
    `;
    document.body.appendChild(panel);

    panel.querySelector("[data-role='import']").addEventListener("click", () => {
      handleImport(panel);
    });
    panel.querySelector("[data-role='switch']").addEventListener("click", () => {
      handleSwitch(panel);
    });
    panel.querySelector("[data-role='refresh']").addEventListener("click", () => {
      refreshPanel(panel, "状态已刷新").catch((error) => {
        setNotice(panel, error.message || "刷新失败", true);
      });
    });

    await refreshPanel(panel);
  }

  document.addEventListener(
    "input",
    (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;
      if (target.getAttribute("placeholder")?.includes("唯一的标识名称")) {
        target.dataset.autofilled = "false";
      }
      if (target.getAttribute("placeholder")?.includes("输入展示的名称")) {
        target.dataset.autofilled = "false";
      }
      if (target.matches(`#${PANEL_ID} [data-role='url']`)) {
        return;
      }
      const value = normalizeUrl(target.value);
      if (!value) return;
      window.requestAnimationFrame(autoFillNames);
    },
    true
  );

  const observer = new MutationObserver(() => {
    window.requestAnimationFrame(autoFillNames);
    window.requestAnimationFrame(() => {
      ensureQuickPanel().catch(() => {});
    });
  });

  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
  });

  window.addEventListener("popstate", () => {
    ensureQuickPanel().catch(() => {});
  });

  window.requestAnimationFrame(autoFillNames);
  window.requestAnimationFrame(() => {
    ensureQuickPanel().catch(() => {});
  });
})();
