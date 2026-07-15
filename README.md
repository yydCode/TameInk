# Tame Ink

Tame Ink 是面向个人本机使用的中文网络小说写作 Web 工具。当前版本已包含作品存储、版本事务、任务审批、SSE 事件恢复、受控 Agent 后端和三栏创作工作台。

## 当前功能

- 新建、打开和切换本地作品
- 导入整本小说并人工修正章节标题、编号和边界
- 通过 Agent 生成故事设定、全书大纲、分卷规划和章节候选稿
- 章节连续性与风格审查、修订及用户审批门禁
- 草稿自动保存、逐项差异审核和正式版本冲突处理
- 分类浏览、搜索、修正和撤销派生记忆
- 查看任务事件历史、取消任务和恢复中断状态
- 在工作台配置并测试 OpenAI-compatible 模型连接

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
make evaluate
make e2e
make verify
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

## 数据与恢复

运行期作品数据位于 `TAME_INK_WORKSPACE` 指定目录；未设置时使用当前目录下的 `.tame-ink-workspace`。正式内容位于项目 `canon/`，未确认内容位于 `.tame-ink/drafts/`，SQLite 索引可从正式文件重建。API 默认只监听 `127.0.0.1`。

浏览器会保存当前项目、任务和草稿路径，刷新后通过后端草稿接口恢复工作副本。正式内容必须通过工作台中的审批按钮确认，确认时才创建版本提交。

服务重启时，未完成任务会标记为中断；工作台可将中断任务恢复为运行状态。Agent 生成需要先在“模型设置”中保存有效配置和 API Key，配置或上游调用失败时不会生成替代内容。

## 真实模型评测

真实模型调用不会进入默认测试。需要显式设置 `OPENAI_API_KEY`、`TAME_INK_MODEL` 和 `TAME_INK_BASE_URL` 后运行：

```bash
cd backend && uv run python ../evaluations/run.py --live
```
