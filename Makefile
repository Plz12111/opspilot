.PHONY: install dev migrate migration test lint format eval compose-up demo-up demo-seed smoke resilience-test resilience-quick compose-down

install:
	uv sync --all-groups

dev:
	PYTHONPATH=src uv run uvicorn opspilot.main:app --reload

migrate:
	PYTHONPATH=src uv run alembic upgrade head

migration:
	PYTHONPATH=src uv run alembic revision --autogenerate -m "$(name)"

test:
	PYTHONPATH=src uv run pytest -q

lint:
	PYTHONPATH=src uv run ruff check .
	PYTHONPATH=src uv run ruff format --check .

format:
	PYTHONPATH=src uv run ruff check --fix .
	PYTHONPATH=src uv run ruff format .

eval:
	PYTHONPATH=src uv run python -m opspilot.evaluation.cli

eval-dataset:
	PYTHONPATH=src uv run python evals/incidents/build_dataset.py

compose-up:
	docker compose up -d postgres redis

demo-up:
	docker compose up -d --build

demo-seed:
	PYTHONPATH=src uv run opspilot-demo seed --base-url $${OPSPILOT_BASE_URL:-http://127.0.0.1:8000}

smoke:
	PYTHONPATH=src uv run python scripts/smoke.py --base-url $${OPSPILOT_BASE_URL:-http://127.0.0.1:8000}

resilience-test:
	PYTHONPATH=src uv run python scripts/resilience_test.py --concurrency $${CONCURRENCY:-50}

resilience-quick:
	PYTHONPATH=src uv run python scripts/resilience_test.py --quick --concurrency $${CONCURRENCY:-20}

compose-down:
	docker compose down
