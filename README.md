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

## 启动

```bash
docker compose -f "/home/dajingling/mihomo/docker-compose.yml" up -d
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

- 真实订阅地址、节点数据和缓存都会保留在本地
- 仓库内静态基线配置是 `config/base.yaml`
- 运行期生成的订阅配置是 `config/generated.yaml`，该文件不会纳入版本控制
- 如果浏览器没有立刻看到最新界面，强刷 `3001` 页面即可
