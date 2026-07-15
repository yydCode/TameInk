# Tame Ink 网络小说写作工具设计规格

日期：2026-07-11

状态：已确认

## 1. 目标

Tame Ink 是面向个人作者的本地 Web 应用，用于中文网络小说从创意立项到长篇稳定续写的完整创作流程。

首版的核心价值是长篇一致性与可控性，而不是单纯提高文字生成速度。系统应支持单部约 200 万字、1000 章的作品，通过分层记忆、结构化事实、按需检索、独立校验和人工确认，降低人物设定冲突、时间线错误、能力体系越界、伏笔遗漏和剧情漂移。

## 2. 已确认的产品决策

- 使用方式：个人本地工具，不包含账号、团队、支付或云同步。
- 核心范围：中文网络小说，多题材通用。
- 创作范围：从题材创意、书名简介、设定、大纲和分卷规划，到逐章规划、生成、校验与续写。
- 人工控制：大纲、分卷规划和每章正文必须由用户确认；细节规划与校验由 Agent 自主完成。
- 运行形态：本地 Web 应用，浏览器连接只监听本机的后端服务。
- 模型接入：单一 OpenAI-compatible 接口，由用户配置 API Key、Base URL 和模型名。
- 数据存储：Markdown/YAML 保存正式内容，SQLite 保存状态、索引和运行记录。
- 导入范围：支持 TXT 和 Markdown，先校对章节边界，再提取设定与记忆。
- 编辑体验：所见即所得，底层保存为 Markdown；AI 修改必须经过差异审核。
- 质量优先级：一致性与可控性优先于速度和调用成本。

## 3. 非目标

首版不包含以下能力：

- 模型训练或微调
- 云同步和多用户协作
- 移动端或桌面安装包
- 自动发布到小说平台
- 市场数据采集和热点分析
- DOCX、EPUB 等复杂格式导入
- 向量数据库或隐式 Embedding 依赖
- 多模型自动切换或失败降级
- Agent Shell 权限和任意网络访问

## 4. 技术方案

采用 React + FastAPI + Python `deepagents` 的前后端分离方案。

```text
Tame-Ink/
├── frontend/                 # React + Vite
│   └── src/
│       ├── features/         # 项目、设定、大纲、章节、审核
│       ├── components/       # 通用 UI 与编辑器
│       └── api/              # FastAPI 客户端与 SSE 事件流
├── backend/                  # FastAPI + deepagents
│   ├── app/
│   │   ├── api/              # HTTP/SSE 接口
│   │   ├── domain/           # 领域模型与确定性规则
│   │   ├── workflows/        # 阶段推进和人工确认门禁
│   │   ├── agents/           # Agent、子 Agent、Skills、Tools
│   │   ├── repositories/     # 文件、SQLite 和 Git 访问
│   │   └── infrastructure/   # 模型、日志、配置、检索
│   └── tests/
└── workspace/                # 本地作品数据，不进入源码仓库
    └── projects/<project-id>/
```

### 4.1 职责边界

- 前端只负责提交任务、显示进度、编辑草稿和审批结果，不执行 Agent。
- FastAPI 管理任务启动、取消、恢复、审批和错误返回。
- `deepagents` 负责推理、任务规划、子 Agent 调度和候选内容生成。
- 领域工作流负责状态转换、审批门禁、版本检查和正式内容写入。
- Repository 是唯一持久化入口，Agent 不能直接访问任意本地路径。
- Agent 只能写草稿。用户确认后，确定性服务才可写入正式内容并创建版本。

`deepagents` 的内置文件工具保留，但它们只能看到由自定义 `BackendProtocol`
提供的虚拟工作区：`/canon` 和 `/memory` 只读映射到 `CanonRepository`，
`/drafts` 只映射到当前任务的 `.tame-ink/drafts/<task-id>`。`project_id` 和
`task_id` 由受信运行上下文绑定，模型参数不能切换项目或任务。任何其他虚拟根、
操作系统路径、`..`、反斜线和符号链接逃逸都必须拒绝；Agent 不提供 Shell、命令执行
或任意 HTTP 工具。

