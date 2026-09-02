.PHONY: help install test lint lint-backend lint-frontend format check \
	db-up db-down db-migrate dev-backend dev-frontend

help:
	@echo "Available targets:"
	@echo "  install       - install backend (uv sync) and frontend (npm install) deps"
	@echo "  test          - run backend test suite (uv run pytest)"
	@echo "  lint          - lint backend (ruff check) and frontend (eslint)"
	@echo "  lint-backend  - lint backend only (uv run ruff check .)"
	@echo "  lint-frontend - lint frontend only (npm run lint)"
	@echo "  format        - format backend code (uv run ruff format .)"
	@echo "  check         - lint + test"
	@echo "  db-up         - start local Postgres (docker compose up -d)"
	@echo "  db-down       - stop local Postgres (docker compose down)"
	@echo "  db-migrate    - apply Alembic migrations (uv run alembic upgrade head)"
	@echo "  dev-backend   - run the backend dev server (uv run uvicorn --reload)"
	@echo "  dev-frontend  - run the frontend dev server (npm run dev)"

install:
	cd backend && uv sync
	cd frontend && npm install

test:
	cd backend && uv run pytest

lint: lint-backend lint-frontend

lint-backend:
	cd backend && uv run ruff check .

lint-frontend:
	cd frontend && npm run lint

format:
	cd backend && uv run ruff format .

check: lint test

db-up:
	docker compose up -d

db-down:
	docker compose down

db-migrate:
	cd backend && uv run alembic upgrade head

dev-backend:
	cd backend && uv run uvicorn app.main:app --reload

dev-frontend:
	cd frontend && npm run dev
