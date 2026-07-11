(function () {
  const OPEN_ID = "config-helper-open";
  const PAGE_ID = "config-helper-page";
  const STYLE_ID = "config-helper-style";
  const PROXY_HELPER_ID = "proxy-mode-helper";
  const PAGE_SIZE = 10;
  const NODE_DELAY_TEST_URL = "https://www.gstatic.com/generate_204";
  const NODE_DELAY_TIMEOUT_MS = 5000;
  const NODE_DELAY_CONCURRENCY = 4;
  const SYNC_STEPS = [
    ["prepare", "读取配置"],
    ["subscription", "下载订阅"],
    ["render", "处理配置"],
    ["write-config", "写入配置"],
    ["geoip", "检查 GeoIP"],
    ["mmdb", "检查 MMDB"],
    ["geosite", "检查 GeoSite"],
    ["cache", "保存快照"],
    ["reload", "应用配置"],
    ["metadata", "更新状态"],
  ];
  const ACTIVE_UPDATE_PROGRESS_STEPS = [
    ["prepare", "读取当前订阅"],
    ["subscription", "下载最新订阅"],
    ["render", "处理订阅配置"],
    ["write-config", "写入运行配置"],
    ["snapshot", "校验并保存快照"],
    ["reload", "通知 Mihomo 热重载"],
    ["complete-update", "完成订阅更新"],
  ];
  const ACTIVE_UPDATE_PROGRESS_GROUPS = [[1], [2], [3], [4], [5, 6, 7, 8], [9], [10]];
  const SNAPSHOT_UPDATE_PROGRESS_STEPS = [
    ["prepare", "读取订阅信息"],
    ["subscription", "下载最新订阅"],
    ["render", "处理订阅配置"],
    ["snapshot", "保存配置快照"],
    ["complete-update", "完成订阅更新"],
  ];
  const SNAPSHOT_UPDATE_PROGRESS_GROUPS = [[1], [2], [3], [4, 5, 6, 7, 8], [9, 10]];

  const state = {
    currentPage: 0,
    flows: {},
    sources: [],
    status: null,
    navMountTimer: null,
    proxyModeTimer: null,
    proxyModeRendering: false,
    proxyHelperMarkup: "",
    proxyGroups: null,
    customGroups: [],
    customEditor: null,
    syncProgressTimer: null,
    syncProgressToken: null,
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
      #${OPEN_ID}[data-active="true"] {
        color: var(--color-primary) !important;
        background: color-mix(in oklch, var(--color-primary) 15%, transparent) !important;
      }
      #${OPEN_ID}[data-active="true"]:hover {
        background: color-mix(in oklch, var(--color-primary) 20%, transparent) !important;
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
        white-space: normal;
        overflow-wrap: anywhere;
      }
      #${PAGE_ID} .cfg-notice.error {
        color: #b74c3f;
      }
      #${PAGE_ID} .cfg-notice:empty {
        display: none;
      }
      #${PAGE_ID} .cfg-sync-progress {
        padding: 8px 12px 10px;
        cursor: help;
      }
      #${PAGE_ID} .cfg-sync-progress[hidden] {
        display: none;
      }
      #${PAGE_ID} .cfg-sync-progress-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 6px;
        color: #9fb0c3;
        font-size: 10px;
        line-height: 1.3;
      }
      #${PAGE_ID} .cfg-sync-progress-head strong {
        min-width: 0;
        color: #d4e2f0;
        font-weight: 700;
        overflow-wrap: anywhere;
      }
      #${PAGE_ID} .cfg-sync-track {
        height: 6px;
        overflow: hidden;
        border-radius: 3px;
        background: rgba(71, 85, 105, 0.34);
      }
      #${PAGE_ID} .cfg-sync-track > span {
        display: block;
        width: 0;
        height: 100%;
        background: #2f9e73;
        transition: width 180ms ease;
      }
      #${PAGE_ID} .cfg-sync-steps {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 6px 10px;
        margin-top: 8px;
      }
      #${PAGE_ID} .cfg-sync-step {
        display: flex;
        min-width: 0;
        align-items: center;
        gap: 5px;
        color: #718197;
        font-size: 10px;
        line-height: 1.25;
        white-space: normal;
      }
      #${PAGE_ID} .cfg-sync-step-label {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      #${PAGE_ID} .cfg-sync-step-time {
        flex: 0 0 auto;
        margin-left: auto;
        color: #718197;
        font-variant-numeric: tabular-nums;
      }
      #${PAGE_ID} .cfg-sync-step::before {
        width: 7px;
        height: 7px;
        flex: 0 0 7px;
        border-radius: 50%;
        background: #475569;
        content: "";
      }
      #${PAGE_ID} .cfg-sync-step.done {
        color: #71c6a2;
      }
      #${PAGE_ID} .cfg-sync-step.done::before {
        background: #2f9e73;
      }
      #${PAGE_ID} .cfg-sync-step.active {
        color: #d4e2f0;
        font-weight: 700;
      }
      #${PAGE_ID} .cfg-sync-step.active::before {
        background: #e6a23c;
        box-shadow: 0 0 0 3px rgba(230, 162, 60, 0.16);
      }
      #${PAGE_ID} .cfg-sync-step.error {
        color: #d46a5c;
      }
      #${PAGE_ID} .cfg-sync-step.error::before {
        background: #b74c3f;
      }
      #${PROXY_HELPER_ID} {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
        padding: 10px 12px;
        margin-bottom: 12px;
        border: 1px solid color-mix(in oklch, var(--color-primary) 22%, transparent);
        border-radius: 8px;
        background: color-mix(in oklch, var(--color-base-200) 82%, black);
        color: var(--color-base-content);
        font-size: 13px;
        line-height: 1.4;
      }
      #${PROXY_HELPER_ID} .pmh-title {
        font-weight: 700;
        color: var(--color-primary);
      }
      #${PROXY_HELPER_ID} button {
        height: 30px;
        border: 1px solid color-mix(in oklch, var(--color-base-content) 14%, transparent);
        border-radius: 7px;
        padding: 0 10px;
        background: color-mix(in oklch, var(--color-base-300) 74%, transparent);
        color: var(--color-base-content);
        font: inherit;
        cursor: pointer;
      }
      #${PROXY_HELPER_ID} button:disabled {
        opacity: 0.48;
        cursor: not-allowed;
      }
      #custom-proxy-group-modal {
        position: fixed;
        inset: 0;
        z-index: 80;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 18px;
        background: rgba(2, 8, 16, 0.72);
      }
      #custom-proxy-group-modal .cpg-dialog {
        width: min(980px, 100%);
        max-height: min(820px, 92vh);
        display: grid;
        grid-template-rows: auto auto 1fr auto;
        gap: 12px;
        border: 1px solid color-mix(in oklch, var(--color-primary) 20%, transparent);
        border-radius: 8px;
        background: #101923;
        color: var(--color-base-content);
        box-shadow: 0 24px 80px rgba(0, 0, 0, 0.42);
        overflow: hidden;
      }
      #custom-proxy-group-modal .cpg-header,
      #custom-proxy-group-modal .cpg-footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding: 12px;
        border-bottom: 1px solid rgba(71, 85, 105, 0.28);
      }
      #custom-proxy-group-modal .cpg-footer {
        border-top: 1px solid rgba(71, 85, 105, 0.28);
        border-bottom: 0;
      }
      #custom-proxy-group-modal .cpg-title {
        margin: 0;
        font-size: 14px;
        font-weight: 700;
      }
      #custom-proxy-group-modal .cpg-form {
        display: grid;
        grid-template-columns: 1fr 150px 220px;
        gap: 10px;
        padding: 0 12px;
      }
      #custom-proxy-group-modal label {
        display: grid;
        gap: 5px;
        min-width: 0;
        font-size: 11px;
        color: #93a4b8;
      }
      #custom-proxy-group-modal input,
      #custom-proxy-group-modal select {
        min-width: 0;
        height: 34px;
        border: 1px solid rgba(71, 85, 105, 0.58);
        border-radius: 7px;
        padding: 0 9px;
        background: rgba(15, 23, 42, 0.86);
        color: var(--color-base-content);
        font: inherit;
      }
      #custom-proxy-group-modal .cpg-body {
        display: grid;
        grid-template-columns: 1fr 1fr;
        min-height: 0;
        gap: 12px;
        padding: 0 12px;
      }
      #custom-proxy-group-modal .cpg-panel {
        min-height: 0;
        display: grid;
        grid-template-rows: auto auto 1fr;
        gap: 8px;
      }
      #custom-proxy-group-modal .cpg-panel-title {
        font-size: 12px;
        font-weight: 700;
      }
      #custom-proxy-group-modal .cpg-panel-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }
      #custom-proxy-group-modal .cpg-list {
        min-height: 240px;
        overflow: auto;
        border: 1px solid rgba(71, 85, 105, 0.38);
        border-radius: 8px;
        background: rgba(2, 8, 16, 0.22);
      }
      #custom-proxy-group-modal .cpg-row {
        display: grid;
        grid-template-columns: auto 1fr auto;
        align-items: center;
        gap: 8px;
        padding: 7px 9px;
        border-bottom: 1px solid rgba(71, 85, 105, 0.18);
        font-size: 12px;
      }
      #custom-proxy-group-modal .cpg-row.cpg-selected-row {
        grid-template-columns: auto minmax(0, 1fr) auto auto;
      }
      #custom-proxy-group-modal .cpg-row:last-child {
        border-bottom: 0;
      }
      #custom-proxy-group-modal .cpg-name {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      #custom-proxy-group-modal .cpg-row[draggable="true"] {
        cursor: grab;
      }
      #custom-proxy-group-modal .cpg-small-actions {
        display: inline-flex;
        gap: 4px;
      }
      #custom-proxy-group-modal button {
        height: 32px;
        border: 1px solid rgba(71, 85, 105, 0.52);
        border-radius: 7px;
        padding: 0 10px;
        background: rgba(30, 41, 59, 0.72);
        color: var(--color-base-content);
        font: inherit;
        cursor: pointer;
      }
      #custom-proxy-group-modal button:disabled {
        opacity: 0.48;
        cursor: not-allowed;
      }
      #custom-proxy-group-modal button.primary {
        border-color: var(--color-primary);
        background: color-mix(in oklch, var(--color-primary) 20%, transparent);
        color: var(--color-primary);
        font-weight: 700;
      }
      #custom-proxy-group-modal button.danger {
        border-color: #c53030;
        background: rgba(197, 48, 48, 0.18);
        color: #fca5a5;
        font-weight: 700;
      }
      #custom-proxy-group-modal .cpg-confirm-dialog {
        width: min(460px, 100%);
        grid-template-rows: auto auto;
      }
      #custom-proxy-group-modal .cpg-confirm-body {
        display: grid;
        gap: 8px;
        padding: 0 12px;
        font-size: 13px;
        line-height: 1.5;
      }
      #custom-proxy-group-modal .cpg-confirm-name {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: #e5eef8;
        font-weight: 700;
      }
      #custom-proxy-group-modal .cpg-muted {
        color: #93a4b8;
      }
      #custom-proxy-group-modal .cpg-delay {
        width: 64px;
        min-width: 64px;
        height: 18px;
        display: inline-flex;
        align-items: center;
        justify-content: flex-end;
        text-align: right;
        font-size: 11px;
        font-variant-numeric: tabular-nums;
        color: #93a4b8;
      }
      #custom-proxy-group-modal .cpg-delay.ok {
        color: #86efac;
      }
      #custom-proxy-group-modal .cpg-delay.warn {
        color: #facc15;
      }
      #custom-proxy-group-modal .cpg-delay.bad {
        color: #fca5a5;
      }
      #custom-proxy-group-modal .cpg-delay.cpg-testing {
        color: #8dc1ff;
      }
      #custom-proxy-group-modal .cpg-spinner {
        width: 10px;
        height: 10px;
        flex: 0 0 10px;
        box-sizing: border-box;
        display: inline-block;
        border: 1px solid rgba(141, 193, 255, 0.28);
        border-top-color: #8dc1ff;
        border-radius: 999px;
        animation: cpg-spin 0.8s linear infinite;
      }
      @keyframes cpg-spin {
        to {
          transform: rotate(360deg);
        }
      }
      #${PROXY_HELPER_ID} .pmh-custom {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 6px;
        width: 100%;
      }
      #${PROXY_HELPER_ID} .pmh-chip {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        max-width: 100%;
        padding: 3px 5px 3px 8px;
        border: 1px solid rgba(71, 85, 105, 0.42);
        border-radius: 7px;
        background: rgba(15, 23, 42, 0.42);
      }
      #${PROXY_HELPER_ID} .pmh-chip span {
        max-width: 220px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      @media (max-width: 980px) {
        #${PAGE_ID} .cfg-workbar {
          grid-template-columns: 1fr;
        }
        #custom-proxy-group-modal .cpg-form,
        #custom-proxy-group-modal .cpg-body {
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
        #${PAGE_ID} .cfg-sync-steps {
          grid-template-columns: repeat(2, minmax(0, 1fr));
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
    const raw = await response.text();
    let payload;
    try {
      payload = raw ? JSON.parse(raw) : null;
    } catch (error) {
      const status = response.status ? `HTTP ${response.status}` : "无状态码";
      throw new Error(`管理接口返回了非 JSON 响应（${status}），请查看 mihomo-sync 与 Nginx 日志`);
    }
    if (!response.ok || payload?.status !== "success") {
      throw new Error(payload?.message || `请求失败（HTTP ${response.status}）`);
    }
    return payload.data;
  }

  async function backendApi(path, options) {
    const response = await fetch(`/backend${path}`, {
      headers: {
        "Content-Type": "application/json",
      },
      ...(options || {}),
    });
    if (response.status === 204) return null;
    const text = await response.text();
    const payload = text ? JSON.parse(text) : null;
    if (!response.ok) {
      throw new Error(payload?.message || "请求失败");
    }
    return payload;
  }

  function findMainProxyGroup(proxies) {
    const groups = Object.values(proxies || {}).filter((item) => {
      const all = item?.all || [];
      return item?.type === "Selector" && all.includes("自动选择") && all.includes("故障转移");
    });
    return groups.find((item) => item.name !== "GLOBAL") || groups[0] || null;
  }

  function proxyHelperContainer() {
    return document.querySelector(".min-h-0.flex-1.overflow-y-auto");
  }

  function removeProxyModeHelper() {
    document.getElementById(PROXY_HELPER_ID)?.remove();
    state.proxyHelperMarkup = "";
  }

  function ensureProxyHelper(container) {
    let helper = document.getElementById(PROXY_HELPER_ID);
    if (!helper) {
      helper = document.createElement("div");
      helper.id = PROXY_HELPER_ID;
      helper.innerHTML = `
        <span class="pmh-custom">
          <span class="pmh-title">自定义策略组</span>
          <button type="button" disabled>创建策略组</button>
        </span>
      `;
      container.parentElement?.insertBefore(helper, container);
      state.proxyHelperMarkup = "";
    }
    return helper;
  }

  function setProxyHelperMarkup(helper, markup) {
    if (state.proxyHelperMarkup === markup && helper.innerHTML) return;
    helper.innerHTML = markup;
    state.proxyHelperMarkup = markup;
  }

  async function renderProxyModeHelper() {
    if (!location.hash.includes("/proxies")) {
      removeProxyModeHelper();
      return false;
    }
    const container = proxyHelperContainer();
    if (!container) return false;
    const helper = ensureProxyHelper(container);
    if (state.proxyModeRendering) return true;

    state.proxyModeRendering = true;
    try {
      const [payload, customPayload] = await Promise.all([backendApi("/proxies"), api("/custom-proxy-groups")]);
      const proxies = payload?.proxies || {};
      const customGroups = customPayload?.groups || [];
      state.proxyGroups = proxies;
      state.customGroups = customGroups;
      const group = findMainProxyGroup(proxies);
      const sourceGroup = group?.name || (proxies["故障转移"] ? "故障转移" : "");

      setProxyHelperMarkup(helper, `
        <span class="pmh-custom">
          <span class="pmh-title">自定义策略组</span>
          <button type="button" data-custom-create data-source="${escapeHtml(sourceGroup)}" ${sourceGroup ? "" : "disabled"}>创建策略组</button>
          ${customGroups.map((customGroup) => `
            <span class="pmh-chip">
              <span title="${escapeHtml(customGroup.name)}">${escapeHtml(customGroup.name)}</span>
              <button type="button" data-custom-edit="${escapeHtml(customGroup.name)}">编辑</button>
              <button type="button" data-custom-delete="${escapeHtml(customGroup.name)}">删除</button>
            </span>
          `).join("")}
        </span>
      `);
      return true;
    } finally {
      state.proxyModeRendering = false;
    }
  }

  function proxyGroupOptions(proxies) {
    return Object.values(proxies || {})
      .filter((item) => item?.all?.length)
      .map((item) => item.name)
      .sort((a, b) => a.localeCompare(b, "zh-CN"));
  }

  function proxyLeafNames(sourceGroup, proxies) {
    const names = proxies?.[sourceGroup]?.all || [];
    return names.filter((name) => {
      const item = proxies[name];
      return item && !item.all?.length && !["DIRECT", "REJECT", "REJECT-DROP", "PASS", "PASS-RULE"].includes(name);
    });
  }

  function countryToken(name) {
    const match = String(name || "").match(/[\u{1F1E6}-\u{1F1FF}]{2}/u);
    return match ? match[0] : "";
  }

  function filteredCandidateNames(editor) {
    const query = editor.filter.trim().toLowerCase();
    return proxyLeafNames(editor.sourceGroup, editor.proxies).filter((name) => {
      if (editor.country && (countryToken(name) || "__other__") !== editor.country) return false;
      return !query || name.toLowerCase().includes(query);
    });
  }

  function selectedCountries(editor) {
    const countries = new Map();
    proxyLeafNames(editor.sourceGroup, editor.proxies).forEach((name) => {
      const token = countryToken(name) || "__other__";
      countries.set(token, (countries.get(token) || 0) + 1);
    });
    return [...countries.entries()].sort((a, b) => b[1] - a[1]);
  }

  function nodeDelayResult(editor, name) {
    return editor.delayResults?.[name] || { state: "idle" };
  }

  function nodeDelayClass(result) {
    if (result.state === "testing") return "cpg-testing";
    if (result.state === "error") return "bad";
    if (result.state !== "ok") return "";
    if (result.delay <= 500) return "ok";
    if (result.delay <= 1200) return "warn";
    return "bad";
  }

  function nodeDelayText(result) {
    if (result.state === "error") return "超时";
    if (result.state === "ok") return `${result.delay} ms`;
    return "未测";
  }

  function nodeDelayMarkup(editor, name) {
    const result = nodeDelayResult(editor, name);
    if (result.state === "testing") {
      return '<span class="cpg-delay cpg-testing" title="测试中"><span class="cpg-spinner"></span></span>';
    }
    const title = result.error ? ` title="${escapeHtml(result.error)}"` : "";
    return `<span class="cpg-delay ${nodeDelayClass(result)}"${title}>${escapeHtml(nodeDelayText(result))}</span>`;
  }

  async function testNodeDelay(name) {
    const path = `/proxies/${encodeURIComponent(name)}/delay?timeout=${NODE_DELAY_TIMEOUT_MS}&url=${encodeURIComponent(NODE_DELAY_TEST_URL)}`;
    const payload = await backendApi(path);
    const delay = Number(payload?.delay);
    if (!Number.isFinite(delay)) throw new Error("测试失败");
    return Math.round(delay);
  }

  function sortSelectedByDelay(editor) {
    const originalIndex = new Map(editor.selected.map((name, index) => [name, index]));
    editor.selected = [...editor.selected].sort((left, right) => {
      const leftResult = nodeDelayResult(editor, left);
      const rightResult = nodeDelayResult(editor, right);
      const leftRank = leftResult.state === "ok" ? 0 : leftResult.state === "error" ? 1 : 2;
      const rightRank = rightResult.state === "ok" ? 0 : rightResult.state === "error" ? 1 : 2;
      if (leftRank !== rightRank) return leftRank - rightRank;
      if (leftRank === 0 && leftResult.delay !== rightResult.delay) return leftResult.delay - rightResult.delay;
      return (originalIndex.get(left) || 0) - (originalIndex.get(right) || 0);
    });
  }

  async function testNodesDelay(names) {
    const editor = state.customEditor;
    if (!editor || !names.length) return;
    const queue = [...new Set(names.filter(Boolean))];
    if (!queue.length) return;
    queue.forEach((name) => {
      editor.delayResults[name] = { state: "testing" };
    });
    renderCustomGroupModal();

    let cursor = 0;
    const worker = async () => {
      while (cursor < queue.length) {
        const name = queue[cursor];
        cursor += 1;
        try {
          const delay = await testNodeDelay(name);
          if (state.customEditor === editor) {
            editor.delayResults[name] = { state: "ok", delay };
            renderCustomGroupModal();
          }
        } catch (error) {
          if (state.customEditor === editor) {
            editor.delayResults[name] = { state: "error", error: error?.message || "测试失败" };
            renderCustomGroupModal();
          }
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(NODE_DELAY_CONCURRENCY, queue.length) }, worker));
  }

  function customGroupModal() {
    let modal = document.getElementById("custom-proxy-group-modal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "custom-proxy-group-modal";
      document.body.appendChild(modal);
    }
    return modal;
  }

  function closeCustomGroupModal() {
    state.customEditor = null;
    document.getElementById("custom-proxy-group-modal")?.remove();
  }

  function renderCustomGroupModal() {
    const editor = state.customEditor;
    if (!editor) return;
    const modal = customGroupModal();
    const groupNames = proxyGroupOptions(editor.proxies);
    const candidates = filteredCandidateNames(editor);
    const selected = new Set(editor.selected);
    const countries = selectedCountries(editor);
    const visibleSelectedCount = candidates.filter((name) => selected.has(name)).length;
    const allVisibleSelected = candidates.length > 0 && visibleSelectedCount === candidates.length;
    modal.innerHTML = `
      <div class="cpg-dialog">
        <div class="cpg-header">
          <h2 class="cpg-title">${editor.editingName ? "编辑自定义策略组" : "创建自定义策略组"}</h2>
          <button type="button" data-cpg-close>关闭</button>
        </div>
        <div class="cpg-form">
          <label>名称
            <input data-cpg-field="name" value="${escapeHtml(editor.name)}" placeholder="美国故障转移" />
          </label>
          <label>类型
            <select data-cpg-field="type">
              <option value="fallback" ${editor.type === "fallback" ? "selected" : ""}>故障转移</option>
              <option value="url-test" ${editor.type === "url-test" ? "selected" : ""}>自动选择</option>
              <option value="select" ${editor.type === "select" ? "selected" : ""}>手动选择</option>
            </select>
          </label>
          <label>复制来源
            <select data-cpg-field="sourceGroup">
              ${groupNames.map((name) => `<option value="${escapeHtml(name)}" ${editor.sourceGroup === name ? "selected" : ""}>${escapeHtml(name)}</option>`).join("")}
            </select>
          </label>
        </div>
        <div class="cpg-body">
          <div class="cpg-panel">
            <div class="cpg-panel-head">
              <div class="cpg-panel-title">候选节点</div>
              <div>${visibleSelectedCount} / ${candidates.length}</div>
            </div>
            <input data-cpg-field="filter" value="${escapeHtml(editor.filter)}" placeholder="搜索节点" />
            <div class="cpg-list">
              <div class="cpg-row">
                <input type="checkbox" data-cpg-toggle-visible ${allVisibleSelected ? "checked" : ""} />
                <span class="cpg-name">${candidates.length} / ${proxyLeafNames(editor.sourceGroup, editor.proxies).length}</span>
                <span class="cpg-small-actions">
                  <button type="button" data-cpg-country="" data-active="${editor.country === ""}">全部</button>
                  ${countries.slice(0, 8).map(([token, count]) => `<button type="button" data-cpg-country="${escapeHtml(token)}" data-active="${token === editor.country}">${escapeHtml(token === "__other__" ? "其他" : token)} ${count}</button>`).join("")}
                </span>
              </div>
              ${candidates.map((name) => `
                <label class="cpg-row">
                  <input type="checkbox" data-cpg-node="${escapeHtml(name)}" ${selected.has(name) ? "checked" : ""} />
                  <span class="cpg-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
                  <span>${escapeHtml(editor.proxies[name]?.type || "")}</span>
                </label>
              `).join("")}
            </div>
          </div>
          <div class="cpg-panel">
            <div class="cpg-panel-head">
              <div class="cpg-panel-title">已选节点顺序</div>
              <span class="cpg-small-actions">
                <button type="button" data-cpg-test-selected ${editor.selected.length ? "" : "disabled"}>测试已选</button>
                <button type="button" data-cpg-sort-delay ${editor.selected.length ? "" : "disabled"}>按延迟排序</button>
              </span>
            </div>
            <div>${editor.selected.length} 个节点，拖拽或用上下按钮调整优先级</div>
            <div class="cpg-list">
              ${editor.selected.map((name, index) => `
                <div class="cpg-row cpg-selected-row" draggable="true" data-cpg-selected-index="${index}">
                  <span>${index + 1}</span>
                  <span class="cpg-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
                  ${nodeDelayMarkup(editor, name)}
                  <span class="cpg-small-actions">
                    <button type="button" data-cpg-move="${index}" data-direction="-1">上</button>
                    <button type="button" data-cpg-move="${index}" data-direction="1">下</button>
                    <button type="button" data-cpg-remove="${index}">删</button>
                  </span>
                </div>
              `).join("") || '<div class="cpg-row"><span></span><span class="cpg-name">还没有选择节点</span><span></span></div>'}
            </div>
          </div>
        </div>
        <div class="cpg-footer">
          <span>${editor.editingName ? `正在编辑：${escapeHtml(editor.editingName)}` : "保存后会重载 mihomo 配置"}</span>
          <span class="cpg-small-actions">
            <button type="button" data-cpg-close>取消</button>
            <button type="button" class="primary" data-cpg-save>保存并重载</button>
          </span>
        </div>
      </div>
    `;
  }

  async function loadCustomGroupEditorData() {
    if (state.proxyGroups && Object.keys(state.proxyGroups).length) {
      return {
        proxies: state.proxyGroups,
        groups: state.customGroups || [],
      };
    }
    const [proxyPayload, customPayload] = await Promise.all([backendApi("/proxies"), api("/custom-proxy-groups")]);
    state.proxyGroups = proxyPayload?.proxies || {};
    state.customGroups = customPayload?.groups || [];
    return {
      proxies: state.proxyGroups,
      groups: state.customGroups,
    };
  }

  async function openCustomGroupModal(sourceGroup, editingName = "") {
    const { proxies, groups } = await loadCustomGroupEditorData();
    const editing = groups.find((group) => group.name === editingName);
    const fallbackSource = proxies[sourceGroup] ? sourceGroup : proxies["故障转移"] ? "故障转移" : proxyGroupOptions(proxies)[0] || "";
    state.customEditor = {
      proxies,
      groups,
      editingName,
      name: editing?.name || "",
      type: editing?.type || "fallback",
      sourceGroup: editing?.sourceGroup || fallbackSource,
      selected: [...(editing?.proxies || [])],
      delayResults: {},
      filter: "",
      country: "",
      dragIndex: null,
    };
    renderCustomGroupModal();
  }

  async function saveCustomGroupFromModal() {
    const editor = state.customEditor;
    if (!editor) return;
    const payload = {
      name: editor.name.trim(),
      type: editor.type,
      sourceGroup: editor.sourceGroup,
      proxies: editor.selected,
    };
    await api("/custom-proxy-groups", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    closeCustomGroupModal();
    window.location.reload();
  }

  function moveSelectedNode(index, direction) {
    const editor = state.customEditor;
    if (!editor) return;
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= editor.selected.length) return;
    const next = [...editor.selected];
    [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
    editor.selected = next;
    renderCustomGroupModal();
  }

  function setNodeSelected(name, checked) {
    const editor = state.customEditor;
    if (!editor) return;
    if (checked && !editor.selected.includes(name)) {
      editor.selected = [...editor.selected, name];
    } else if (!checked) {
      editor.selected = editor.selected.filter((item) => item !== name);
    }
    renderCustomGroupModal();
  }

  function setVisibleNodesSelected(checked) {
    const editor = state.customEditor;
    if (!editor) return;
    const visible = filteredCandidateNames(editor);
    if (checked) {
      const next = [...editor.selected];
      visible.forEach((name) => {
        if (!next.includes(name)) next.push(name);
      });
      editor.selected = next;
    } else {
      const visibleSet = new Set(visible);
      editor.selected = editor.selected.filter((name) => !visibleSet.has(name));
    }
    renderCustomGroupModal();
  }

  function openDeleteCustomGroupConfirm(name) {
    if (!name) return;
    state.customEditor = null;
    const modal = customGroupModal();
    modal.innerHTML = `
      <div class="cpg-dialog cpg-confirm-dialog">
        <div class="cpg-header">
          <h2 class="cpg-title">删除自定义策略组</h2>
        </div>
        <div class="cpg-confirm-body">
          <div>确认删除这个自定义策略组？</div>
          <div class="cpg-confirm-name" title="${escapeHtml(name)}">${escapeHtml(name)}</div>
          <div class="cpg-muted">删除后会重载 mihomo 配置，内置订阅策略组不会受影响。</div>
        </div>
        <div class="cpg-footer">
          <span></span>
          <span class="cpg-small-actions">
            <button type="button" data-cpg-close>取消</button>
            <button type="button" class="danger" data-cpg-delete-confirm="${escapeHtml(name)}">删除并重载</button>
          </span>
        </div>
      </div>
    `;
  }

  async function deleteCustomGroup(name) {
    if (!name) return;
    await api("/custom-proxy-groups-delete", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    window.location.reload();
  }

  function startProxyModeHelper() {
    if (state.proxyModeTimer) return;
    const tick = async () => {
      let rendered = false;
      try {
        rendered = await renderProxyModeHelper();
      } catch (error) {
        console.warn("failed to render proxy mode helper", error);
      } finally {
        const delay = location.hash.includes("/proxies") ? (rendered ? 3000 : 120) : 800;
        state.proxyModeTimer = window.setTimeout(tick, delay);
      }
    };
    tick();
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

  function setTitle(role, value) {
    const node = document.querySelector(`#${PAGE_ID} [data-role="${role}"]`);
    if (!node) return;
    if (value) {
      node.setAttribute("title", value);
    } else {
      node.removeAttribute("title");
    }
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

  function formatDurationMs(value) {
    if (value === null || value === undefined || value === "") return "等待";
    const milliseconds = Number(value);
    if (!Number.isFinite(milliseconds) || milliseconds < 0) return "等待";
    if (milliseconds < 1000) return `${Math.round(milliseconds)}ms`;
    const seconds = milliseconds / 1000;
    return `${seconds < 10 ? seconds.toFixed(2) : seconds.toFixed(1)}s`;
  }

  function normalizeSyncProgress(sync) {
    const trigger = String(sync?.sync_trigger || "");
    const isActiveUpdate = sync?.progress_profile === "active-update" || trigger === "api-update-active";
    const isSnapshotUpdate = sync?.progress_profile === "snapshot-update" || trigger === "api-update-inactive";
    const isUpdate = isActiveUpdate || isSnapshotUpdate;
    if (!isUpdate) return sync;

    const updateSteps = isActiveUpdate ? ACTIVE_UPDATE_PROGRESS_STEPS : SNAPSHOT_UPDATE_PROGRESS_STEPS;
    const updateGroups = isActiveUpdate ? ACTIVE_UPDATE_PROGRESS_GROUPS : SNAPSHOT_UPDATE_PROGRESS_GROUPS;
    const status = String(sync?.last_status || "");
    const complete = status === "ok" || sync?.current_stage === "complete";
    const originalIndex = Math.max(1, Number(sync?.current_stage_index || 1));
    const mappedIndex = complete
      ? updateSteps.length
      : Math.max(1, updateGroups.findIndex((indices) => indices.includes(originalIndex)) + 1);
    const history = Array.isArray(sync?.stage_history) ? sync.stage_history : [];
    const collapsedHistory = updateGroups.flatMap((indices, groupIndex) => {
      const position = groupIndex + 1;
      if (!complete && position >= mappedIndex) return [];
      const entries = history.filter((item) => indices.includes(Number(item.index)));
      return [{
        code: updateSteps[groupIndex][0],
        label: updateSteps[groupIndex][1],
        index: position,
        status: entries.some((item) => item.status === "error") ? "error" : "done",
        elapsed_ms: entries.reduce((total, item) => total + Number(item.elapsed_ms || 0), 0),
        detail: entries.length ? entries[entries.length - 1].detail : "",
      }];
    });
    const currentStep = updateSteps[mappedIndex - 1];

    return {
      ...sync,
      operation_label: "更新订阅",
      current_stage: complete ? "complete" : currentStep[0],
      current_stage_label: complete ? "更新订阅完成" : currentStep[1],
      current_stage_index: mappedIndex,
      current_stage_total: updateSteps.length,
      stage_labels: updateSteps.map(([code, label]) => ({ code, label })),
      stage_history: collapsedHistory,
    };
  }

  function renderSyncProgress(sync, forceVisible = false) {
    sync = normalizeSyncProgress(sync);
    const progress = document.querySelector(`#${PAGE_ID} [data-role="sync-progress"]`);
    const track = document.querySelector(`#${PAGE_ID} [data-role="sync-progress-track"]`);
    const steps = document.querySelector(`#${PAGE_ID} [data-role="sync-steps"]`);
    const summary = document.querySelector(`#${PAGE_ID} [data-role="sync-progress-summary"]`);
    const percent = document.querySelector(`#${PAGE_ID} [data-role="sync-progress-percent"]`);
    if (!progress || !track || !steps || !summary || !percent) return;

    const configuredSteps = Array.isArray(sync?.stage_labels)
      ? sync.stage_labels
          .filter((item) => item && item.code && item.label)
          .map((item) => [String(item.code), String(item.label)])
      : [];
    const stepDefinitions = configuredSteps.length ? configuredSteps : SYNC_STEPS;
    const index = Math.max(0, Number(sync?.current_stage_index || 0));
    const total = Math.max(stepDefinitions.length, Number(sync?.current_stage_total || 0));
    const status = String(sync?.last_status || "");
    const operationLabel = String(sync?.operation_label || "同步订阅");
    const complete = status === "ok" || sync?.current_stage === "complete";
    const visible = forceVisible || index > 0 || status === "running" || status === "error" || complete;
    progress.hidden = !visible;
    if (!visible) return;

    const progressValue = complete ? 100 : Math.min(100, Math.max(0, (index / total) * 100));
    track.style.width = `${progressValue}%`;
    const currentStartedAt = Number(sync?.current_stage_started_at || 0);
    const currentElapsedMs = currentStartedAt > 0 ? Math.max(0, Date.now() - currentStartedAt * 1000) : null;
    if (complete) {
      summary.textContent = sync?.current_stage_detail || "同步完成";
      percent.textContent = `${total}/${total} · 100% · ${formatDurationMs(sync?.sync_elapsed_ms)}`;
    } else if (status === "error") {
      summary.textContent = `${operationLabel}失败`;
      percent.textContent = `${index}/${total} · ${Math.round(progressValue)}%`;
    } else if (index > 0) {
      summary.textContent = `${operationLabel}进行中`;
      percent.textContent = `${index}/${total} · ${Math.round(progressValue)}% · ${formatDurationMs(currentElapsedMs)}`;
    } else {
      summary.textContent = `${operationLabel}准备中`;
      percent.textContent = "准备中";
    }

    const history = Array.isArray(sync?.stage_history) ? sync.stage_history : [];
    const historyByCode = new Map(history.map((item) => [item.code, item]));
    const tooltipLines = [];
    steps.innerHTML = stepDefinitions.map(([code, label], stepIndex) => {
      const position = stepIndex + 1;
      const stage = historyByCode.get(code);
      const active = !complete && position === index;
      const displayLabel = stage?.label || (active ? sync?.current_stage_label : label) || label;
      const durationMs = stage?.elapsed_ms ?? (active ? currentElapsedMs : null);
      const duration = formatDurationMs(durationMs);
      const detail = stage?.detail || (active ? sync?.current_stage_detail : "") || "";
      let className = "cfg-sync-step";
      if (complete || stage?.status === "done" || position < index) className += " done";
      if (stage?.status === "error" || (!complete && active && status === "error")) className += " error";
      if (!complete && active && status !== "error") className += " active";
      const title = `${displayLabel} · ${duration}${detail ? ` · ${detail}` : ""}`;
      tooltipLines.push(`${position}. ${title}`);
      return `<span class="${className}" data-sync-stage="${code}" title="${escapeHtml(title)}"><span class="cfg-sync-step-label">${escapeHtml(displayLabel)}</span><small class="cfg-sync-step-time">${duration}</small></span>`;
    }).join("");
    progress.title = tooltipLines.join("\n");
  }

  function startSyncProgressPolling(options = {}) {
    if (state.syncProgressTimer) {
      window.clearTimeout(state.syncProgressTimer);
      state.syncProgressTimer = null;
    }
    const token = {};
    state.syncProgressToken = token;
    const baselineSyncId = options.baselineSyncId || null;
    let observedNewSync = !options.waitForNewSync;
    let active = true;
    const isCurrent = () => active && state.syncProgressToken === token;
    const poll = async () => {
      if (!isCurrent()) return;
      try {
        const status = await api("/status");
        if (!isCurrent()) return;
        state.status = status;
        const sync = status.sync || {};
        if (!observedNewSync) {
          const syncChanged = Boolean(sync.sync_id && sync.sync_id !== baselineSyncId);
          const runningWithoutBaseline = !baselineSyncId && sync.last_status === "running";
          if (!syncChanged && !runningWithoutBaseline) return;
          observedNewSync = true;
        }
        renderSyncProgress(status.sync, true);
      } catch (error) {
        if (isCurrent()) console.warn("failed to poll sync progress", error);
      } finally {
        if (isCurrent()) state.syncProgressTimer = window.setTimeout(poll, 500);
      }
    };
    poll();
    return () => {
      active = false;
      if (state.syncProgressToken === token) {
        state.syncProgressToken = null;
      }
      if (state.syncProgressTimer && state.syncProgressToken === null) {
        window.clearTimeout(state.syncProgressTimer);
        state.syncProgressTimer = null;
      }
    };
  }

  function setOpen(nextOpen) {
    const page = document.getElementById(PAGE_ID);
    if (!page) return;
    page.dataset.open = nextOpen ? "true" : "false";
    syncNavButtonState();
  }

  function setNativeNavActive(active) {
    const nav = document.querySelector(".drawer-side nav");
    if (!nav) return;
    nav.querySelectorAll('a[href^="#/"], a[href*="#/"]').forEach((link) => {
      if (!(link instanceof HTMLElement)) return;
      if (active) {
        link.removeAttribute("aria-current");
        if (!("cfgInactiveClass" in link.dataset)) {
          link.dataset.cfgInactiveClass = link.className;
          link.dataset.cfgInactiveStyle = link.getAttribute("style") || "";
        }
        link.classList.remove("router-link-active", "router-link-exact-active", "is-active", "!text-primary", "text-primary", "bg-[color-mix(in_oklch,var(--color-primary)_15%,transparent)]");
        link.style.setProperty("color", "color-mix(in oklch, var(--color-base-content) 70%, transparent)", "important");
        link.style.setProperty("background", "transparent", "important");
      } else if (link.dataset.cfgInactiveClass) {
        link.className = link.dataset.cfgInactiveClass;
        if (link.dataset.cfgInactiveStyle) {
          link.setAttribute("style", link.dataset.cfgInactiveStyle);
        } else {
          link.removeAttribute("style");
        }
        delete link.dataset.cfgInactiveClass;
        delete link.dataset.cfgInactiveStyle;
      }
    });
  }

  function syncNavButtonState() {
    const toggle = document.getElementById(OPEN_ID);
    const page = document.getElementById(PAGE_ID);
    if (!toggle || !page) return;
    const active = page.dataset.open === "true";
    toggle.dataset.active = active ? "true" : "false";
    if (active) {
      toggle.setAttribute("aria-current", "page");
      toggle.style.setProperty("color", "var(--color-primary)", "important");
      toggle.style.setProperty("background", "color-mix(in oklch, var(--color-primary) 15%, transparent)", "important");
    } else {
      toggle.removeAttribute("aria-current");
      toggle.style.removeProperty("color");
      toggle.style.removeProperty("background");
    }
    toggle.className = active
      ? "group relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-[color-mix(in_oklch,var(--color-base-content)_70%,transparent)] no-underline transition-all duration-200 ease-in-out hover:bg-[var(--sidebar-hover)] hover:text-base-content bg-[color-mix(in_oklch,var(--color-primary)_15%,transparent)] !text-primary hover:bg-[color-mix(in_oklch,var(--color-primary)_20%,transparent)]"
      : "group relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-[color-mix(in_oklch,var(--color-base-content)_70%,transparent)] no-underline transition-all duration-200 ease-in-out hover:bg-[var(--sidebar-hover)] hover:text-base-content";
    setNativeNavActive(active);
  }

  function normalizeUrl(value) {
    return String(value || "").trim();
  }

  function findCurrentSource() {
    const config = state.status?.config;
    if (!config) return null;
    if (config.sourceName) {
      const currentKind = config.sourceKind || "sub";
      return state.sources.find((item) => item.kind === currentKind && item.name === config.sourceName) || null;
    }
    const activeUrl = normalizeUrl(config.sourceUrl);
    if (!activeUrl) return null;
    return state.sources.find((item) => normalizeUrl(item.url) === activeUrl) || null;
  }

  function activeValue() {
    const current = findCurrentSource();
    return current ? `${current.kind}::${current.name}` : "";
  }

  function currentSourceText() {
    const config = state.status?.config;
    if (!config) return "当前未绑定配置";

    const current = findCurrentSource();
    if (current) {
      return current.displayName || current.name;
    }
    if (config.sourceName) {
      return config.sourceName;
    }
    if (config.sourceUrl) {
      try {
        return new URL(config.sourceUrl).hostname;
      } catch (_) {
        return "订阅链接";
      }
    }
    return "当前未绑定配置";
  }

  function currentTransportText() {
    return state.status?.config?.sourceTransport || "未知";
  }

  function currentParseFormatText() {
    return state.status?.config?.parseFormat || "未知";
  }

  function currentStatusText(item, current) {
    if (!current) return "未启用";
    if (item.kind === "collection") {
      return "当前使用（组合）";
    }
    return "当前使用";
  }

  function currentActionText(item, current) {
    if (!current) return "设为当前";
    return "当前配置";
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
        const statusLabel = currentStatusText(item, current);
        const useLabel = currentActionText(item, current);
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
            <td>${current ? `<span class="cfg-tag">${escapeHtml(statusLabel)}</span>` : '<span class="cfg-tag idle">未启用</span>'}</td>
            <td>
              <div class="cfg-row-actions">
                <button class="cfg-btn secondary" type="button" data-role="use-item" data-kind="${escapeHtml(item.kind)}" data-name="${escapeHtml(item.name)}" ${current ? "disabled" : ""}>${escapeHtml(useLabel)}</button>
                <button class="cfg-btn" type="button" data-role="update-item" data-kind="${escapeHtml(item.kind)}" data-name="${escapeHtml(item.name)}">更新</button>
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

    setText("mode", status.config.mode === "substore" ? "订阅列表模式" : "订阅链接模式");
    setText("transport", currentTransportText());
    setText("format", currentParseFormatText());
    setText("sync-time", status.sync.last_sync_at || "尚未同步");
    setText("interval", `${status.config.intervalSeconds} 秒`);
    setText("current", currentSourceText());
    setTitle("current", status.config.sourceUrl || "");

    renderSyncProgress(status.sync);
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
    setNotice("", false);
    renderSyncProgress(
      {
        last_status: "running",
        operation_label: "下载并应用",
        current_stage_index: 0,
        current_stage_total: SYNC_STEPS.length,
        stage_labels: SYNC_STEPS.map(([code, label]) => ({ code, label })),
      },
      true,
    );
    const stopPolling = startSyncProgressPolling({
      baselineSyncId: state.status?.sync?.sync_id || null,
      waitForNewSync: true,
    });
    try {
      await api("/source-url-apply", {
        method: "POST",
        body: JSON.stringify({ url }),
      });
      stopPolling();
      state.currentPage = 0;
      await refresh();
    } catch (error) {
      setNotice(error.message || "下载失败", true);
    } finally {
      stopPolling();
      button.disabled = false;
    }
  }

  async function switchSource(kind, name) {
    setNotice("", false);
    renderSyncProgress(
      {
        last_status: "running",
        current_stage: "prepare",
        current_stage_label: "读取本地配置",
        current_stage_index: 1,
        current_stage_total: SYNC_STEPS.length,
        current_stage_started_at: Date.now() / 1000,
        stage_history: [],
      },
      true,
    );
    const stopPolling = startSyncProgressPolling({
      baselineSyncId: state.status?.sync?.sync_id || null,
      waitForNewSync: true,
    });
    try {
      await api("/source-switch", {
        method: "POST",
        body: JSON.stringify({
          kind,
          name,
        }),
      });
      stopPolling();
      await refresh();
    } catch (error) {
      setNotice(error.message || "切换失败", true);
    } finally {
      stopPolling();
    }
  }

  async function updateSource(kind, name) {
    const button = document.querySelector(
      `#${PAGE_ID} [data-role="update-item"][data-kind="${CSS.escape(kind)}"][data-name="${CSS.escape(name)}"]`,
    );
    const isCurrent = activeValue() === `${kind}::${name}`;
    const updateSteps = isCurrent ? ACTIVE_UPDATE_PROGRESS_STEPS : SNAPSHOT_UPDATE_PROGRESS_STEPS;
    if (button) button.disabled = true;
    setNotice("", false);
    renderSyncProgress(
      {
        last_status: "running",
        operation_label: "更新订阅",
        progress_profile: isCurrent ? "active-update" : "snapshot-update",
        current_stage: "prepare",
        current_stage_label: updateSteps[0][1],
        current_stage_index: 1,
        current_stage_total: updateSteps.length,
        current_stage_started_at: Date.now() / 1000,
        stage_history: [],
        stage_labels: updateSteps.map(([code, label]) => ({ code, label })),
      },
      true,
    );
    const stopPolling = startSyncProgressPolling({
      baselineSyncId: state.status?.sync?.sync_id || null,
      waitForNewSync: true,
    });
    try {
      await api("/source-update", {
        method: "POST",
        body: JSON.stringify({ kind, name }),
      });
      stopPolling();
      await refresh();
    } catch (error) {
      setNotice(error.message || "更新失败", true);
    } finally {
      stopPolling();
      if (button) button.disabled = false;
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
            </div>
          </div>
          <div class="cfg-notice" data-role="notice"></div>
          <div class="cfg-sync-progress" data-role="sync-progress" hidden>
            <div class="cfg-sync-progress-head">
              <strong data-role="sync-progress-summary">等待同步</strong>
              <span data-role="sync-progress-percent">0%</span>
            </div>
            <div class="cfg-sync-track"><span data-role="sync-progress-track"></span></div>
            <div class="cfg-sync-steps" data-role="sync-steps"></div>
          </div>
          <div class="cfg-info-row">
            <div class="cfg-info-items">
              <div class="cfg-info-item">模式: <strong data-role="mode">加载中</strong></div>
              <div class="cfg-info-item">来源类型: <strong data-role="transport">加载中</strong></div>
              <div class="cfg-info-item">订阅格式: <strong data-role="format">加载中</strong></div>
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
      const updateButton = target.closest('[data-role="update-item"]');
      if (updateButton instanceof HTMLElement) {
        await updateSource(updateButton.dataset.kind || "sub", updateButton.dataset.name || "");
        return;
      }
      const deleteButton = target.closest('[data-role="delete-item"]');
      if (deleteButton instanceof HTMLElement) {
        await deleteSource(deleteButton.dataset.kind || "sub", deleteButton.dataset.name || "");
      }
    });

    document.addEventListener("click", async (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const createButton = target.closest(`#${PROXY_HELPER_ID} [data-custom-create]`);
      if (createButton instanceof HTMLElement) {
        await openCustomGroupModal(createButton.dataset.source || "故障转移");
        return;
      }
      const editButton = target.closest(`#${PROXY_HELPER_ID} [data-custom-edit]`);
      if (editButton instanceof HTMLElement) {
        await openCustomGroupModal("", editButton.dataset.customEdit || "");
        return;
      }
      const deleteButton = target.closest(`#${PROXY_HELPER_ID} [data-custom-delete]`);
      if (deleteButton instanceof HTMLElement) {
        openDeleteCustomGroupConfirm(deleteButton.dataset.customDelete || "");
        return;
      }
      if (target.closest("#custom-proxy-group-modal [data-cpg-close]")) {
        closeCustomGroupModal();
        return;
      }
      const confirmDeleteButton = target.closest("#custom-proxy-group-modal [data-cpg-delete-confirm]");
      if (confirmDeleteButton instanceof HTMLElement) {
        await deleteCustomGroup(confirmDeleteButton.dataset.cpgDeleteConfirm || "");
        return;
      }
      if (target.closest("#custom-proxy-group-modal [data-cpg-save]")) {
        await saveCustomGroupFromModal();
        return;
      }
      if (target.closest("#custom-proxy-group-modal [data-cpg-test-selected]") && state.customEditor) {
        await testNodesDelay([...state.customEditor.selected]);
        return;
      }
      if (target.closest("#custom-proxy-group-modal [data-cpg-sort-delay]") && state.customEditor) {
        sortSelectedByDelay(state.customEditor);
        renderCustomGroupModal();
        return;
      }
      const countryButton = target.closest("#custom-proxy-group-modal [data-cpg-country]");
      if (countryButton instanceof HTMLElement && state.customEditor) {
        state.customEditor.country = countryButton.dataset.cpgCountry || "";
        renderCustomGroupModal();
        return;
      }
      const moveButton = target.closest("#custom-proxy-group-modal [data-cpg-move]");
      if (moveButton instanceof HTMLElement) {
        moveSelectedNode(Number(moveButton.dataset.cpgMove), Number(moveButton.dataset.direction));
        return;
      }
      const removeButton = target.closest("#custom-proxy-group-modal [data-cpg-remove]");
      if (removeButton instanceof HTMLElement && state.customEditor) {
        state.customEditor.selected.splice(Number(removeButton.dataset.cpgRemove), 1);
        renderCustomGroupModal();
      }
    });

    document.addEventListener("input", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement) || !state.customEditor) return;
      if (target.dataset.cpgField === "name") state.customEditor.name = target.value;
      if (target.dataset.cpgField === "filter") {
        state.customEditor.filter = target.value;
        renderCustomGroupModal();
      }
    });

    document.addEventListener("change", (event) => {
      const target = event.target;
      if (!state.customEditor) return;
      if (target instanceof HTMLSelectElement && target.dataset.cpgField === "type") {
        state.customEditor.type = target.value;
        renderCustomGroupModal();
        return;
      }
      if (target instanceof HTMLSelectElement && target.dataset.cpgField === "sourceGroup") {
        state.customEditor.sourceGroup = target.value;
        state.customEditor.selected = [];
        state.customEditor.delayResults = {};
        state.customEditor.filter = "";
        state.customEditor.country = "";
        renderCustomGroupModal();
        return;
      }
      if (target instanceof HTMLInputElement && target.dataset.cpgToggleVisible !== undefined) {
        setVisibleNodesSelected(target.checked);
        return;
      }
      if (target instanceof HTMLInputElement && target.dataset.cpgNode) {
        setNodeSelected(target.dataset.cpgNode, target.checked);
      }
    });

    document.addEventListener("dragstart", (event) => {
      const row = event.target instanceof HTMLElement ? event.target.closest("#custom-proxy-group-modal [data-cpg-selected-index]") : null;
      if (!(row instanceof HTMLElement) || !state.customEditor) return;
      state.customEditor.dragIndex = Number(row.dataset.cpgSelectedIndex);
      event.dataTransfer?.setData("text/plain", row.dataset.cpgSelectedIndex || "");
    });

    document.addEventListener("dragover", (event) => {
      if (event.target instanceof HTMLElement && event.target.closest("#custom-proxy-group-modal [data-cpg-selected-index]")) {
        event.preventDefault();
      }
    });

    document.addEventListener("drop", (event) => {
      const row = event.target instanceof HTMLElement ? event.target.closest("#custom-proxy-group-modal [data-cpg-selected-index]") : null;
      if (!(row instanceof HTMLElement) || !state.customEditor) return;
      event.preventDefault();
      const from = state.customEditor.dragIndex;
      const to = Number(row.dataset.cpgSelectedIndex);
      if (from === null || Number.isNaN(from) || Number.isNaN(to) || from === to) return;
      const next = [...state.customEditor.selected];
      const [item] = next.splice(from, 1);
      next.splice(to, 0, item);
      state.customEditor.selected = next;
      state.customEditor.dragIndex = null;
      renderCustomGroupModal();
    });

    const ensureMounted = () => scheduleEnsureMounted(page);
    window.addEventListener("hashchange", () => {
      setOpen(false);
      ensureMounted();
      renderProxyModeHelper().catch((error) => console.warn("failed to update proxy mode helper", error));
    });
    startProxyModeHelper();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    mount();
  }
})();