文件访问采用双重限制：自定义 backend 强制虚拟路径边界，工具 permissions 再按角色
限制读写能力。内置 `write_file` 和 `edit_file` 对 `/canon`、`/memory` 始终拒绝，只有
当前任务的 `/drafts` 可写；读取、列举、glob 和 grep 仍保留可审计来源。草稿写入不改变
正式事实，正式内容仍必须经用户审批后由确定性 Repository 事务原子写入并创建版本。

Tame Ink 的 OpenAI-compatible 模型通过 LangChain 公开的 provider tracking hook 使用独立
provider 标识 `tame_ink_openai`，`deepagents` harness profile 只注册到该隔离 provider，
不污染普通 `openai` 模型。产品进程内所有 Tame Ink 模型共享同一安全 profile；这是有意的
最小权限策略，模型 id（包括带多个冒号的 fine-tuned opaque id）不会被改写或用于 registry key。

首版定位为本地单用户应用：允许显式配置 loopback 模型端点，并依赖原子替换、文件锁和路径
校验降低并发风险。私网/DNS rebinding、本机恶意进程在校验后替换文件的 TOCTOU 属于已知
残余风险；多用户或不可信主机部署前必须增加网络出口隔离、端点解析固定和操作系统级目录
权限/句柄约束。

核心原则：模型输出永远是候选内容，用户确认过的文件才是作品事实。

## 5. Agent 设计

主编排 Agent 只拆解任务、选择子 Agent 和汇总结果，不直接修改正式作品。

专业子 Agent：

- `StoryArchitect`：题材定位、核心卖点、主线冲突、人物与世界观。
- `OutlineArchitect`：全书大纲、剧情阶段、伏笔布局和分卷目标。
- `ChapterPlanner`：依据当前卷目标和前文状态生成章节计划。
- `DraftWriter`：依据已确认事实与章节计划生成正文。
- `ContinuityAuditor`：检查人物、时间线、能力体系、伏笔和因果冲突。
- `StyleCritic`：检查视角、节奏、重复表达、可读性和章节钩子。
- `MemoryCurator`：从已确认章节提取摘要、事实变化、关系变化和伏笔状态。
- `ImportAnalyst`：分析导入作品并提取候选设定与章节结构。

### 5.1 新书流程

```text
创意输入
→ 核心概念与设定草案
→ 全书大纲
→ 用户确认
→ 分卷规划
→ 用户确认
→ 进入逐章创作
```

### 5.2 逐章流程

```text
读取已确认上下文
→ 章节规划
→ 正文初稿
→ 一致性校验与风格校验
→ 针对明确问题局部修订
→ 展示正文与校验报告
→ 用户编辑并确认
→ 写入正式章节
→ 更新分层摘要和结构化记忆
```

### 5.3 Agent 约束

- 校验问题必须带具体文件、章节或记忆来源。
- 修订只处理已识别问题，不借润色重写整章。
- 正文确认前不得提取正式记忆。
- 记忆保留来源章节和原文位置，并支持撤销和修正。
- 导入章节先由确定性规则拆分，用户校对后才运行 Agent 分析。
- Schema 不合法、来源不存在或模型调用失败时立即终止当前任务。
- 每个子 Agent 只接收当前任务所需上下文，不能读取整部作品。

## 6. 作品数据模型

每部作品是可独立移动和备份的目录：

```text
workspace/projects/<project-id>/
├── project.yaml
├── canon/
│   ├── premise.md
│   ├── outline.md
│   ├── volumes/
│   ├── characters/
│   ├── world/
│   └── chapters/
├── memory/
│   ├── summaries/
│   │   ├── book.md
│   │   ├── volumes/
│   │   └── chapters/
│   ├── facts/
│   ├── events/
│   ├── relationships/
│   └── foreshadowing/
├── imports/
│   └── originals/
└── .tame-ink/
    ├── state.db
    ├── drafts/
    └── runs/
```

- `canon/` 保存用户确认过的大纲、设定与正文。
- `memory/` 保存从正式内容派生的可追溯记忆。
- 每条事实、事件、关系和伏笔使用独立 YAML 文件，包含稳定 ID、状态、来源章节和原文引用。
- `.tame-ink/state.db` 保存任务、审批、索引、事件和运行记录，不是正文来源。
- `.tame-ink/drafts/` 保存未确认内容，不参与正式上下文。
- `imports/originals/` 保存只读导入原件。

