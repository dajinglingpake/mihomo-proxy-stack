# Mihomo Proxy Stack

一个基于 `mihomo + MetaCubeXD + Sub-Store` 的单机代理管理项目。

当前交互已经收敛为单端口入口：

- `3001`：主入口，MetaCubeXD 面板
- 左侧导航新增 `订阅` 入口
- 订阅导入、更新、切换、删除都在这个入口里完成

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

## 启动

```bash
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" up -d
```

## 本地运行时文件

下面这些都属于本地运行时数据，不应提交到仓库：

- `config/stack.local.env`
- `config/config.local.yaml`
- `sub-store-data/*.json`

如果你要给脚本提供本地默认订阅地址，可以新建：

```bash
touch "/home/dajingling/mihomo/config/stack.local.env"
```

然后写入：

```bash
SUBSCRIPTION_URL="https://你的真实订阅地址"
```

## 默认端口

- 面板端口：`3001`
- Sub-Store 原始端口：`3002`
- Mihomo 控制端口：`19090`
- Mihomo 混合代理端口：`7890`

## 常用命令

```bash
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" up -d
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" restart
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" logs -f mihomo
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" logs -f mihomo-sync
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" logs -f sub-store
```

## 说明

- 仓库只保留可公开提交的代码和安全默认配置
- 真实订阅、节点、缓存、流量数据都应留在本地运行时文件中
- 如果浏览器没有立刻看到最新界面，强刷 `3001` 页面即可
