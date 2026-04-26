ENV_FILE ?= .env

ifneq ("$(wildcard $(ENV_FILE))","")
include $(ENV_FILE)
export
endif

COMPOSE ?= docker compose --env-file $(ENV_FILE)
DOMAIN ?= $(APP_DOMAIN)
CERTBOT_EMAIL_ARG := $(if $(CERTBOT_EMAIL),--email $(CERTBOT_EMAIL),--register-unsafely-without-email)
CERTBOT_STAGING_ARG := $(if $(filter 1 true yes,$(CERTBOT_STAGING)),--staging,)

ifeq ($(OS),Windows_NT)
COPY_ENV := copy /Y .env.example "$(ENV_FILE)"
SET_NGINX_CLOUDFLARED := set NGINX_MODE=cloudflared&&
else
COPY_ENV := cp .env.example "$(ENV_FILE)"
SET_NGINX_CLOUDFLARED := NGINX_MODE=cloudflared
endif

.PHONY: help env config build up down restart ps logs deploy first-deploy cloudflared-deploy cloudflared-up cloudflared-logs cert-init cert-renew cert-dry-run nginx-reload check-domain check-cloudflared-token

help:
	@echo "ALib deployment commands"
	@echo "  make env             Copy .env.example to .env if .env does not exist"
	@echo "  make config          Validate docker compose config"
	@echo "  make build           Build application images"
	@echo "  make up              Start stack"
	@echo "  make down            Stop stack"
	@echo "  make restart         Restart stack"
	@echo "  make logs            Follow logs"
	@echo "  make deploy          Build and start stack"
	@echo "  make first-deploy    Build, issue certificate, and start stack"
	@echo "  make cloudflared-deploy  Build and start stack with Cloudflare Tunnel"
	@echo "  make cert-init       Issue the first Let's Encrypt certificate"
	@echo "  make cert-renew      Renew certificates and reload nginx"
	@echo "  make cert-dry-run    Test renewal without changing certificates"

env:
	$(if $(wildcard $(ENV_FILE)),@echo "$(ENV_FILE) already exists.",$(COPY_ENV))

config:
	$(COMPOSE) config --quiet

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) up -d --force-recreate

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=200

deploy: config build up

first-deploy: config build cert-init up

cloudflared-deploy: check-cloudflared-token config build
	$(SET_NGINX_CLOUDFLARED) $(COMPOSE) --profile cloudflared up -d

cloudflared-up: check-cloudflared-token
	$(SET_NGINX_CLOUDFLARED) $(COMPOSE) --profile cloudflared up -d

cloudflared-logs:
	$(COMPOSE) --profile cloudflared logs -f --tail=200 cloudflared

check-domain:
	$(if $(filter-out localhost example.com,$(strip $(DOMAIN))),@echo "Domain is $(DOMAIN).",$(error Set APP_DOMAIN in $(ENV_FILE) to a real public domain before requesting certificates.))

check-cloudflared-token:
	$(if $(strip $(CLOUDFLARED_TOKEN)),@echo "Cloudflare Tunnel token is configured.",$(error Set CLOUDFLARED_TOKEN in $(ENV_FILE) before starting Cloudflare Tunnel.))

cert-init: check-domain
	$(COMPOSE) up -d nginx
	$(COMPOSE) --profile certbot run --rm certbot certonly --webroot -w /var/www/certbot --non-interactive --agree-tos $(CERTBOT_EMAIL_ARG) $(CERTBOT_STAGING_ARG) -d $(DOMAIN)
	$(COMPOSE) restart nginx

cert-renew: check-domain
	$(COMPOSE) --profile certbot run --rm certbot renew --webroot -w /var/www/certbot
	$(COMPOSE) exec nginx nginx -s reload

cert-dry-run: check-domain
	$(COMPOSE) --profile certbot run --rm certbot renew --dry-run --webroot -w /var/www/certbot

nginx-reload:
	$(COMPOSE) exec nginx nginx -s reload
