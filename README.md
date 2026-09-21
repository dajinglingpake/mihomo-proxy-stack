# Mihomo Proxy Stack

一个基于 `mihomo + MetaCubeXD + Sub-Store` 的单机代理管理项目。

专门为无界面的Linux操作系统使用，市面上主要都是客户端软件导致没法在无界面的操作系统上运行，故做了web版本以保证跨平台的兼容性。

启动后直接打开 `3001` 面板即可使用。导入订阅、更新订阅、切换配置这些操作，都可以在面板左侧的 `订阅` 页面完成。

## 组件

- `mihomo`：代理核心
- `MetaCubeXD`：主控制面板
- `Sub-Store`：订阅源管理与导出
- `mihomo-sync`：订阅同步、流量缓存、面板管理 API

## 当前使用方式

启动后访问：

- 面板地址：`http://<你的主机IP>:3001`

进入面板后：

1. 在左侧导航点击 `订阅`
2. 在订阅页直接填写订阅链接
3. 点击 `下载并应用`
4. 后续可以在同一页完成：
   - 更新当前订阅
   - 切换已有订阅
   - 删除订阅
   - 查看已用 / 总量、有效期、订阅更新时间

## 快速启动

首次启动或升级后启动，直接运行本地一键脚本：

```bash
scripts/upgrade-local-mihomo.sh
```

该脚本会执行完整打包启动流程：

1. 校验本地工具和 MetaCubeXD 面板资源
2. 构建本项目自定义镜像并重建整个 stack
3. 等待 `3001` 面板可用
4. 校验 MetaCubeXD 版本和本项目注入内容

首次启动和后续升级都走这个脚本，不需要手动执行 Docker Compose 启动命令。启动完成后访问：

```text
http://<你的主机IP>:3001
```

## 远程一键部署

先复制本地配置模板并填写远程服务器信息：

```bash
cp scripts/upgrade-remote-mihomo.local.env.example scripts/upgrade-remote-mihomo.local.env
```

然后执行：

```bash
scripts/upgrade-remote-mihomo.sh
```

远程脚本会在本地构建项目自定义镜像，同步当前项目文件和镜像到目标目录，并在远程重建整个 stack。`scripts/upgrade-remote-mihomo.local.env` 包含远程账号等敏感配置，已被 `.gitignore` 忽略，不要提交。

`REBUILD=0` 只跳过外部镜像拉取，仍会在本地构建项目自定义镜像并重启远程 stack，确保面板注入脚本和同步服务代码生效。

查看远程服务状态：

```bash
scripts/upgrade-remote-mihomo.sh status
```

## Ping0 IP 纯净度检测

在自定义策略组里点 `测试已选（延迟 + Ping0）`，每个已选节点会测出延迟和 Ping0 风控值/纯净度。

检测按顺序尝试这些链路，**默认不需要人工做任何事**：

1. **直连抓取**（默认首选）：把出口切到目标节点后直接拉 `ping0.cc` 首页，读服务端渲染
   出来的数据。它不启动浏览器，也就没有浏览器指纹——实测多数节点直连一次就成功，
   2 秒左右出结果，反而是浏览器更容易被 Cloudflare 判成机器人。
2. **Ping0 浏览器服务**：只有直连被 Cloudflare 挡住时才启动（`ping0-browser` 容器，
   Xvfb + noVNC）。挑战交给真实浏览器自己跑完，界面上不会出现「请人工验证」。
3. **备用数据源**：上面都走不通时改用不需要验证码的公开接口
   （`ip-api.com`）。它给不出 ping0 的风控百分比，但「是不是机房 IP、是不是已知代理
   出口、ASN、位置」这些纯净度的硬指标能确定，面板会标注`风控待定`并说明原因。

浏览器服务的说明：

- **检测走 ping0 首页而不是 `/ip/{ip}/` 查询页**。ping0 只对「访问者自己的出口 IP」
  服务端渲染真实数据，指定 IP 查询（`ping0.cc/ip/1.2.3.4/`）对代理出口只返回空壳页，
  风控值恒为模板默认的 `0%`。所以流程是：把出口切到目标节点 → 打开首页 →
  读页面里服务端注入的数据（IP、风控、位置、ASN、类型、原生、共享人数、适用场景）
- 检测结果里 `ip` 是实际测到的出口地址（可能是 IPv6，取决于节点是否放行 v6）
- **点一下节点那一行**会弹出详情面板，显示上面全部字段和操作按钮（再点一次、点别处或按
  Esc 收起）。这一列只有 190px 宽且会截断，所以详情不放悬停提示里，也不塞在行内
- 检测时会临时把出口策略组切到目标节点，测完自动恢复，因此同一时刻只处理一个节点
- **同一出口 IP 的结果会复用**：多个节点常常共用同一个出口（机场 NAT 出口、故障转移落到
  同一台机器），检测前先用一次轻量请求确认出口 IP，命中缓存就直接返回，不再启动浏览器。
  实测单次检测从约 10 秒降到约 1 秒，同时因为请求次数少了，触发验证码的概率也明显下降。
  缓存按出口 IP 索引（不是按节点名），落在 `.ping0-cache.json`，重启容器后仍然有效；
  面板里会标注「复用 N 分钟前的结果」，并有「重新检测（忽略缓存）」按钮强制刷新一次
- **整份缓存可以一键清掉**：「已选节点顺序」标题栏里的`清除 Ping0 缓存`（节点详情面板里
  也有`清除全部缓存`）会清空后端全部条目并提示清了几条，同时把界面上那些「复用 N 分钟前」
  的结果一起作废，避免看起来还在用旧值。清完再点「测试已选」就是全量重测