## 7. 分层上下文与检索

首版采用结构化记忆、分层摘要和 SQLite FTS5，不使用向量数据库。

1. 固定加载项目规则、当前卷目标、最近章节摘要、当前人物状态和未解决伏笔。
2. 根据章节计划涉及的人物、地点、能力和线索查询结构化记忆。
3. 使用 FTS5 检索相关原文片段，并携带来源文件和段落位置。

SQLite 中的索引是派生数据，必须能够从 Markdown/YAML 重建。检索日志记录实际送入模型的来源，便于审计上下文选择。

## 8. 版本历史

使用 Git 数据模型保存正式内容历史，通过 Python `Dulwich` 操作，不依赖系统安装 Git，也不自研 diff 或回滚算法。

- 每次确认大纲、分卷或章节时产生一个原子提交。
- 提交信息使用中文，例如 `确认：第 12 章《雨夜来客》`。
- AI 草稿不进入 Git 历史。
- 用户可以查看差异、恢复历史版本和导出完整作品目录。
- 作品数据仓库与应用源码仓库相互独立。

## 9. 前端体验

章节工作台采用三栏布局：

```text
左侧：作品目录       中间：正文/大纲编辑器       右侧：上下文与 Agent
章节树              当前文档                    当前任务进度
人物与设定          AI 修改差异                  引用的记忆来源
伏笔与时间线        接受/拒绝修改                校验问题与证据
```

首版视图：

- 项目创建
- 作品导入
- 故事设计
- 分卷规划
- 章节工作台
- 记忆中心
- 运行记录
- 模型设置

### 9.1 编辑器

复用以下 MIT 开源组件：

- Tiptap 3
- `@tiptap/markdown`
- `prosemirror-changeset`

不使用 Tiptap 付费 AI、协作或版本历史服务。

- 打开正式内容后创建工作副本，自动保存到草稿区。
- AI 只提交建议，用户逐项接受、拒绝或手工修改。
- “确认版本”执行校验、原子写入和 Git 提交，再触发记忆更新。
- 浏览器刷新或后端重启后恢复同一工作副本。
- 检测到外部修改时停止保存，要求用户重新加载或比较差异，不自动合并。

## 10. 任务状态与事件

任务状态机：

```text
pending → running → awaiting_approval → completed
                  ↘ failed
                  ↘ cancelled
                  ↘ interrupted
```

- 每个项目同一时间只允许一个会修改内容的 Agent 任务。
- 前端通过 SSE 接收带单调序号的持久化事件。
- 断线重连从最后确认序号继续，不重新执行任务。
- 后端重启后，未完成任务标记为 `interrupted`，由用户选择恢复或终止。
- 重试创建新的运行记录并关联原失败任务。

## 11. 错误处理

稳定错误码至少包括：

- `MODEL_AUTH_FAILED`
- `MODEL_RATE_LIMITED`
- `MODEL_RESPONSE_INVALID`
- `SCHEMA_VALIDATION_FAILED`
- `CONTEXT_SOURCE_MISSING`
- `WORKSPACE_PATH_VIOLATION`
- `CANON_VERSION_CONFLICT`
- `STORAGE_WRITE_FAILED`
- `TASK_INTERRUPTED`

处理规则：

- 不自动切换模型、降低校验标准或用旧结果替代新结果。
- 非法模型输出保留原始响应和 Schema 错误，但不形成有效草稿。
- 正式写入由 Repository 作为一个带恢复日志的事务执行：校验当前版本、构造新 Git 对象、以 compare-and-swap 更新版本引用，再原子替换工作文件。任一步失败都根据恢复日志回到事务开始前的引用和文件版本，并将任务标记为 `STORAGE_WRITE_FAILED`；恢复未完成前禁止后续写任务。
- API 返回可行动信息，运行记录保存技术细节，密钥和正文不进入普通日志。

## 12. 本地安全

- FastAPI 默认只监听 `127.0.0.1`。
- API 只接受固定本地域名来源。
- API Key 使用 Python `keyring` 写入系统钥匙串，不进入文件、数据库或日志。
- Agent 不获得 Shell 工具，也不能访问任意网络。
- 文件工具把项目 ID 映射到固定根目录，并在解析真实路径后检查越界、符号链接和绝对路径。
- 唯一外部网络目标是用户明确配置的模型 Base URL。
- TXT/Markdown 导入文件只作为数据读取，不执行嵌入内容。

