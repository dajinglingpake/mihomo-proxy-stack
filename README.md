# Mihomo Proxy Stack

一个面向个人服务器部署的 `mihomo + MetaCubeXD + Sub-Store` 组合项目，目标是提供：

- 可公开提交的安全默认配置
- 自动同步订阅并热重载 `mihomo`
- 开箱可用的 Web 面板与订阅管理入口
- 对本机敏感运行态数据的隔离

## 仓库约定

- `config/config.yaml`：可提交的安全启动配置，默认可启动，但不会包含你的真实节点。
- `config/stack.env`：可提交的示例运行参数，发布前需要替换 `SUBSCRIPTION_URL` 等占位值。
- `sub-store-data/sub-store.json`：可提交的脱敏初始化数据。
- `sub-store-data/root.json`：可提交的空缓存文件。
- `config/*.local.*`、`sub-store-data/*.local.json`：本机敏感备份，不会提交。

## 目录结构

```text
.
├── config/              # mihomo 配置、UI 资源与运行参数模板
├── nginx/               # MetaCubeXD Nginx 配置
├── portal/              # 入口页静态资源
├── scripts/             # 订阅同步与辅助脚本
├── sub-store-data/      # Sub-Store 初始化数据与运行缓存
└── ui-official/         # MetaCubeXD 前端资源
```

## 功能说明

- `mihomo`：代理核心，使用宿主网络模式运行。
- `metacubexd`：提供 Mihomo Web 面板。
- `proxy-portal`：提供统一入口页。
- `sub-store`：管理订阅源、生成适合 Mihomo 的订阅内容。
- `mihomo-sync`：定时拉取订阅、写入 `config/config.yaml` 并通知 Mihomo 热重载。

## Web 入口

- Mihomo 面板: `http://<你的主机IP>:3001`
- Sub-Store: `http://<你的主机IP>:3002`

## 当前约定

- Sub-Store 后端隐藏路径: `/sub-store-api-123456`
- Mihomo 控制接口密码: `123456`

## 初始化

1. 修改 `config/stack.env` 中的 `SUBSCRIPTION_URL` 为你的真实订阅地址。
2. 如果你使用 Sub-Store，按需修改 `sub-store-data/sub-store.json` 中的订阅源。
3. 如需修改本地代理监听，调整 `MIHOMO_MIXED_PORT`、`MIHOMO_ALLOW_LAN`、`MIHOMO_BIND_ADDRESS`。
4. 执行下面的启动命令。

## 常用命令

```bash
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" up -d
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" restart
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" logs -f sub-store
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" logs -f mihomo
```

## 发布建议

- 不要提交真实订阅链接、节点配置、Sub-Store token 和运行缓存。
- 使用 `config/*.local.*` 与 `sub-store-data/*.local.json` 保存你自己的本机敏感版本。
- 如果准备公开仓库，优先使用 SSH 远程地址，避免在仓库配置中留下带 token 的 URL。
