---
title: Smart Travel Assistant
emoji: "🧭"
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# 智能旅游助手

一个基于 `FastAPI + 原生 JavaScript` 的单页旅游规划应用，当前已经按 `单个公开实例` 的部署方式做过架构收口，适合直接部署到 `Hugging Face Docker Space`。

## 当前部署定位

- 面向 `单机 / 单实例 / 公共网址`
- 用户之间通过 `匿名运行时 cookie` 做隔离
- 用户自带 Key 只保留在当前浏览器会话中，不写入后端长期配置
- 后端只保存 `短时运行状态`，用于任务排队、SSE 进度、结果查询、静态地图票据
- 服务重启后，这些临时状态丢失是 `预期行为`，不是故障

## 这次架构整改后的实际效果

- 行程任务不再依赖某个请求进程内存，`task_id + SSE + 结果轮询` 改为统一运行时状态存储
- 任务即使经过正常的 worker 切换，也不会出现“创建在 A，查询不到”的直接 bug
- `Travel Context MCP` 默认关闭；只有显式开启并提供令牌时才可访问
- Travel Context 访问增加了运行时 owner 隔离，不能再裸读别人的 session
- 高德 Key 不再拼到前端 URL 上，避免浏览器地址栏、代理日志、分享链接泄露
- 静态地图链路改成 `短时 ticket`，继续兼容 BYOK，但不暴露真实 Key

## 当前架构

- `LangGraph` 负责多 Agent 编排
- `高德官方 MCP` 负责地图、天气、POI、路线等外部事实能力
- `内部 Travel Context MCP` 仅在显式开启时提供只读上下文能力
- `SQLite runtime store` 负责单实例下的临时任务状态、进度和运行时隔离数据

## 关键目录

```text
backend/
  core/                环境配置、路径、运行时 owner
  runtime/             运行时状态存储、任务队列、后台 worker
  routers/             FastAPI 路由与内部 MCP 入口
  services/            业务入口服务
frontend/
  index.html
  js/
  css/
  assets/
tests/
  test_runtime_deploy_safety.py
```

## 环境变量

参考 `.env.example`。

核心变量：

- `AMAP_API_KEY=`：可选，后端默认高德 Key
- `ALIYUN_BAILIAN_API_KEY=`：可选，视觉和模型能力使用
- `PUBLIC_API_BASE_URL=`：前后端分域部署时使用；同域部署可留空
- `TRAVEL_CONTEXT_MCP_ENABLED=false`：默认关闭内部 MCP
- `TRAVEL_CONTEXT_MCP_TOKEN=`：只有开启 MCP 时才需要配置
- `RUNTIME_OWNER_TRUST_HEADER=false`：默认不信任请求头 owner，避免伪造
- `TRIP_SYNC_ROUTE_ENABLED=false`：默认关闭同步长请求入口，避免公网部署时被代理超时拖垮体验
- `EPHEMERAL_RUNTIME_ROOT=`：可选；不填时，Hugging Face Space 默认写入系统临时目录

说明：

- 未配置 `AMAP_MCP_SERVER_URL` 时，系统会根据 `AMAP_API_KEY` 自动拼接高德官方 MCP 地址
- 若出现 `USERKEY_PLAT_NOMATCH`，请改用高德开放平台 `Web 服务` 类型 Key
- 未配置后端 Key 时，系统仍可运行，但部分实时能力会退回 demo/fallback 数据

## 本地启动

```bash
python -m uvicorn backend.main:application --host 0.0.0.0 --port 8000 --reload
```

访问：

- 前端主页：`http://localhost:8000/`
- API 文档：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/health`

## Hugging Face Space 部署

1. 在本地确认 Docker 镜像可构建：
   - `docker build -t smart-travel-assistant:hf .`
2. 在 Hugging Face 新建 `Docker Space`
3. 把当前仓库推到该 Space 对应的 Git 仓库
4. 在 Space `Settings -> Variables and secrets` 中按需配置：
   - `AMAP_API_KEY`
   - `ALIYUN_BAILIAN_API_KEY`
   - `TRAVEL_CONTEXT_MCP_ENABLED=false`
   - `RUNTIME_OWNER_TRUST_HEADER=false`
   - `TRIP_SYNC_ROUTE_ENABLED=false`
5. 不需要持久卷；当前设计就是短时运行态
6. 等待平台自动构建完成后，直接访问 Space 公网地址

部署预期：

- 浏览器会拿到匿名隔离 cookie
- 每个用户只能读取自己当前运行期的任务结果
- 服务重启后，未完成任务和临时结果会消失
- 不会在页面 URL、日志友好的链接参数中暴露用户高德 Key

## 不建议的部署方式

- 不建议把当前版本直接横向扩成多副本部署
- 不建议把 `Travel Context MCP` 当成公网裸接口暴露
- 不建议恢复“前端 URL 直接拼接 Key”的静态地图方案

如果后续要升级为多实例部署，再把当前的 runtime store 从单机 SQLite 换成共享存储即可；但对单个 Hugging Face Space 来说，现在这套已经够用。

## 本地 Docker 自检

构建：

```bash
docker build -t smart-travel-assistant:hf .
```

运行：

```bash
docker run --rm -p 7860:7860 \
  -e TRAVEL_CONTEXT_MCP_ENABLED=false \
  -e RUNTIME_OWNER_TRUST_HEADER=false \
  -e TRIP_SYNC_ROUTE_ENABLED=false \
  smart-travel-assistant:hf
```

检查：

- `http://localhost:7860/`
- `http://localhost:7860/health`
- `http://localhost:7860/docs`