## 13. 测试策略

### 13.1 领域单元测试

- 工作流状态机和审批门禁
- 路径越界与符号链接检查
- Schema 和 Markdown/YAML 序列化
- 原子写入与版本冲突
- 分层上下文选择和来源引用

### 13.2 Agent 合约测试

- 使用可预测的假模型响应，不调用真实 API。
- 验证子 Agent 输入范围、输出 Schema 和工具权限。
- 验证失败时不会推进状态或写入正式内容。

### 13.3 后端集成测试

- 在临时目录中运行 SQLite、FTS5 和 Dulwich。
- 覆盖新建、导入、生成、审批、回滚和索引重建。
- 模拟进程中断、SSE 重连和外部文件冲突。

### 13.4 前端和端到端测试

- Vitest + Testing Library 验证组件状态和交互。
- Playwright 验证从新建作品到确认章节的完整流程。
- 覆盖差异接受/拒绝、刷新恢复和错误展示。

### 13.5 真实模型评测

- 使用小型中文网文评测集覆盖人物矛盾、时间线冲突、能力越界、伏笔遗漏和视角漂移。
- 显式运行真实模型评测，记录模型、参数、token、耗时和结果。
- 默认验证命令不调用付费模型。

## 14. 验收标准

- 未经确认的内容写入 `canon/` 的次数为 0。
- 每条 Agent 记忆和校验问题都能定位到来源文件。
- 1000 章、约 200 万字项目可完成确定性导入、索引重建和章节浏览。
- Agent 只读取任务清单声明的上下文。
- 后端中断后草稿、事件和审批状态可恢复。
- 外部文件冲突不会覆盖任何版本。
- 预置矛盾评测集召回率不低于 90%，误报必须可追溯；评测结果按模型分别记录。
- 前后端最小验证全部通过后才允许提交代码。

计划验证命令：

```bash
cd backend && uv run ruff check .
cd backend && uv run mypy app
cd backend && uv run pytest

cd frontend && pnpm lint
cd frontend && pnpm test
cd frontend && pnpm build
cd frontend && pnpm playwright test
```

## 15. 开源依赖决策

- Python `deepagents`：MIT，作为 Agent 编排层。
- LangGraph：由 `deepagents` 使用，提供持久化、流式执行和 checkpoint 能力。
- FastAPI：本地 HTTP/SSE 服务。
- Tiptap、`@tiptap/markdown`、`prosemirror-changeset`：MIT，提供编辑与差异能力。
- Dulwich：`Apache-2.0 OR GPL-2.0-or-later`，按 Apache 2.0 使用，提供 Git 数据模型。
- Python `keyring`：MIT，提供系统钥匙串访问。
- SQLite FTS5：提供本地全文检索。
- pytest、Ruff、mypy、Vitest、Testing Library、Playwright：提供验证工具链。

不自研 Agent 框架、富文本编辑器、Git 差异算法、系统密钥存储或浏览器自动化框架。

## 16. 关键风险

- 模型质量差异会影响结构化输出和矛盾检测，必须按具体模型维护评测结果。
- 记忆提取属于模型推断，即使来源可追溯仍可能解释错误，必须允许修正和回滚。
- Markdown 与富文本双向转换必须限制支持的节点集合，避免不可逆格式丢失。
- 外部编辑与应用工作副本可能冲突，必须依赖版本 ID 检查，不能自动覆盖或静默合并。
- 1000 章规模不能靠全量提示词处理，任何绕过分层检索的实现都不符合本设计。
- Agent 的提示词约束不是安全边界，文件和网络权限必须由工具实现强制执行。

## 17. 参考资料

- Python Deep Agents：https://github.com/langchain-ai/deepagents
- JavaScript Deep Agents：https://github.com/langchain-ai/deepagentsjs
- Tiptap：https://github.com/ueberdosis/tiptap
- Lexical：https://github.com/facebook/lexical
- Milkdown：https://github.com/Milkdown/milkdown
- Dulwich：https://github.com/jelmer/dulwich
- keyring：https://github.com/jaraco/keyring
