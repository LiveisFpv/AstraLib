# AstraLib

AstraLib - web-приложение для семантического поиска научных публикаций. Система объединяет поиск по текстовому смыслу, граф внешних цитирований, авторскую загрузку статей, модерацию материалов и пользовательский интерфейс с ролями.

## Назначение

Цель проекта - построить поисковую систему для научных публикаций, которая учитывает не только текст статьи, но и связи между работами. Бэкенд хранит публикации и граф цитирований, строит FAISS-индекс на эмбеддингах `intfloat/multilingual-e5-large`, а frontend предоставляет поиск, историю чатов, кабинет автора, очередь модерации и администрирование пользователей через внешний SSO.

## Структура репозитория

```text
AstraLib/
├── apps/
│   └── frontend/              # Vue 3 + TypeScript + Vite
├── deploy/
│   └── nginx/templates/       # шаблоны nginx для HTTP, HTTPS и Cloudflare Tunnel
├── docs/
│   └── PhysicalModel.png      # физическая модель данных
├── services/
│   ├── gateway/               # Go HTTP API Gateway
│   ├── semantic/              # Python gRPC semantic/search service
│   └── ELK/                   # Elastic + Logstash + Kibana
├── docker-compose.yml         # общий стек приложения
├── Makefile                   # команды деплоя и управления стеком
└── .env.example               # пример окружения
```

## Компоненты

- `apps/frontend` - web UI: авторизация через SSO, поиск, чаты, страницы публикаций, кабинет автора, панели модератора и администратора.
- `services/gateway` - REST API на Go/Gin. Проверяет JWT через внешний SSO, применяет ролевые ограничения и проксирует поисковые/author-запросы в semantic-service по gRPC.
- `services/semantic` - Python-сервис семантического поиска. Работает с PostgreSQL, FAISS, E5-эмбеддингами, ingestion-очередью, OpenAlex и citation-aware weighted runtime.
- `services/ELK` - отдельный стек наблюдаемости.
- `deploy/nginx/templates` - nginx-конфигурации для production, ACME challenge и Cloudflare Tunnel.

## Архитектура запуска

Корневой `docker-compose.yml` поднимает:

- `nginx` или `nginx-dev` - публичная точка входа;
- `frontend` или `frontend-dev` - Vue-приложение;
- `gateway` - REST API `/api` и Swagger `/swagger`;
- `semantic-service` - gRPC-сервис поиска;
- `semantic-postgres` - PostgreSQL для semantic-service;
- `semantic-migrator` - автоматическое применение миграций semantic DB;
- `pipeline-worker` - фоновый процесс ingestion pipeline;
- `certbot` - выпуск/продление Let's Encrypt сертификатов;
- `cloudflared` - Cloudflare Tunnel при соответствующем профиле.

Маршрутизация nginx:

- `/` - frontend;
- `/api/` - gateway;
- `/swagger/` - Swagger UI gateway;
- `/.well-known/acme-challenge/` - ACME challenge для Let's Encrypt.

## Внешние зависимости

### SSO

Подсистема SSO считается заменяемым внешним сервисом. Используются HTTP endpoints:

- `/api/auth/login`, `/api/auth/logout`, `/api/auth/refresh`;
- `/api/auth/authenticate` - профиль и роли;
- `/api/auth/validate` - проверка JWT для gateway;
- `/api/oauth/{provider}` - OAuth redirect для frontend;
- `/api/auth/admin/users` - административные операции с пользователями.

Ключевые переменные:

- `SSO_HTTP_URL` - URL SSO для gateway;
- `VITE_SSO_CLIENT_ID_URL` - URL SSO API для frontend;
- `ALLOWED_CORS_ORIGINS` и `ALLOWED_REDIRECT_URLS` - публичные origins/redirect URLs.

### Данные поиска

Для полноценного поиска нужны артефакты FAISS и эмбеддингов в `services/semantic/data/index`. Минимальные пути задаются:

- `FAISS_INDEX_PATH`;
- `FAISS_DOC_IDS_PATH`;
- `EMBEDDING_MODEL_NAME`;
- `EMBEDDING_LORA_PATH`, если используется LoRA.

Если индекса нет, его нужно построить pipeline-скриптами semantic-service. Подробности описаны в [services/semantic/README.md](services/semantic/README.md).

## Быстрый старт через Docker Compose

1. Скопируйте окружение:

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

2. Отредактируйте `.env`:

- `APP_DOMAIN`, `PUBLIC_URL`, `VITE_FRONTEND_BASE_URL`, `VITE_API_BASE_URL`;
- `SSO_HTTP_URL`, `VITE_SSO_CLIENT_ID_URL`;
- `SEMANTIC_DB_PASSWORD`;
- `FAISS_INDEX_PATH`, `FAISS_DOC_IDS_PATH`;
- `OPENALEX_EMAIL`, если используется OpenAlex ingestion.

3. Запустите production-стек:

```bash
docker compose --env-file .env up -d --build
```

4. Проверьте состояние:

```bash
docker compose --env-file .env ps
docker compose --env-file .env logs -f --tail=200
```

