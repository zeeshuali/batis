.PHONY: up down logs seed migrate test

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

seed:
	docker compose exec backend python -m app.workers.run_data_jobs

migrate:
	docker compose exec backend psql $$DATABASE_URL -f sql/migrations/001_multi_agency.sql

test:
	cd backend && .venv/bin/pytest tests/ -v --tb=short
