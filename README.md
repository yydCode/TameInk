# Tame Ink

Tame Ink 是面向个人本机使用的中文网络小说写作 Web 工具。本阶段提供 FastAPI 健康检查和 React 应用外壳，不包含写作领域功能。

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- pnpm 10.33.2

## 安装

```bash
make install
```

## 运行

分别在两个终端启动后端和前端：

```bash
make backend-dev
make frontend-dev
```

前端地址为 `http://127.0.0.1:5173`，后端健康检查为 `http://127.0.0.1:8000/api/health`。前端无法连接后端时会显示“后端离线”。

## 测试与检查

```bash
make test
make check
```

也可以分别运行：

```bash
cd backend && uv run pytest
cd frontend && pnpm test --run
cd backend && uv run ruff check .
cd backend && uv run mypy app
cd frontend && pnpm lint
cd frontend && pnpm build
```
