.PHONY: dev deploy-frontend deploy-backend deploy logs

# Run backend in watch mode (auto-restarts on code changes)
dev:
	docker compose watch

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