По умолчанию nginx слушает `80` и `443`, gateway доступен за nginx по `/api`, Swagger - по `/swagger/index.html`.

## Локальный dev-стек

Для разработки frontend с HMR и остальными сервисами из корневого compose:

```bash
make dev
```

Без Makefile:

```bash
docker compose --env-file .env --profile dev up --build nginx-dev pipeline-worker
```

В dev-профиле `frontend-dev` получает alias `frontend`, а nginx проксирует трафик на Vite dev server.

## Деплой

### HTTPS через Let's Encrypt

Укажите в `.env` реальный домен и email:

```env
APP_DOMAIN=example.com
CERTBOT_EMAIL=admin@example.com
PUBLIC_URL=https://example.com
VITE_FRONTEND_BASE_URL=https://example.com
VITE_API_BASE_URL=https://example.com
VITE_ALIB_API_URL=/api
```

Первый запуск:

```bash
make first-deploy
```

Полезные команды:

```bash
make cert-renew
make deploy
make logs
make ps
make down
```

### Cloudflare Tunnel

Укажите:

```env
APP_DOMAIN=example.com
CLOUDFLARED_TOKEN=<token>
NGINX_MODE=cloudflared
```

Запуск:

```bash
make cloudflared-deploy
```

В этом режиме TLS завершается на Cloudflare, а tunnel обращается к nginx по внутреннему HTTP.

## Переменные окружения

Основные группы переменных лежат в `.env.example`:

- публичные URL и nginx: `APP_DOMAIN`, `PUBLIC_URL`, `NGINX_MODE`, `NGINX_HTTP_PORT`, `NGINX_HTTPS_PORT`;
- frontend: `VITE_API_BASE_URL`, `VITE_FRONTEND_BASE_URL`, `VITE_ALIB_API_URL`, `VITE_SSO_CLIENT_ID_URL`;
- gateway: `GATEWAY_DOMAIN`, `ALLOWED_CORS_ORIGINS`, `ALLOWED_REDIRECT_URLS`, `GRPC_TIMEOUT`, `SWAGGER_ENABLED`;
- semantic DB: host внутри compose задан как `semantic-postgres`, а пользовательские значения задаются через `SEMANTIC_DB_PORT`, `SEMANTIC_DB_PUBLIC_PORT`, `SEMANTIC_DB_USER`, `SEMANTIC_DB_PASSWORD`, `SEMANTIC_DB_NAME`;
- semantic search: `FAISS_INDEX_PATH`, `FAISS_DOC_IDS_PATH`, `EMBEDDING_MODEL_NAME`, `EMBEDDING_BATCH_SIZE`;
- ingestion: `INGESTION_SCHEDULER_ENABLED`, `INGESTION_OPENALEX_ENABLED`, `INGESTION_OPENALEX_LIMIT`, `INGESTION_WEIGHTED_RUNTIME_REQUIRED`;
- pipeline: `PIPELINE_OPENALEX_EN`, `PIPELINE_OPENALEX_RU`, `PIPELINE_OPENALEX_CHUNK`.

## API

Основные защищенные gateway endpoints:

- `POST /api/chats`, `GET /api/chats`;
- `GET /api/chats/{chat_id}/history`, `POST /api/chats/{chat_id}/history`;
- `PUT /api/chats/{chat_id}`, `DELETE /api/chats/{chat_id}`;
- `POST /api/submissions`, `GET /api/submissions`;
- `GET /api/submissions/{submission_id}`, `PUT /api/submissions/{submission_id}`, `DELETE /api/submissions/{submission_id}`;
- `POST /api/submissions/{submission_id}/submit`;
- `GET /api/moderation/submissions`;
- `GET /api/moderation/submissions/{submission_id}`;
- `PUT /api/moderation/submissions/{submission_id}`;
- `POST /api/moderation/submissions/{submission_id}/moderate`.

Все защищенные endpoints ожидают `Authorization: Bearer <token>`.

## Документация сервисов

- [Frontend](apps/frontend/README.md)
- [Gateway](services/gateway/readme.md)
- [Semantic](services/semantic/README.md)
- [ELK stack](services/ELK/README.md)
- [sso](services/sso/readme.md)

## Проверки

Frontend:

```bash
cd apps/frontend
npm run type-check
npm run test:unit
npm run build
```

Gateway:

```bash
cd services/gateway
go test ./...
```

Semantic:

```bash
cd services/semantic
python -m compileall src cmd tests
pytest
```

## Статус разработки

- [x] Сбор и обработка данных публикаций и цитирований.
- [x] Интеграция E5-модели и FAISS-поиска.
- [x] Citation-aware weighted runtime и инкрементальное обновление затронутых 2-hop соседей.
- [x] REST gateway, gRPC-интеграция и Swagger.
- [x] Web UI: поиск, чаты, роли, кабинет автора, модерация, админ-панель.
- [x] Авторская загрузка публикаций через очередь ingestion.
- [x] Планировщик пополнения базы знаний из OpenAlex.
- [ ] Оценка качества поиска на размеченной выборке.
- [ ] Финальная настройка наблюдаемости и эксплуатационных метрик.
