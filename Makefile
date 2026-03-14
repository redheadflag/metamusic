.PHONY: dev deploy-frontend deploy-backend deploy logs clean-tmp

# Start and watch (auto-restarts on code changes)
dev:
	docker compose up --build --watch

# Rebuild and restart the backend container
deploy-backend:
	docker compose up --build -d

# Rebuild frontend and copy to nginx web root
deploy-frontend:
	cd frontend && npm run build && sudo cp -r dist/* /var/www/upload.redheadflag.com/

# Deploy everything
deploy: deploy-backend deploy-frontend

# Tail backend logs
logs:
	docker compose logs -f backend

# Remove leftover temp files from inside the backend container
clean-tmp:
	docker compose exec backend find /tmp -maxdepth 1 -name "metamusic_*" -exec rm -rf {} +
	@echo "Temp files cleaned."