.PHONY: dev.secret db.up db.down db.migrate db.reset pptx.canvas.parity

# Append a random JWT_SECRET to repo-root .env if not already set (local dev only).
dev.secret:
	@set -e; ROOT="$$(git rev-parse --show-toplevel 2>/dev/null || pwd)"; ENV="$$ROOT/.env"; \
	if [ -f "$$ENV" ] && grep -q '^JWT_SECRET=' "$$ENV"; then \
	  echo "Refusing: $$ENV already contains JWT_SECRET="; exit 1; \
	fi; \
	SECRET="$$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"; \
	echo "JWT_SECRET=$$SECRET" >> "$$ENV"; \
	echo "Appended JWT_SECRET to $$ENV"

# Database targets (Postgres via docker-compose)
db.up:
	docker compose up -d postgres
	@echo "Waiting for Postgres to be ready..."
	@until docker compose exec postgres pg_isready -U processdoc -d processdoc -q 2>/dev/null; do sleep 1; done
	@echo "Postgres ready. Run 'make db.migrate' to apply migrations."

db.down:
	docker compose stop postgres

db.migrate:
	cd backend && alembic upgrade head

db.reset:
	docker compose stop postgres
	docker compose rm -f postgres
	docker compose up -d postgres
	@until docker compose exec postgres pg_isready -U processdoc -d processdoc -q 2>/dev/null; do sleep 1; done
	cd backend && alembic upgrade head
	@echo "Database reset and migrated."

pptx.canvas.parity:
	python3 infra/scripts/pptx_canvas_parity_spike.py --strict
	python3 infra/scripts/pptx_canvas_visual_diff_spike.py --strict
