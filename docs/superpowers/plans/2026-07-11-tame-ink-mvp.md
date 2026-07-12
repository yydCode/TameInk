# Tame Ink MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个面向个人作者的本地 Web 应用，使用 Python `deepagents` 完成中文网络小说从立项、导入、大纲规划到长篇逐章生成、校验、审批和记忆更新。

**Architecture:** React + Vite 前端通过 HTTP/SSE 连接只监听本机的 FastAPI 后端。确定性领域服务管理审批、文件、SQLite 和 Git 事务，`deepagents` 只生成候选内容并通过受限工具读取项目上下文。

**Tech Stack:** React、TypeScript、Vite、Tiptap、FastAPI、Pydantic、Python `deepagents`、LangGraph、SQLite FTS5、Dulwich、keyring、pytest、Ruff、mypy、Vitest、Testing Library、Playwright。

---

## 1. 本次解决的问题

普通聊天式写作工具无法可靠维护百万字长篇的已确认事实，也缺少阶段审批、来源追踪、版本回滚和失败恢复。本计划通过确定性工作流包住 Agent，将模型输出限定为候选草稿，并建立可重建、可审计的本地作品存储。

## 2. 影响模块

- `backend/app/domain/`：作品、章节、任务、审批和错误语义。
- `backend/app/repositories/`：Markdown/YAML、SQLite、FTS5 和 Git。
- `backend/app/workflows/`：任务状态机、确认门禁和中断恢复。
- `backend/app/agents/`：主 Agent、子 Agent、Skills、受限 Tools 和输出 Schema。
- `backend/app/api/`：项目、导入、创作、审批、设置和 SSE 接口。
- `frontend/src/features/`：项目创建、导入、故事设计、章节工作台、记忆和运行记录。
- `frontend/src/components/editor/`：Tiptap、Markdown 往返和差异审核。
- `workspace/`：运行期作品目录；只提交示例和忽略规则，不提交用户内容。
- `tests/` 与前后端测试目录：确定性测试、Agent 合约测试、E2E 和真实模型评测。

## 3. 目标文件结构

```text
Tame-Ink/
├── README.md
├── Makefile
├── .gitignore
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── agents/
│   │   ├── domain/
│   │   ├── repositories/
│   │   ├── workflows/
│   │   └── infrastructure/
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── vite.config.ts
│   ├── playwright.config.ts
│   └── src/
│       ├── api/
│       ├── components/
│       └── features/
├── evaluations/
│   ├── fixtures/
│   └── README.md
└── workspace/
    └── .gitkeep
```

## 4. 实施阶段

### 阶段 1：建立可运行的前后端基线

**目标：** 得到一个可重复安装、可启动、可测试的本地 Web 骨架，只包含健康检查与应用外壳。

**主要文件：**

