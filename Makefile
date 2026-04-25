.PHONY: dev deploy-frontend deploy-backend deploy logs clean-tmp check-env

COMPOSE = docker compose --env-file backend/.env

# ── Environment guard ─────────────────────────────────────────────────────────
# backend/.env  → single source of truth for all settings
check-env:
	@bash scripts/check-env.sh backend/.env

# ── Development ───────────────────────────────────────────────────────────────
dev: check-env
	$(COMPOSE) up --build --watch

# ── Backend ───────────────────────────────────────────────────────────────────
deploy-backend: check-env
	$(COMPOSE) up --build -d backend worker bot

# ── Frontend ──────────────────────────────────────────────────────────────────
deploy-frontend:
	cd frontend && npm run build && sudo cp -r dist/* /var/www/upload.redheadflag.com/

# ── Everything ────────────────────────────────────────────────────────────────
deploy: deploy-backend deploy-frontend

# ── Logs ─────────────────────────────────────────────────────────────────────
logs:
	$(COMPOSE) logs -f backend worker

# ── Cleanup ───────────────────────────────────────────────────────────────────
# Remove leftover temp files from the backend and worker containers
clean-tmp:
	$(COMPOSE) exec backend find /tmp -maxdepth 1 \( -name "metamusic_*" -o -name "sc_dl_*" \) -exec rm -rf {} +
	$(COMPOSE) exec worker  find /tmp -maxdepth 1 \( -name "metamusic_*" -o -name "sc_dl_*" \) -exec rm -rf {} +
	@echo "Temp files cleaned."
