(function () {
  const OPEN_ID = "config-helper-open";
  const PAGE_ID = "config-helper-page";
  const STYLE_ID = "config-helper-style";
  const PAGE_SIZE = 10;

  const state = {
    currentPage: 0,
    flows: {},
    sources: [],
    status: null,
    navMountTimer: null,
  };

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      #${OPEN_ID} {
        border: 0;
        width: 100%;
        cursor: pointer;
        font-family: inherit;
        font-size: 0.875rem;
        font-weight: 500;
        line-height: 1.25rem;
        letter-spacing: normal;
        background: transparent;
        text-align: left;
        -webkit-appearance: none;
        appearance: none;
      }
      #cfg-nav-item {
        list-style: none;
      }
      #${OPEN_ID} .cfg-nav-dot {
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
      }
      #${OPEN_ID} .cfg-nav-dot svg {
        width: 1.25rem;
        height: 1.25rem;
        fill: none;
        stroke: currentColor;
        stroke-width: 2;
        stroke-linecap: round;
        stroke-linejoin: round;
      }
      #${OPEN_ID} .cfg-nav-label {
        flex: 1 1 auto;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: 0.875rem;
        font-weight: 500;
        line-height: 1.25rem;
      }
      #${OPEN_ID} .cfg-nav-indicator {
        display: none;
      }
      #${OPEN_ID}[data-active="true"] .cfg-nav-indicator {
        display: block;
      }
      #${PAGE_ID} {
        position: absolute;
        inset: 0;
        z-index: 20;
        display: flex;
        justify-content: center;
        padding: 12px;
        overflow: auto;
        background: rgba(11, 18, 24, 0.94);
        backdrop-filter: blur(8px);
      }
      #${PAGE_ID}[data-open="false"] {
        display: none;
      }
      #${PAGE_ID} .cfg-shell {
        width: min(1560px, 100%);
        min-height: 100%;
        display: grid;
        grid-template-rows: auto 1fr;
        gap: 4px;
      }
      #${PAGE_ID} .cfg-topbar {
        display: flex;
        justify-content: flex-start;
        gap: 12px;
        align-items: center;
        padding: 0 2px;
      }
      #${PAGE_ID} .cfg-title {
        margin: 0;
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.02em;
        line-height: 1.2;
        color: #93a4b8;
      }
      #${PAGE_ID} .cfg-card {
        border: 1px solid rgba(71, 85, 105, 0.38);
        border-radius: 8px;
        background: #101923;
        padding: 10px;
        box-shadow: 0 16px 48px rgba(2, 8, 16, 0.35);
      }
      #${PAGE_ID} .cfg-main {
        display: flex;
        flex-direction: column;
        min-height: 0;
        padding: 0;
        overflow: hidden;
      }
      #${PAGE_ID} .cfg-workbar {
        display: grid;
        grid-template-columns: minmax(360px, 1fr) auto;
        gap: 10px;
        align-items: center;
        padding: 12px;
        border-bottom: 1px solid rgba(71, 85, 105, 0.28);
      }
      #${PAGE_ID} .cfg-field {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
      }
      #${PAGE_ID} .cfg-label {
        font-size: 11px;
        color: #93a4b8;
        white-space: nowrap;
      }
      #${PAGE_ID} input,
      #${PAGE_ID} button {
        font: inherit;
      }
      #${PAGE_ID} input {
        width: 100%;
        min-height: 30px;
        padding: 5px 10px;
        border: 1px solid rgba(71, 85, 105, 0.52);
        border-radius: 4px;
        background: #0b1218;
        color: #e5eef8;
      }
      #${PAGE_ID} .cfg-actions,
      #${PAGE_ID} .cfg-head-actions {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
      }
      #${PAGE_ID} .cfg-btn {
        border: 1px solid rgba(71, 85, 105, 0.52);
        border-radius: 4px;
        padding: 6px 10px;
        cursor: pointer;
        font-weight: 600;
        font-size: 11px;
        color: #dbe7f3;
        background: #162331;
      }
      #${PAGE_ID} .cfg-btn.primary {
        color: #fff;
        border-color: #2563eb;
        background: #2563eb;
      }
      #${PAGE_ID} .cfg-btn.danger {
        color: #fff;
        border-color: #c53030;
        background: #c53030;
      }
      #${PAGE_ID} .cfg-btn:disabled {
        opacity: 0.68;
        cursor: not-allowed;
      }
      #${PAGE_ID} .cfg-info-row {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        align-items: center;
        padding: 8px 12px;
        border-bottom: 1px solid rgba(71, 85, 105, 0.2);
        background: #0d151d;
      }
      #${PAGE_ID} .cfg-info-items {
        display: flex;
        gap: 18px;
        align-items: center;
        flex-wrap: wrap;
        min-width: 0;
      }
      #${PAGE_ID} .cfg-info-item {
        font-size: 11px;
        color: #9fb0c3;
      }
      #${PAGE_ID} .cfg-info-item strong {
        color: #e5eef8;
      }
      #${PAGE_ID} .cfg-list-head {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        align-items: center;
        padding: 10px 12px 8px;
        margin-bottom: 0;
      }
      #${PAGE_ID} .cfg-list-title {
        font-size: 12px;
        font-weight: 700;
        color: #dbe7f3;
      }
      #${PAGE_ID} .cfg-list-copy {
        display: none;
        margin-top: 2px;
        font-size: 11px;
        color: #647262;
      }
      #${PAGE_ID} .cfg-pager {
        display: inline-flex;
        gap: 6px;
        align-items: center;
      }
      #${PAGE_ID} .cfg-page-indicator {
        min-width: 64px;
        text-align: center;
        font-size: 10px;
        color: #93a4b8;
      }
      #${PAGE_ID} .cfg-table-wrap {
        overflow: auto;
        border: 1px solid rgba(71, 85, 105, 0.36);
        border-radius: 4px;
        background: #0f1822;
        min-height: 140px;
        max-height: calc(100vh - 230px);
        margin: 0 12px 12px;
      }
      #${PAGE_ID} table {
        width: 100%;
        border-collapse: collapse;
        min-width: 1120px;
      }
      #${PAGE_ID} th,
      #${PAGE_ID} td {
        padding: 8px 10px;
        text-align: left;
        border-bottom: 1px solid rgba(71, 85, 105, 0.22);
        vertical-align: middle;
        font-size: 11px;
      }
      #${PAGE_ID} th {
        position: sticky;
        top: 0;
        z-index: 1;
        background: #131f2b;
        color: #93a4b8;
        font-weight: 700;
        white-space: nowrap;
      }
      #${PAGE_ID} tr:last-child td {
        border-bottom: 0;
      }
      #${PAGE_ID} tbody tr:hover {
        background: #152433;
      }
      #${PAGE_ID} tr.active-row {
        background: #1a2b3b;
      }
      #${PAGE_ID} .cfg-name {
        font-weight: 700;
        color: #e5eef8;
      }
      #${PAGE_ID} .cfg-sub {
        margin-top: 3px;
        color: #7f93a8;
        font-size: 10px;
      }
      #${PAGE_ID} .cfg-url {
        max-width: 560px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: #b5c3d3;
      }
      #${PAGE_ID} .cfg-tag {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 20px;
        padding: 1px 7px;
        border-radius: 4px;
        background: rgba(37, 99, 235, 0.18);
        color: #8dc1ff;
        font-size: 10px;
        font-weight: 700;
        white-space: nowrap;
      }
      #${PAGE_ID} .cfg-tag.idle {
        background: rgba(71, 85, 105, 0.26);
        color: #93a4b8;
      }
      #${PAGE_ID} .cfg-row-actions {
        display: inline-flex;
        gap: 6px;
        flex-wrap: wrap;
      }
      #${PAGE_ID} .cfg-empty {
        padding: 18px;
        color: #93a4b8;
        font-size: 11px;
      }
      #${PAGE_ID} .cfg-notice {
        min-height: 18px;
        margin: 0;
        padding: 6px 12px 0;
        font-size: 11px;
        color: #9fb0c3;
      }
      #${PAGE_ID} .cfg-notice.error {
        color: #b74c3f;
      }
      @media (max-width: 980px) {
        #${PAGE_ID} .cfg-workbar {
          grid-template-columns: 1fr;
        }
      }
      @media (max-width: 760px) {
        #${PAGE_ID} {
          padding: 8px;
        }
        #${PAGE_ID} .cfg-topbar {
          align-items: flex-start;
          flex-direction: column;
        }
        #${PAGE_ID} .cfg-field {
          flex-direction: column;
          align-items: stretch;
        }
        #${PAGE_ID} .cfg-info-row,
        #${PAGE_ID} .cfg-list-head {
          flex-direction: column;
          align-items: flex-start;
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

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function setText(role, value) {
    const node = document.querySelector(`#${PAGE_ID} [data-role="${role}"]`);
    if (node) node.textContent = value || "";
  }

  function formatBytes(bytes, base = 1024) {
    const value = Number(bytes || 0);
    if (!Number.isFinite(value) || value <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let index = 0;
    let size = value;
    while (size >= base && index < units.length - 1) {
      size /= base;
      index += 1;
    }
    const digits = size >= 100 || index === 0 ? 0 : size >= 10 ? 1 : 2;
    return `${size.toFixed(digits)} ${units[index]}`;
  }

  function formatTime(value) {
    const timestamp = Number(value || 0);
    if (!Number.isFinite(timestamp) || timestamp <= 0) return "未知";
    return new Date(timestamp * 1000).toLocaleString("zh-CN", { hour12: false });
  }

  function getFlowText(flow) {
    if (!flow) return "-";
    const upload = Number(flow.usage?.upload || 0);
    const download = Number(flow.usage?.download || 0);
    const used = upload + download;
    const total = Number(flow.total || 0);
    return `${formatBytes(used)} / ${formatBytes(total)}`;
  }

  function getExpireText(flow) {
    if (!flow) return "-";
    const expire = Number(flow.expires || 0);
    if (!Number.isFinite(expire) || expire <= 0) return "-";
    return formatTime(expire);
  }

  function getUpdatedAtText(flow) {
    if (!flow) return "-";
    const cachedAt = Number(flow.cached_at || 0);
    if (!Number.isFinite(cachedAt) || cachedAt <= 0) return "-";
    return formatTime(cachedAt);
  }

  function setNotice(message, isError) {
    const notice = document.querySelector(`#${PAGE_ID} [data-role="notice"]`);
    if (!notice) return;
    notice.textContent = message || "";
    notice.className = `cfg-notice${isError ? " error" : ""}`;
  }

  function setOpen(nextOpen) {
    const page = document.getElementById(PAGE_ID);
    if (!page) return;
    page.dataset.open = nextOpen ? "true" : "false";
    syncNavButtonState();
  }

  function syncNavButtonState() {
    const toggle = document.getElementById(OPEN_ID);
    const page = document.getElementById(PAGE_ID);
    if (!toggle || !page) return;
    const active = page.dataset.open === "true";
    toggle.dataset.active = active ? "true" : "false";
    toggle.className = active
      ? "group relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-[color-mix(in_oklch,var(--color-base-content)_70%,transparent)] no-underline transition-all duration-200 ease-in-out hover:bg-[var(--sidebar-hover)] hover:text-base-content bg-[color-mix(in_oklch,var(--color-primary)_15%,transparent)] !text-primary hover:bg-[color-mix(in_oklch,var(--color-primary)_20%,transparent)]"
      : "group relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-[color-mix(in_oklch,var(--color-base-content)_70%,transparent)] no-underline transition-all duration-200 ease-in-out hover:bg-[var(--sidebar-hover)] hover:text-base-content";
  }

  function activeValue() {
    return state.status?.config?.sourceName
      ? `${state.status.config.sourceKind || "sub"}::${state.status.config.sourceName}`
      : "";
  }

  function renderTable() {
    const body = document.querySelector(`#${PAGE_ID} [data-role="table-body"]`);
    const indicator = document.querySelector(`#${PAGE_ID} [data-role="page-indicator"]`);
    const prev = document.querySelector(`#${PAGE_ID} [data-role="prev-page"]`);
    const next = document.querySelector(`#${PAGE_ID} [data-role="next-page"]`);
    if (!body || !indicator || !prev || !next) return;

    const total = state.sources.length;
    if (!total) {
      state.currentPage = 0;
      indicator.textContent = "0 / 0";
      prev.disabled = true;
      next.disabled = true;
      body.innerHTML = '<tr><td colspan="8" class="cfg-empty">当前还没有可管理的配置。</td></tr>';
      return;
    }

    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (state.currentPage >= totalPages) {
      state.currentPage = totalPages - 1;
    }
    const start = state.currentPage * PAGE_SIZE;
    const pageItems = state.sources.slice(start, start + PAGE_SIZE);
    const active = activeValue();

    indicator.textContent = `${state.currentPage + 1} / ${totalPages}`;
    prev.disabled = state.currentPage <= 0;
    next.disabled = state.currentPage >= totalPages - 1;

    body.innerHTML = pageItems
      .map((item) => {
        const current = `${item.kind}::${item.name}` === active;
        const typeLabel = item.kind === "collection" ? "组合" : "单条";
        const flow = item.kind === "sub" ? state.flows[item.name] : null;
        const title = item.displayName || item.name;
        const subtitle = item.displayName && item.displayName !== item.name ? item.name : "";
        return `
          <tr class="${current ? "active-row" : ""}">
            <td>
              <div class="cfg-name">${escapeHtml(title)}</div>
              ${subtitle ? `<div class="cfg-sub">${escapeHtml(subtitle)}</div>` : ""}
            </td>
            <td>${typeLabel}</td>
            <td title="${escapeHtml(item.url || "本地/无 URL 配置")}" class="cfg-url">${escapeHtml(item.url || "本地/无 URL 配置")}</td>
            <td>${escapeHtml(getFlowText(flow))}</td>
            <td>${escapeHtml(getExpireText(flow))}</td>
            <td>${escapeHtml(getUpdatedAtText(flow))}</td>
            <td>${current ? '<span class="cfg-tag">当前使用</span>' : '<span class="cfg-tag idle">未启用</span>'}</td>
            <td>
              <div class="cfg-row-actions">
                <button class="cfg-btn secondary" type="button" data-role="use-item" data-kind="${escapeHtml(item.kind)}" data-name="${escapeHtml(item.name)}">设为当前</button>
                <button class="cfg-btn danger" type="button" data-role="delete-item" data-kind="${escapeHtml(item.kind)}" data-name="${escapeHtml(item.name)}">删除</button>
              </div>
            </td>
          </tr>
        `;
      })
      .join("");
  }

  async function refresh(statusMessage) {
    const [status, sources, flowCache] = await Promise.all([api("/status"), api("/sources"), api("/flow-cache")]);
    state.status = status;
    state.sources = [...(sources.subs || []), ...(sources.collections || [])];
    state.flows = flowCache || {};

    setText("mode", status.config.mode === "substore" ? "订阅配置跟随中" : "原始远程订阅");
    setText("sync-time", status.sync.last_sync_at || "尚未同步");
    setText("interval", `${status.config.intervalSeconds} 秒`);
    setText("current", status.config.sourceUrl || "当前未绑定配置");

    renderTable();

    if (statusMessage) {
      setNotice(statusMessage, false);
    }
  }

  async function importByUrl() {
    const input = document.querySelector(`#${PAGE_ID} [data-role="url"]`);
    const button = document.querySelector(`#${PAGE_ID} [data-role="import"]`);
    const url = (input && input.value ? input.value : "").trim();
    if (!/^https?:\/\//i.test(url)) {
      setNotice("请先输入有效的订阅链接", true);
      return;
    }
    button.disabled = true;
    setNotice("正在下载并应用订阅...", false);
    try {
      const result = await api("/source-url", {
        method: "POST",
        body: JSON.stringify({ url }),
      });
      await api("/sync", {
        method: "POST",
        body: "{}",
      });
      state.currentPage = 0;
      await refresh(`已应用: ${result.display_name || result.name}`);
    } catch (error) {
      setNotice(error.message || "下载失败", true);
    } finally {
      button.disabled = false;
    }
  }

  async function updateCurrentSubscription() {
    if (!state.status?.config?.sourceName) {
      setNotice("当前没有可更新的订阅来源", true);
      return;
    }
    const button = document.querySelector(`#${PAGE_ID} [data-role="sync-current"]`);
    if (button) button.disabled = true;
    setNotice("正在更新当前订阅...", false);
    try {
      const result = await api("/sync", {
        method: "POST",
        body: "{}",
      });
      await refresh(result.message || "当前订阅已更新");
    } catch (error) {
      setNotice(error.message || "更新订阅失败", true);
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function switchSource(kind, name) {
    setNotice("正在切换配置...", false);
    try {
      await api("/source", {
        method: "POST",
        body: JSON.stringify({
          mode: "substore",
          kind,
          name,
        }),
      });
      await api("/sync", {
        method: "POST",
        body: "{}",
      });
      await refresh(`已切换到: ${name}`);
    } catch (error) {
      setNotice(error.message || "切换失败", true);
    }
  }

  async function deleteSource(kind, name) {
    setNotice(`正在删除配置: ${name}`, false);
    try {
      const result = await api("/source-delete", {
        method: "POST",
        body: JSON.stringify({ kind, name }),
      });
      await refresh(result.active_cleared ? `已删除 ${name}，当前激活配置已清空` : `已删除 ${name}`);
    } catch (error) {
      setNotice(error.message || "删除失败", true);
    }
  }

  function ensureNavButton() {
    const nav = document.querySelector(".drawer-side nav");
    if (!nav) return null;
    const list = nav.querySelector("ul");
    if (!list) return null;
    let navItem = document.getElementById("cfg-nav-item");
    let button = document.getElementById(OPEN_ID);
    if (!button) {
      navItem = document.createElement("li");
      navItem.id = "cfg-nav-item";
      navItem.className = "animate-[slideIn_0.3s_ease-out_backwards]";
      button = document.createElement("button");
      button.id = OPEN_ID;
      button.type = "button";
      button.className = "group relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-[color-mix(in_oklch,var(--color-base-content)_70%,transparent)] no-underline transition-all duration-200 ease-in-out hover:bg-[var(--sidebar-hover)] hover:text-base-content";
      button.innerHTML = '<div class="cfg-nav-dot transition-transform duration-200 ease-in-out group-hover:scale-110" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M6.75 4.75h10.5a1 1 0 0 1 1 1v12.5l-6.25-3-6.25 3V5.75a1 1 0 0 1 1-1Z"></path><path d="M9 8.5h6"></path><path d="M9 11.5h4.5"></path></svg></div><span class="cfg-nav-label">订阅</span><div class="cfg-nav-indicator absolute top-1/2 left-0 h-[60%] w-[3px] -translate-y-1/2 animate-[indicatorIn_0.2s_ease-out] rounded-r-sm bg-primary"></div>';
      button.addEventListener("click", () => {
        const page = document.getElementById(PAGE_ID);
        if (!page) return;
        if (page.dataset.open === "true") {
          setOpen(false);
          return;
        }
        setOpen(true);
        refresh().catch((error) => {
          setNotice(error.message || "加载配置失败", true);
        });
      });
      navItem.appendChild(button);
    }
    const rulesItem = list.querySelector('a[href*="#/rules"]')?.closest("li");
    const insertBefore = rulesItem?.nextElementSibling || null;
    if (navItem && rulesItem) {
      navItem.style.animationDelay = "125ms";
      if (navItem.parentElement !== list || navItem.previousElementSibling !== rulesItem) {
        list.insertBefore(navItem, insertBefore);
      }
    } else if (navItem && navItem.parentElement !== list) {
      navItem.style.animationDelay = "125ms";
      list.appendChild(navItem);
    }
    nav.querySelectorAll('a[href^="#/"], a[href*="#/"]').forEach((link) => {
      if (link.dataset.cfgCloseBound === "true") return;
      link.dataset.cfgCloseBound = "true";
      link.addEventListener("click", () => setOpen(false));
    });
    syncNavButtonState();
    return button;
  }

  function ensurePageHost(page) {
    const host = document.querySelector(".drawer-content");
    if (!host || !page) return null;
    if (host.style.position !== "relative") {
      host.style.position = "relative";
    }
    if (page.parentElement !== host) {
      host.appendChild(page);
    }
    return host;
  }

  function scheduleEnsureMounted(page) {
    if (state.navMountTimer) {
      window.clearTimeout(state.navMountTimer);
      state.navMountTimer = null;
    }
    let attempts = 0;
    const ensureMounted = () => {
      const navButton = ensureNavButton();
      const host = ensurePageHost(page);
      if (navButton && host) {
        state.navMountTimer = null;
        return;
      }
      if (attempts >= 30) {
        state.navMountTimer = null;
        return;
      }
      attempts += 1;
      state.navMountTimer = window.setTimeout(ensureMounted, 100);
    };
    ensureMounted();
  }

  function mount() {
    if (document.getElementById(PAGE_ID)) return;
    ensureStyle();

    const page = document.createElement("section");
    page.id = PAGE_ID;
    page.dataset.open = "false";
    page.innerHTML = `
      <div class="cfg-shell">
        <div class="cfg-topbar">
          <h1 class="cfg-title">订阅配置</h1>
        </div>

        <div class="cfg-card cfg-main">
          <div class="cfg-workbar">
            <div class="cfg-field">
              <label class="cfg-label" for="cfg-url-input">订阅地址</label>
              <input id="cfg-url-input" data-role="url" type="url" placeholder="https://example.com/subscription" />
            </div>
            <div class="cfg-actions">
              <button class="cfg-btn primary" data-role="import" type="button">下载并应用</button>
              <button class="cfg-btn" data-role="sync-current" type="button">更新当前订阅</button>
            </div>
          </div>
          <div class="cfg-notice" data-role="notice"></div>
          <div class="cfg-info-row">
            <div class="cfg-info-items">
              <div class="cfg-info-item">模式: <strong data-role="mode">加载中</strong></div>
              <div class="cfg-info-item">当前来源: <strong data-role="current">加载中</strong></div>
              <div class="cfg-info-item">最近同步: <strong data-role="sync-time">加载中</strong></div>
              <div class="cfg-info-item">同步间隔: <strong data-role="interval">加载中</strong></div>
            </div>
          </div>
          <div class="cfg-list-head">
            <div class="cfg-list-title">订阅列表</div>
            <div class="cfg-head-actions">
              <button class="cfg-btn" data-role="prev-page" type="button">上一页</button>
              <div class="cfg-page-indicator" data-role="page-indicator">0 / 0</div>
              <button class="cfg-btn" data-role="next-page" type="button">下一页</button>
            </div>
          </div>
          <div class="cfg-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>名称</th>
                  <th>类型</th>
                  <th>订阅链接</th>
                  <th>已用 / 总量</th>
                  <th>有效期</th>
                  <th>订阅更新时间</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody data-role="table-body"></tbody>
            </table>
          </div>
        </div>
      </div>
    `;

    scheduleEnsureMounted(page);
    page.querySelector('[data-role="import"]').addEventListener("click", importByUrl);
    page.querySelector('[data-role="sync-current"]').addEventListener("click", updateCurrentSubscription);
    page.querySelector('[data-role="prev-page"]').addEventListener("click", () => {
      if (state.currentPage > 0) {
        state.currentPage -= 1;
        renderTable();
      }
    });
    page.querySelector('[data-role="next-page"]').addEventListener("click", () => {
      const totalPages = Math.max(1, Math.ceil(state.sources.length / PAGE_SIZE));
      if (state.currentPage < totalPages - 1) {
        state.currentPage += 1;
        renderTable();
      }
    });

    page.addEventListener("click", async (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const useButton = target.closest('[data-role="use-item"]');
      if (useButton instanceof HTMLElement) {
        await switchSource(useButton.dataset.kind || "sub", useButton.dataset.name || "");
        return;
      }
      const deleteButton = target.closest('[data-role="delete-item"]');
      if (deleteButton instanceof HTMLElement) {
        await deleteSource(deleteButton.dataset.kind || "sub", deleteButton.dataset.name || "");
      }
    });

    const ensureMounted = () => scheduleEnsureMounted(page);
    window.addEventListener("hashchange", () => {
      setOpen(false);
      ensureMounted();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    mount();
  }
})();
