.PHONY: up down logs api worker frontend install test lint seed clean

up:            ## Start the full stack (Postgres, Redis, API, worker, dashboard)
	docker compose up --build -d

down:          ## Stop the stack
	docker compose down

logs:          ## Tail all container logs
	docker compose logs -f

install:       ## Install backend deps into the active virtualenv
	pip install -r backend/requirements.txt -r backend/requirements-dev.txt

api:           ## Run the API locally (workers off)
	cd backend && uvicorn app.main:app --reload --port 8000

worker:        ## Run the worker loops locally
	cd backend && python -m app.workers.runner

frontend:      ## Run the dashboard locally
	cd frontend && npm install && npm run dev

test:          ## Run backend tests
	cd backend && python -m pytest -q

lint:          ## Static checks
	cd backend && python -m compileall -q app tests scripts

seed:          ## Load synthetic demo data so the dashboard has content
	cd backend && python -m scripts.seed_demo

clean:
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