- Create: `.gitignore`
- Create: `README.md`
- Create: `Makefile`
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/api/health.py`
- Create: `backend/tests/api/test_health.py`
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/eslint.config.js`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/App.test.tsx`
- Create: `workspace/.gitkeep`

**步骤：**

- [ ] 先写 FastAPI 健康检查测试，断言 `GET /api/health` 返回固定 Schema 和版本字段。
- [ ] 运行 `cd backend && uv run pytest tests/api/test_health.py -v`，确认因入口不存在而失败。
- [ ] 初始化 `pyproject.toml`，加入 FastAPI、Uvicorn、pytest、Ruff 和 mypy，并实现最小健康检查。
- [ ] 再次运行健康检查测试，确认通过。
- [ ] 先写 React 外壳测试，断言应用标题和后端离线状态可见。
- [ ] 运行 `cd frontend && pnpm test --run`，确认因组件不存在而失败。
- [ ] 初始化 Vite + React + TypeScript，建立类型化 API 客户端和安静的应用外壳。
- [ ] 运行前后端 lint、类型检查、单元测试和生产构建。
- [ ] 使用中文提交：`工程：建立前后端运行基线`。

**验证：**

```bash
cd backend && uv run ruff check .
cd backend && uv run mypy app
cd backend && uv run pytest
cd frontend && pnpm lint
cd frontend && pnpm test --run
cd frontend && pnpm build
```

**通过标准：** 后端健康接口和前端应用外壳可独立启动；前端无法连接后端时显示明确状态，不伪造成功数据。

### 阶段 2：实现作品存储、路径边界和 Git 事务

**目标：** 在没有 Agent 的情况下完成项目创建、正式内容读写、版本确认、冲突检测和回滚。

**主要文件：**

- Create: `backend/app/domain/project.py`
- Create: `backend/app/domain/revision.py`
- Create: `backend/app/domain/errors.py`
- Create: `backend/app/repositories/workspace.py`
- Create: `backend/app/repositories/canon.py`
- Create: `backend/app/repositories/database.py`
- Create: `backend/app/repositories/revisions.py`
- Create: `backend/app/repositories/schema.sql`
- Create: `backend/tests/repositories/test_workspace.py`
- Create: `backend/tests/repositories/test_canon.py`
- Create: `backend/tests/repositories/test_revisions.py`
- Create: `backend/tests/repositories/test_database_rebuild.py`

**步骤：**

- [ ] 为 `../`、绝对路径、符号链接越界和非法项目 ID 写失败测试。
- [ ] 实现基于真实路径解析的 `WorkspaceRepository`，保证所有工具路径局限于当前项目。
- [ ] 为 `project.yaml`、Markdown 正文和独立 YAML 记忆写序列化往返测试。
- [ ] 实现 `CanonRepository`，限制受支持的文件类型和目录。
- [ ] 为 SQLite Schema、FTS5 索引和“删除数据库后从正式文件重建”写集成测试。
- [ ] 实现数据库初始化、迁移版本和可重建索引。
- [ ] 为版本 ID 冲突、原子确认、Git 提交失败恢复和历史回滚写集成测试。
- [ ] 使用 Dulwich 实现带恢复日志的 `RevisionRepository`；恢复未完成时拒绝后续写任务。
- [ ] 运行后端全量静态检查和测试。
- [ ] 使用中文提交：`功能：建立作品存储与版本事务`。

**验证：**

```bash
cd backend && uv run pytest tests/repositories -v
cd backend && uv run ruff check .
cd backend && uv run mypy app
```

**通过标准：** 未确认草稿不能进入 `canon/`；路径越界全部被拒绝；故障注入后文件和 Git 引用回到事务前版本；索引可以完全重建。

### 阶段 3：实现任务状态机、审批门禁和 SSE 恢复

**目标：** 建立不依赖模型的长任务基础设施，明确 `pending/running/awaiting_approval/completed/failed/cancelled/interrupted` 状态。

**主要文件：**

- Create: `backend/app/domain/task.py`
- Create: `backend/app/workflows/task_state.py`
- Create: `backend/app/workflows/task_service.py`
- Create: `backend/app/repositories/tasks.py`
- Create: `backend/app/api/tasks.py`
- Create: `backend/app/api/events.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/workflows/test_task_state.py`
- Create: `backend/tests/workflows/test_task_service.py`
- Create: `backend/tests/api/test_task_events.py`
- Create: `frontend/src/api/events.ts`
- Create: `frontend/src/features/runs/RunStatus.tsx`
- Create: `frontend/src/features/runs/RunStatus.test.tsx`

**步骤：**

- [ ] 先为所有合法和非法状态转换写参数化测试。
- [ ] 实现纯函数状态机，非法转换返回稳定领域错误。
- [ ] 为“同一项目仅一个写任务”、取消和审批门禁写服务测试。
- [ ] 实现任务持久化和项目级互斥。
- [ ] 为带单调序号的事件、`Last-Event-ID` 重连和断线不重跑写 API 测试。
- [ ] 实现 SSE 事件接口和持久化事件读取。
- [ ] 为进程启动时把遗留 `running` 标记为 `interrupted` 写恢复测试并实现恢复服务。
- [ ] 实现前端运行状态组件和断线重连客户端。
- [ ] 运行前后端相关测试并检查取消后没有正式写入。
- [ ] 使用中文提交：`功能：建立任务审批与事件恢复`。

**验证：**

```bash
cd backend && uv run pytest tests/workflows tests/api/test_task_events.py -v
cd frontend && pnpm test --run src/features/runs/RunStatus.test.tsx
```

**通过标准：** 非法状态无法进入数据库；断线只补发缺失事件；中断任务必须由用户明确恢复或终止。

### 阶段 4：接入 deepagents、模型配置和受限工具

**目标：** 通过假模型先验证 Agent 合约，再接入单一 OpenAI-compatible 模型，不允许 Agent 绕过 Repository。

**主要文件：**

- Create: `backend/app/infrastructure/settings.py`
- Create: `backend/app/infrastructure/secrets.py`
- Create: `backend/app/infrastructure/model.py`
- Create: `backend/app/agents/schemas.py`
- Create: `backend/app/agents/tools.py`
- Create: `backend/app/agents/context.py`
- Create: `backend/app/agents/subagents.py`
- Create: `backend/app/agents/orchestrator.py`
- Create: `backend/app/agents/backend.py`
- Create: `backend/app/repositories/drafts.py`
- Create: `backend/app/api/settings.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/agents/fake_model.py`
- Create: `backend/tests/agents/test_tools.py`
- Create: `backend/tests/agents/test_contracts.py`
- Create: `backend/tests/infrastructure/test_secrets.py`

**步骤：**

- [ ] 为 Base URL 校验、密钥不落盘和日志脱敏写测试。
- [ ] 使用 `keyring` 实现密钥保存，配置文件只保存非敏感模型信息。
- [ ] 定义所有 Agent 输出的 Pydantic Schema，并为非法字段、缺失引用和未知实体写失败测试。
- [ ] 为受限读写工具写越权测试，确认没有 Shell 和任意 HTTP 工具。
- [ ] 实现基于公开 `BackendProtocol` 的虚拟工作区：`/canon`、`/memory` 只读映射
  `CanonRepository`，`/drafts` 只写当前任务 `.tame-ink/drafts/<task-id>`；由受信上下文
  绑定 `project_id`/`task_id`，拒绝其他虚拟根、操作系统路径、`..` 和反斜线。
- [ ] 保留 `deepagents` 内置文件工具，通过 backend 强制边界与 permissions 角色权限双重
  限制；验证内置 `write_file`/`edit_file` 不能写 `/canon`、`/memory` 或操作系统路径，
  只能写当前 `/drafts`，且读、list、glob、grep 记录来源。
- [ ] 实现只能调用 Repository 的 Agent 工具；不提供 Shell、命令执行或任意 HTTP 工具。
- [ ] 为上下文清单和实际文件读取一致性写测试。
- [ ] 实现分层上下文构建器，记录每个送入模型的来源。
- [ ] 使用假模型测试主 Agent 与八个子 Agent 的输入边界、输出 Schema 和失败传播。
- [ ] 接入 Python `deepagents` 和 OpenAI-compatible 模型适配器，不配置自动模型切换。
- [ ] 运行 Agent 合约测试；真实 API 连接测试保持显式执行。
- [ ] 使用中文提交：`功能：接入受控创作智能体`。

**验证：**

```bash
cd backend && uv run pytest tests/agents tests/infrastructure -v
cd backend && uv run ruff check .
cd backend && uv run mypy app
```

**通过标准：** 假模型可走完候选内容流程；Schema 或来源错误立即失败；API Key 不出现在项目文件、数据库和测试日志中；Agent 只能写当前任务草稿，正式内容仍仅由用户审批后的确定性 Repository 事务写入。

### 阶段 5：实现新书、导入、记忆和逐章后端流程

**目标：** 在 API 层完成从新书或已有作品进入逐章确认的完整后端垂直流程。

**主要文件：**

- Create: `backend/app/workflows/new_book.py`
- Create: `backend/app/workflows/import_book.py`
- Create: `backend/app/workflows/outline.py`
- Create: `backend/app/workflows/chapter.py`
- Create: `backend/app/workflows/memory.py`
- Create: `backend/app/repositories/search.py`
- Create: `backend/app/api/projects.py`
- Create: `backend/app/api/imports.py`
- Create: `backend/app/api/creation.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/workflows/test_new_book.py`
- Create: `backend/tests/workflows/test_import_book.py`
- Create: `backend/tests/workflows/test_chapter.py`
- Create: `backend/tests/workflows/test_memory.py`
- Create: `backend/tests/repositories/test_search.py`
- Create: `backend/tests/performance/test_large_project.py`

**步骤：**

- [ ] 为 TXT/Markdown 编码检测、章节边界、空章节和无法识别边界写导入测试。
- [ ] 实现确定性章节解析；无法确认边界时返回具体位置，不猜测。
- [ ] 为新书的设定、大纲和分卷审批门禁写端到端后端测试。
- [ ] 实现新书、全书大纲和分卷工作流。
- [ ] 为“规划→初稿→双校验→局部修订→审批→正式提交”写假模型集成测试。
- [ ] 实现逐章工作流，校验问题必须带来源，修订只能引用已报告问题 ID。
- [ ] 为已确认章节的摘要、事实、事件、关系和伏笔提取写测试。
- [ ] 实现可撤销、带来源的派生记忆更新。
- [ ] 为固定上下文、结构化查询和 FTS5 原文检索写召回测试。
- [ ] 实现搜索服务并记录实际上下文清单。
- [ ] 运行后端全量测试和 1000 章合成数据性能测试。
- [ ] 使用中文提交：`功能：贯通长篇小说创作流程`。

**验证：**

```bash
cd backend && uv run pytest tests/workflows tests/repositories/test_search.py -v
cd backend && uv run pytest -m performance tests/performance/test_large_project.py -v
```

**通过标准：** 新书和导入作品都能到达章节审批；确认前无正式写入；所有派生记忆和校验问题带可解析来源；1000 章索引可重建。

### 阶段 6：实现工作台、Tiptap 和 AI 差异审核

**目标：** 提供可日常使用的三栏工作台，完成项目、导入、故事设计、章节、记忆、运行记录和设置界面。

**主要文件：**

- Create: `frontend/src/components/layout/AppShell.tsx`
- Create: `frontend/src/components/editor/NovelEditor.tsx`
- Create: `frontend/src/components/editor/markdown.ts`
- Create: `frontend/src/components/editor/changeset.ts`
- Create: `frontend/src/features/projects/`
- Create: `frontend/src/features/imports/`
- Create: `frontend/src/features/story/`
- Create: `frontend/src/features/chapters/`
- Create: `frontend/src/features/memory/`
- Create: `frontend/src/features/runs/`
- Create: `frontend/src/features/settings/`
- Create: `frontend/src/components/editor/NovelEditor.test.tsx`
- Create: `frontend/src/components/editor/markdown.test.ts`
- Create: `frontend/src/components/editor/changeset.test.ts`

**步骤：**

- [ ] 为支持的标题、段落、强调和分隔符写 Markdown 往返测试，明确拒绝未支持节点。
- [ ] 接入 Tiptap 和 `@tiptap/markdown`，保证保存后语义等价。
- [ ] 为 AI 增删范围、逐项接受、逐项拒绝和手工编辑后重新计算写测试。
- [ ] 使用 `prosemirror-changeset` 实现差异模型，不自研 diff 算法。
- [ ] 实现三栏 App Shell，并约束章节树、编辑区和 Agent 面板的稳定尺寸。
- [ ] 按项目创建、导入、故事设计、分卷、章节、记忆、运行记录和设置顺序实现页面。
- [ ] 为工作副本自动保存、刷新恢复和正式版本冲突写交互测试。
- [ ] 接入 HTTP/SSE API，所有失败展示稳定错误码对应的可行动信息。
- [ ] 在桌面与移动宽度检查文本溢出、遮挡和编辑器可用性；移动端只要求可审阅，不承诺完整创作体验。
- [ ] 运行前端测试、lint 和生产构建。
- [ ] 使用中文提交：`功能：完成小说创作工作台`。

**验证：**

```bash
cd frontend && pnpm lint
cd frontend && pnpm test --run
cd frontend && pnpm build
```

**通过标准：** Markdown 往返不丢失支持范围内的内容；AI 不直接改正文；刷新恢复同一草稿；冲突时停止保存并展示比较入口。

### 阶段 7：完成 E2E、真实模型评测与交付验证

**目标：** 用浏览器和可审计评测证明主流程、安全边界和长篇一致性指标达到规格要求。

**主要文件：**

- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/new-book.spec.ts`
- Create: `frontend/e2e/import-book.spec.ts`
- Create: `frontend/e2e/chapter-approval.spec.ts`
- Create: `frontend/e2e/recovery.spec.ts`
- Modify: `backend/tests/performance/test_large_project.py`
- Create: `evaluations/fixtures/continuity_cases.yaml`
- Create: `evaluations/run.py`
- Create: `evaluations/README.md`
- Modify: `README.md`
- Modify: `Makefile`

