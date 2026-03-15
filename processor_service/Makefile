.DEFAULT_GOAL := help
.PHONY: help install run run-docker build stop logs

ENV_FILE ?= .env

# ── Local (venv) ──────────────────────────────────────────────────────────────

install:                         ## Create venv and install dependencies
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt

run:                             ## Run the processor directly (requires venv)
	@test -f $(ENV_FILE) || (echo "ERROR: $(ENV_FILE) not found. Copy .env.example → .env and fill it in." && exit 1)
	.venv/bin/python main.py

# ── Docker ────────────────────────────────────────────────────────────────────

build:                           ## Build the Docker image
	docker build -t metamusic-processor .

run-docker:                      ## Run the processor in Docker (reads .env)
	@test -f $(ENV_FILE) || (echo "ERROR: $(ENV_FILE) not found. Copy .env.example → .env and fill it in." && exit 1)
	docker run --rm -it \
		--name metamusic-processor \
		--env-file $(ENV_FILE) \
		$(if $(SFTP_KEY_FILE),--volume "$(SFTP_KEY_FILE):/run/secrets/sftp_key:ro" --env SFTP_KEY_FILE=/run/secrets/sftp_key,) \
		metamusic-processor

stop:                            ## Stop the running Docker container
	docker stop metamusic-processor

logs:                            ## Tail logs from the running Docker container
	docker logs -f metamusic-processor

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'