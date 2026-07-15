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