**步骤：**

- [ ] 用假模型编写新书、导入、章节确认、取消、中断恢复和外部冲突 E2E。
- [ ] 运行 Playwright，修复所有交互、控制台和响应式问题。
- [ ] 创建包含人物、时间线、能力、伏笔和视角错误的中文评测集，并为评分器写确定性测试。
- [ ] 实现显式真实模型评测命令，记录模型、参数、token、耗时、召回和误报来源。
- [ ] 构造 1000 章、约 200 万字合成项目，测量导入、索引重建和章节浏览。
- [ ] 验证 API 只监听本机、CORS 限制、路径越界、日志脱敏和密钥存储。
- [ ] 更新 README，写明安装、运行、测试、数据位置、备份和故障恢复命令。
- [ ] 运行完整验证矩阵并保存结果摘要。
- [ ] 使用中文提交：`测试：完成首版端到端验收`。

**验证：**

```bash
make verify
cd frontend && pnpm playwright test
cd backend && uv run pytest -m performance
cd backend && uv run python ../evaluations/run.py --fixture-only
```

真实模型评测仅在用户明确提供模型配置后运行：

```bash
cd backend && uv run python ../evaluations/run.py --live
```

**通过标准：** 默认验证不产生模型费用；E2E 无控制台错误；未经确认写入为 0；所有引用可追溯；按具体模型记录的矛盾召回率不低于 90%。

## 5. 最容易出错的地方

1. **正式文件与 Git 引用不一致**：必须先做故障注入测试，再实现带恢复日志的事务，不能只在正常路径提交。
2. **Agent 越权读取**：提示词不是边界，所有路径必须经过 Repository 的真实路径校验。
3. **记忆污染**：只能从已确认正文提取派生记忆，每条记忆必须带来源并可撤销。
4. **Markdown 往返损坏**：先限定节点集合并做性质测试，不能默认任意富文本都可无损转换。
5. **SSE 重连导致任务重跑**：事件订阅与任务执行必须分离，重连只读取持久化事件。
6. **模型输出被宽松解析掩盖**：只接受明确 Schema；解析失败终止任务，不用正则猜测字段。
7. **百万字上下文失控**：测试必须断言实际读取文件清单，禁止把全文或整个目录交给模型。

## 6. 实施门禁

- 只有当前阶段全部验证通过，才进入下一阶段。
- 每阶段只提交与该阶段相关的文件，提交信息使用中文。
- 默认测试不调用真实模型、不产生费用、不修改用户作品。
- 遇到依赖能力与调研结论不一致时停止实现，先更新设计并由用户确认。
- 不增加自动降级、模型切换、静默重试或宽松解析来掩盖主流程错误。
