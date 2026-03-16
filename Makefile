.PHONY: dev deploy-frontend deploy-backend deploy logs clean-tmp check-env

# ── Environment guard ─────────────────────────────────────────────────────────
# .env          → compose-level vars (SFTP_KEY_FILE, ports)
# backend/.env  → application secrets (API keys, SFTP creds, Navidrome, etc.)
check-env:
	@test -f .env         || { echo "ERROR: .env not found. Copy .env.example → .env and fill it in."; exit 1; }
	@test -f backend/.env || { echo "ERROR: backend/.env not found. Copy backend/.env.example → backend/.env and fill it in."; exit 1; }
	@for var in SFTP_HOST SFTP_USER SFTP_BASE; do \
		grep -q "^$$var=" backend/.env || { echo "ERROR: $$var is not set in backend/.env"; exit 1; }; \
	done
	@echo "Environment OK."

# ── Development ───────────────────────────────────────────────────────────────
dev: check-env
	docker compose up --build --watch

# ── Backend ───────────────────────────────────────────────────────────────────
deploy-backend: check-env
	docker compose up --build -d backend worker bot

# ── Frontend ──────────────────────────────────────────────────────────────────
deploy-frontend:
	cd frontend && npm run build && sudo cp -r dist/* /var/www/upload.redheadflag.com/

# ── Everything ────────────────────────────────────────────────────────────────
deploy: deploy-backend deploy-frontend

# ── Logs ─────────────────────────────────────────────────────────────────────
logs:
	docker compose logs -f backend worker

# ── Cleanup ───────────────────────────────────────────────────────────────────
# Remove leftover temp files from the backend and worker containers
clean-tmp:
	docker compose exec backend find /tmp -maxdepth 1 \( -name "metamusic_*" -o -name "sc_dl_*" \) -exec rm -rf {} +
	docker compose exec worker  find /tmp -maxdepth 1 \( -name "metamusic_*" -o -name "sc_dl_*" \) -exec rm -rf {} +
	@echo "Temp files cleaned."
