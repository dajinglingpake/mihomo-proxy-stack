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

首次启动或升级后启动：

```bash
docker compose up -d --build
```

启动完成后访问：

```text
http://<你的主机IP>:3001
```

只重建并重启本地 MetaCubeXD 面板：

```bash
scripts/upgrade-local-metacubexd.sh
```

该脚本会自动完成：

1. 校验 `vendor/metacubexd/compressed-dist-v1.261.8.tgz`
2. 构建 `mihomo-metacubexd:1.261.8`
3. 重启当前 `metacubexd` 服务
4. 等待 `3001` 面板可用并校验注入内容

## 远程一键部署

先复制本地配置模板并填写远程服务器信息：

```bash
cp scripts/upgrade-remote-mihomo.local.env.example scripts/upgrade-remote-mihomo.local.env
```

然后执行：

```bash
scripts/upgrade-remote-mihomo.sh
```

远程脚本会同步当前项目文件到目标目录，并执行 `docker compose up -d --build`。`scripts/upgrade-remote-mihomo.local.env` 包含远程账号等敏感配置，已被 `.gitignore` 忽略，不要提交。

查看远程服务状态：

```bash
scripts/upgrade-remote-mihomo.sh status
```

## 手动启动

```bash
docker compose up -d --build
```

## 默认端口

- 面板端口：`3001`
- Sub-Store 原始端口：`3002`
- Mihomo 控制端口：`19090`
- Mihomo 混合代理端口：`7890`

## 常用命令

```bash
docker compose up -d --build
docker compose restart
docker compose ps
docker compose logs -f mihomo
docker compose logs -f mihomo-sync
docker compose logs -f sub-store
docker compose logs -f metacubexd
```

## 说明

- 真实订阅地址、节点数据和缓存都会保留在本地
- 仓库内静态基线配置是 `config/base.yaml`
- 运行期生成的订阅配置是 `config/generated.yaml`，该文件不会纳入版本控制
- MetaCubeXD 上游静态面板不再提交解压目录，仓库只保留 release 压缩包 `vendor/metacubexd/compressed-dist-v1.261.8.tgz`
- 自定义注入文件位于 `ui-overrides/metacubexd/`，镜像构建时会覆盖到 Nginx 静态目录并 patch `index.html`
- 如果浏览器没有立刻看到最新界面，强刷 `3001` 页面即可
