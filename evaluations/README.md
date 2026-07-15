# 一致性评测

默认命令只校验固定中文评测集的 Schema，不访问网络：

```bash
cd backend && uv run python ../evaluations/run.py --fixture-only
```

真实模型评测必须显式提供单一 OpenAI-compatible 配置：

```bash
export OPENAI_API_KEY="..."
export TAME_INK_MODEL="model-name"
export TAME_INK_BASE_URL="https://example.com/v1"
cd backend && uv run python ../evaluations/run.py --live
```

输出记录模型、Base URL、各用例 precision 和 recall，不打印 API Key。

## 商业留存评测

商业审查使用 `promptfoo`。默认固定评测不会调用模型：

```bash
cd evaluations && pnpm commercial:fixture
```

真实模型评测复用相同案例、提示词和确定性断言：

```bash
export OPENAI_API_KEY="..."
export TAME_INK_MODEL="model-name"
export TAME_INK_BASE_URL="https://example.com/v1"
cd evaluations && pnpm commercial:live
```

报告检查七个商业维度、平均分、通过/修订判断，以及问题引用是否精确匹配候选正文。评分只代表当前评测集中的提示词表现，不代表收入预测。
