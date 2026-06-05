# 智能旅游助手快速开始

本文件用于本地开发的最短路径说明。更完整的项目说明请见 [README.md](./README.md)。

## 1. 本地运行

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn backend.main:application --host 0.0.0.0 --port 8000 --reload
```

启动后访问：

- `http://localhost:8000/`
- `http://localhost:8000/docs`
- `http://localhost:8000/health`

## 2. 环境变量

复制 `.env.example` 为 `.env` 后按需配置：

- `AMAP_API_KEY`
- `ALIYUN_BAILIAN_API_KEY`
- `PUBLIC_API_BASE_URL`
- `TRAVEL_CONTEXT_MCP_ENABLED=false`
- `TRAVEL_CONTEXT_MCP_TOKEN`
- `RUNTIME_OWNER_TRUST_HEADER=false`
- `TRIP_SYNC_ROUTE_ENABLED=false`

## 3. 验收检查

- 主页可访问
- `/health` 返回 `ok`
- `/docs` 正常加载
- 关键环境变量未泄露到前端 URL
