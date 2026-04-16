# Mihomo Stack

## 仓库约定

- `config/config.yaml`：可提交的安全启动配置，默认可启动，但不会包含你的真实节点。
- `config/stack.env`：可提交的示例运行参数，发布前需要替换 `SUBSCRIPTION_URL` 等占位值。
- `sub-store-data/sub-store.json`：可提交的脱敏初始化数据。
- `sub-store-data/root.json`：可提交的空缓存文件。
- `config/*.local.*`、`sub-store-data/*.local.json`：本机敏感备份，不会提交。

## Web 入口

- Mihomo 面板: `http://<你的主机IP>:3001`
- Sub-Store: `http://<你的主机IP>:3002`

## 当前约定

- Sub-Store 后端隐藏路径: `/sub-store-api-123456`
- Mihomo 控制接口密码: `123456`

## 初始化

1. 修改 `config/stack.env` 中的 `SUBSCRIPTION_URL` 为你的真实订阅地址。
2. 如果你使用 Sub-Store，按需修改 `sub-store-data/sub-store.json` 中的订阅源。
3. 执行下面的启动命令。

## 常用命令

```bash
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" up -d
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" restart
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" logs -f sub-store
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" logs -f mihomo
```