- 容器里默认以有头模式跑（Xvfb + noVNC）；headless 更容易被 Cloudflare 拦截。
  想在本机无 X 环境跑冒烟，加 `PING0_HEADLESS=1`
- 自动化阶段会注入反检测脚本（`navigator.webdriver`、UA/platform/plugins/WebGL
  一致性），否则 Cloudflare 直接把 Playwright 驱动的浏览器判成机器，连挑战都不给过
- **请求频率是最关键的变量**：密集检测会把整段出口打成高风险，之后连一次都过不去
  （表现为所有节点一起返回验证页）。默认已带节流与退避，批量检测宁可慢一点
- **整个过程不需要人工验证，代码里也没有这条路径**：挑战由真实浏览器自己跑完（托管
  挑战跑完 JS 后通常直接放行），等不到放行就刷新一次，还不行才换数据源。不破解、
  不识别、不自动点击验证码——那是对方刻意设计的访问控制，绕过它既不合规，也会随对方
  策略升级而失效。真正有效的是让请求根本走不到挑战
- **降低触发验证码的概率**：基线出口 IP 走 `ipv4.ping0.cc` 纯文本接口而不是首页
  （首页访问次数减半）；两次检测之间留最小间隔（`PING0_MIN_INTERVAL_SECONDS`）；
  被挡住后先冷却再自动重试一次（`PING0_AUTO_RETRY` / `PING0_RETRY_COOLDOWN_SECONDS`）；
  同一出口的结果本来就复用缓存，请求次数少了自然不容易被风控
- `6080` 端口默认无密码，不要把它暴露到公网；需要密码时配置 `PING0_VNC_PASSWORD`

相关配置（`config/stack.local.env`）：

```text
PING0_BROWSER_URL="http://127.0.0.1:3021"
PING0_FALLBACK_SOURCE="ip-api"       # 被挡时的备用数据源，填 off 表示禁用
PING0_MIN_INTERVAL_SECONDS="2"       # 两次访问 ping0.cc 的最小间隔，别把出口打成高风险
PING0_AUTO_RETRY="1"                 # 被 Cloudflare 挡住后自动冷却重试的次数
PING0_RETRY_COOLDOWN_SECONDS="20"    # 每次重试前冷却的秒数
PING0_VNC_PASSWORD=""                # noVNC 密码，留空表示无密码
PING0_CACHE_TTL_SECONDS="21600"      # 出口 IP 结果复用有效期（秒），填 0 表示每次都重测
```

浏览器容器侧（`docker-compose.yml` 里 `ping0-browser` 的 environment，只在直连被挡时才用得上）：

```text
PING0_MIN_INTERVAL_SECONDS="2"       # 两次检测之间的最小间隔
PING0_AUTO_RETRY="1"                 # 被 Cloudflare 挡住后自动重试的次数
PING0_RETRY_COOLDOWN_SECONDS="20"    # 每次重试前的冷却秒数
PING0_HEADLESS="0"                   # 有头模式，headless 几乎必被 Cloudflare 拦
```


构建浏览器镜像需要下载约 300MB 的 Chromium，国内直连几乎必挂在 playwright 的 30s 超时上。
镜像里已经做了三级兜底：**代理优先 → npmmirror 镜像源 → 官方源**，代理失败还会退到直连重试一轮。
只要构建日志最后出现 `浏览器安装完成` 就成功了。

在 `.env` 里写一次即可（只在 build 阶段生效，不会注入容器运行时）：

```bash
HTTP_PROXY=http://192.168.3.28:7890
HTTPS_PROXY=http://192.168.3.28:7890
PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright   # 可选，换下载源
PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple             # 可选，换 pip 源
```

```
[build] 下载浏览器（proxy）：https://cdn.npmmirror.com/binaries/playwright
[build] 浏览器安装完成
```

只强校验完整 Chromium（检测跑的是 Xvfb 有头模式），`chromium-headless-shell` 下载失败不影响构建。

单独检测一个节点：

```bash
docker compose exec ping0-browser python /app/scripts/ping0_browser.py --check "节点名称"
```

## 默认端口

- 面板端口：`3001`
- Sub-Store 原始端口：`3002`
- Mihomo 控制端口：`19090`
- Mihomo 混合代理端口：`7890`
- Ping0 浏览器服务：`3021`
- Ping0 远程桌面（noVNC）：`6080`

## 常用命令

```bash
scripts/upgrade-local-mihomo.sh
scripts/upgrade-local-mihomo.sh status
docker compose ps
docker compose logs -f mihomo
docker compose logs -f mihomo-sync
docker compose logs -f sub-store
docker compose logs -f metacubexd
docker compose logs -f ping0-browser
```

## 说明

- 真实订阅地址、节点数据和缓存都会保留在本地
- 仓库内静态基线配置是 `config/base.yaml`
- 运行期生成的订阅配置是 `config/generated.yaml`，该文件不会纳入版本控制
- 一键部署脚本会先拉取外部镜像，拉取失败会停止部署，避免复用旧镜像。默认不限制拉取时长；需要强制限制时可用 `PULL_TIMEOUT_SECONDS=300 scripts/upgrade-local-mihomo.sh`
- 自定义注入文件位于 `ui-overrides/metacubexd/`，镜像构建时会覆盖到 Nginx 静态目录并 patch `index.html`
- 如果浏览器没有立刻看到最新界面，强刷 `3001` 页面即可
