# Mihomo Proxy Stack

一个用于个人服务器部署的代理面板项目，集成了：

- `mihomo`：代理核心
- `MetaCubeXD`：Web 管理面板
- `Sub-Store`：订阅管理
- `mihomo-sync`：自动同步订阅并热重载配置

这个仓库提供的是可公开提交的安全默认配置。你需要把自己的订阅地址替换进去，启动后才能正常使用代理节点。

## 功能

- 浏览器访问 Mihomo 面板
- 浏览器访问 Sub-Store 管理订阅
- 自动拉取订阅并更新 `mihomo` 配置
- 默认开启本地混合代理端口 `7890`

## 目录说明

- `config/`：Mihomo 配置、参数模板、面板资源
- `sub-store-data/`：Sub-Store 初始化数据
- `scripts/`：同步与辅助脚本
- `portal/`：入口页静态文件
- `nginx/`：Nginx 配置

## 使用前准备

你至少需要修改下面两个文件中的占位内容：

1. [config/stack.env](/home/dajingling/mihomo/config/stack.env)
2. [sub-store-data/sub-store.json](/home/dajingling/mihomo/sub-store-data/sub-store.json)

重点是把里面的示例订阅地址：

```text
https://example.com/your-subscription?clash=1
```

替换成你自己的真实订阅地址。

## 启动

```bash
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" up -d
```

## 访问地址

- Mihomo 面板：`http://<你的主机IP>:3001`
- Sub-Store：`http://<你的主机IP>:3002`

## 默认配置

- Mihomo 控制端口：`19090`
- Mihomo 控制密码：`123456`
- 本地混合代理端口：`7890`

如果你需要修改代理监听端口，可以编辑 [config/stack.env](/home/dajingling/mihomo/config/stack.env) 中这些参数：

- `MIHOMO_MIXED_PORT`
- `MIHOMO_ALLOW_LAN`
- `MIHOMO_BIND_ADDRESS`

## 常用命令

```bash
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" restart
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" logs -f mihomo
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" logs -f sub-store
```

## 说明

- 仓库里的配置文件是脱敏后的安全默认值，不包含你的真实节点信息。
- 你本机的敏感备份文件不会被提交。
