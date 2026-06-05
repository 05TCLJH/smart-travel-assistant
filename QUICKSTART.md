# 智能旅游助手快速启动

## 本地开发

```bash
cd d:\python_work\PycharmProjects\项目\ai应用开发\智能旅游助手
python -m uvicorn backend.main:application --host 0.0.0.0 --port 8000 --reload
```

启动后访问：

- `http://localhost:8000/`
- `http://localhost:8000/docs`
- `http://localhost:8000/health`

## 单个 Hugging Face Space 部署

当前项目已经按 `单实例公开部署` 收口，适合直接部署为 Docker Space。

部署步骤：

1. 先在本地执行：
   - `docker build -t smart-travel-assistant:hf .`
2. 在 Hugging Face 新建 `Docker Space`
3. 推送当前仓库到 Space
4. 在 Space Variables 中按需配置：
   - `AMAP_API_KEY`
   - `ALIYUN_BAILIAN_API_KEY`
   - `TRAVEL_CONTEXT_MCP_ENABLED=false`
   - `RUNTIME_OWNER_TRUST_HEADER=false`
   - `TRIP_SYNC_ROUTE_ENABLED=false`
5. 等待构建完成后直接访问公网地址

## 当前部署特性

- 用户之间通过匿名 cookie 隔离运行时任务
- 行程任务、SSE 进度、结果查询走统一 runtime store
- 高德 Key 不出现在前端 URL
- Travel Context MCP 默认关闭
- 服务重启后临时任务和临时结果丢失，属于预期行为

## 不需要额外准备的东西

- 不需要单独数据库管理员
- 不需要持久化用户临时任务
- 不需要 Redis
- 不需要多节点共享状态

如果后续你要从单 Space 升级到多副本部署，再补共享状态层即可；当前阶段不用过度设计。

## 部署前最后检查

- `README.md` 顶部已经带 Hugging Face Space 的 Docker 元数据
- `Dockerfile` 已默认监听 `7860`
- `TRAVEL_CONTEXT_MCP_ENABLED` 默认应保持 `false`
- `RUNTIME_OWNER_TRUST_HEADER` 默认应保持 `false`
- `TRIP_SYNC_ROUTE_ENABLED` 默认应保持 `false`
