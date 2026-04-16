# Mihomo Stack

## Web 入口

- Mihomo 面板: `http://<你的主机IP>:3001`
- Sub-Store: `http://<你的主机IP>:3002`

## 当前约定

- Sub-Store 后端隐藏路径: `/sub-store-api-123456`
- Mihomo 控制接口密码: `123456`

## 常用命令

```bash
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" up -d
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" restart
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" logs -f sub-store
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" logs -f mihomo
```
