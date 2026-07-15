.PHONY: install backend-dev frontend-dev test check e2e evaluate verify

install:
	cd backend && uv sync
	cd frontend && pnpm install --frozen-lockfile

backend-dev:
	cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

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

verify: test check evaluate e2e
