# AERP developer shortcuts. On Windows, run these targets' commands directly if
# `make` isn't installed (e.g. via Git Bash + GNU Make, or copy the command).

COMPOSE = docker compose -f infra/docker-compose.yml

.PHONY: up down logs build test lint migrate seed shell fmt

up:            ## Start the full local stack
	$(COMPOSE) up --build

down:          ## Stop the stack and remove containers
	$(COMPOSE) down

logs:          ## Tail all service logs
	$(COMPOSE) logs -f

build:         ## Rebuild images
	$(COMPOSE) build

migrate:       ## Apply DB migrations inside the api container
	$(COMPOSE) exec api alembic upgrade head

seed:          ## Run the reference-data seed inside the api container
	$(COMPOSE) exec api python -m app.db.seed

shell:         ## Open a shell in the api container
	$(COMPOSE) exec api bash

test:          ## Run the backend test suite locally
	cd backend && pytest -q

lint:          ## Lint the backend
	cd backend && ruff check .

fmt:           ## Auto-fix lint/format issues
	cd backend && ruff check . --fix
