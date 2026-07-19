# Tame Ink

Tame Ink 是面向个人本机使用的中文网络小说写作 Web 工具。当前版本已包含作品存储、版本事务、任务审批、SSE 事件恢复、受控 Agent 后端和三栏创作工作台。

## 当前功能

- 新建、打开和切换本地作品
- 导入整本小说并人工修正章节标题、编号和边界
- 通过 Agent 生成故事设定、全书大纲、分卷规划和章节候选稿
- 创建并审批番茄首测商业定位，记录真实曝光、打开、留存、追读和收入数据
- 章节连续性、风格与七维商业留存审查，低分章节必须填写人工覆盖理由
- 草稿自动保存、逐项差异审核和正式版本冲突处理
- 分类浏览、搜索、修正和撤销派生记忆
- 查看任务事件历史、取消任务和恢复中断状态
- 在工作台配置并测试 OpenAI-compatible 模型连接，可显式关闭 thinking 以兼容结构化 Agent

## Agent 与长篇上下文架构

章节创作由确定性工作流控制，按顺序调用 `ChapterPlanner`、`DraftWriter`、
`ContinuityAuditor`、`StyleCritic` 和 `RetentionAuditor`。每个阶段只运行一个受控
DeepAgent，必须先读取对应的 `skills/webnovel-*` Skill，再按严格 Schema 输出；不允许
Shell、任意网络请求、作品文件写入、隐式重试或绕过 Skill 的直接模型调用。

上下文由可信代码在每个阶段动态编译，而不是把整部百万字正文发送给模型。编译器只选择
作品配置、已确认商业定位、设定、大纲、当前卷、全书/分卷滚动摘要、最近三章摘要，以及
章节计划明确要求的 FTS 检索片段，并执行来源数和字符数预算。Agent 只能读取本次
`context_manifest` 白名单中的正式作品文件；模型选中的证据路径会转成可校验引用。

章节审批后才写入正式正文和不可变章节摘要，同时更新有界的全书与分卷滚动摘要。任务的
阶段、Skill 哈希、来源路径、检索词数量、上下文字符数、耗时和状态会写入 `run.json`，
并通过只读 `/api/projects/{project_id}/tasks/{task_id}/run` 接口显示在 Agent 面板；接口
不返回 API Key、完整 Prompt 或正文。模型商业评分只是编辑门禁，作品是否赚钱仍必须由
发布后的曝光、打开、留存、追读和收入数据验证。

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

开发环境必须同时运行 API、单进程任务 worker 和前端。可以在一个终端启动：

```bash
make dev
```

也可以分别在三个终端启动，便于单独查看日志：

```bash
make backend-dev
make backend-worker
make frontend-dev
```

前端地址为 `http://127.0.0.1:5173`，后端健康检查为
`http://127.0.0.1:8000/api/health`。Agent 请求由 API 返回 `202 + Task` 后进入持久队列，
没有运行 `backend-worker` 时任务会停留在 `pending`。worker 固定为单进程，模型调用不自动
重试、不切换模型。前端无法连接后端时会显示“后端离线”。

## 测试与检查

```bash
make test
make check
make evaluate
make e2e
make verify
```

真实模型评测和真实前后端联调不会进入默认验证，必须显式执行。两者都要求当前
workspace 中存在有效模型设置和 Keyring API Key，并要求提供当前供应商的 CNY 单价：

```bash
export TAME_INK_INPUT_PRICE_CNY_PER_1M_TOKENS="输入单价"
export TAME_INK_OUTPUT_PRICE_CNY_PER_1M_TOKENS="输出单价"
export TAME_INK_MAX_COST_CNY="20"

make evaluate-live
make e2e-live
```

live 报告和 token 用量记录位于 `output/live/`。也可以设置
`TAME_INK_USAGE_LOG`，让多个显式 live 命令共享同一份预算记录。`e2e-live` 使用独占端口
`8010`（API）和 `5180`（前端），端口被占用时直接失败。价格缺失、模型响应
缺少 token usage、Schema 错误、连接失败或预算超限都会立即失败，不会按字符数估算、
自动重试或切换模型。`e2e-live` 只把模型设置复制到临时 workspace，测试结束后删除临时
作品，不修改当前作品目录和全局 Keyring。报告包含模型、脱敏 Base URL、调用数、Agent
来源、token 和费用汇总；浏览器 console error、任务失败或商业门槛未通过都会使验收失败。

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

真实模型调用不会进入默认测试。商业留存评测复用固定案例和确定性断言，需要显式设置 `OPENAI_API_KEY`、`TAME_INK_MODEL` 和 `TAME_INK_BASE_URL` 后运行：

```bash
cd evaluations
pnpm commercial:live
```

DeepSeek 等在 thinking mode 下不支持强制 `tool_choice` 的模型，需要在“模型设置”中勾选“关闭模型推理模式”。评测通过只表示当前样本中的结构、判断和证据引用符合要求；作品能否产生真实收入仍必须通过发布后的运营数据验证。
