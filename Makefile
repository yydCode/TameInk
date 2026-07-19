.PHONY: install backend-dev backend-worker frontend-dev test check e2e evaluate evaluate-live e2e-live verify

install:
	cd backend && uv sync
	cd frontend && pnpm install --frozen-lockfile
	cd evaluations && pnpm install --frozen-lockfile

backend-dev:
	cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

backend-worker:
	cd backend && uv run huey_consumer app.infrastructure.worker.huey -w 1 -k thread

frontend-dev:
	cd frontend && pnpm dev

test:
	cd backend && uv run pytest
	cd frontend && pnpm test --run

check:
	cd backend && uv run ruff check .
	cd backend && uv run mypy app
	cd frontend && pnpm lint
	cd frontend && pnpm build

e2e:
	cd frontend && pnpm e2e

evaluate:
	cd backend && uv run python ../evaluations/run.py --fixture-only
	cd evaluations && pnpm commercial:fixture

evaluate-live:
	cd backend && uv run python ../evaluations/live.py

e2e-live:
	cd frontend && pnpm exec playwright test -c playwright.live.config.ts

verify: test check evaluate e2e
