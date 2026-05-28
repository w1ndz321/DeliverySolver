# 部署说明

## 推荐结构

将 `submission/` 目录的**内容**作为一个新的 GitHub 仓库根目录。整个项目作为单一 Web Service 部署：

```text
/              项目介绍页
/demo.html     交互实验台
/api/*         数据分析、在线求解和离线学习接口
```

不要把 `frontend/` 单独部署成静态站点：交互页依赖同源 API，拆分后需要额外处理后端地址、CORS 和状态持久化。

## 本地启动

```bash
python3 backend/app.py
```

打开 <http://127.0.0.1:8080/>。

## Docker 部署

```bash
docker build -t autosolver-agent .
docker run --rm -p 8080:8080 \
  -v autosolver-state:/app/state \
  autosolver-agent
```

镜像内设置 `AUTOSOLVER_STATE_DIR=/app/state`。`autosolver-state` 卷会保留在线运行日志、
离线报告、`rule_memory.json` 和离线生成策略模块，因此服务重启后双闭环经验不会丢失。

## Render 上线方式

本目录提供了 `render.yaml`。它配置一个 Python Web Service 和 `1 GB` 持久磁盘，
并将 `AUTOSOLVER_STATE_DIR` 指向磁盘，以保存 Agent 学习证据和离线生成策略。

1. 新建 GitHub 仓库，将本目录内容推送为仓库根目录。
2. 在 Render Dashboard 选择 `New > Blueprint`，连接该仓库。
3. Render 读取 `render.yaml` 创建服务；部署完成后访问分配的 `*.onrender.com` 地址。
4. 打开 `/demo.html` 查看演示页；调用 `/api/autosolver/solve` 与
   `/api/autosolver/offline` 可演示新在线/离线闭环。

重要费用说明：配置文件采用 `starter` 实例和持久磁盘，因为 Render 持久磁盘仅可附加到付费服务。若只需要临时免费预览，可移除 `render.yaml` 中的 `disk` 配置并在控制台选择 Free Web Service；代价是服务重启或重新部署后运行日志、规则记忆和离线生成策略可能丢失。

当前服务已经满足 Render Web Service 运行要求：

- 服务监听 `0.0.0.0`。
- 端口默认读取平台提供的 `PORT` 环境变量。
- `/api/health` 可用于健康检查。

## 自定义域名作为项目介绍页

项目介绍页已经是 `/` 首页，无需额外开发静态官网。部署完成后：

1. 在 Render 服务的 `Settings > Custom Domains` 添加你的域名，例如 `autosolver.example.com`。
2. 按 Render 给出的目标值在域名服务商处添加 DNS 记录。
3. 回到 Render 点击验证域名。

Render 会为 `onrender.com` 地址和自定义域名自动签发并续期 TLS 证书，并将 HTTP 跳转到 HTTPS。

## 官方文档

- Render Web Service：<https://render.com/docs/web-services>
- Render Persistent Disks：<https://render.com/docs/disks>
- Render Blueprints：<https://render.com/docs/blueprint-spec>
- Render Custom Domains：<https://render.com/docs/custom-domains>
