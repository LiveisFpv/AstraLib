# AstraLib Gateway Service

Gateway - HTTP API слой AstraLib на Go/Gin. Он принимает REST-запросы frontend, проверяет JWT через внешний SSO, применяет ролевую авторизацию, управляет чатами и author submissions, а поисковые и ingestion-операции проксирует в semantic-service по gRPC.

## Возможности

- REST API с base path `/api`;
- Swagger UI на `/swagger/index.html`;
- CORS по списку `ALLOWED_CORS_ORIGINS`;
- проверка JWT через `SSO_HTTP_URL/api/auth/validate`;
- получение профиля и ролей через `SSO_HTTP_URL/api/auth/authenticate`;
- role-based доступ для author/moderation endpoints;
- gRPC-клиент semantic-service по `AI_GRPC_ADDR`;
- endpoints для чатов, истории поиска, авторских публикаций и модерации;
- опциональная Basic Auth для Swagger.

## Архитектура

- `cmd/main.go` - точка входа;
- `internal/config/config.go` - загрузка env через `cleanenv`;
- `internal/app/app.go` - сборка зависимостей приложения;
- `internal/transport/http/server.go` - Gin server, CORS, Swagger, route groups;
- `internal/transport/http/router.go` - регистрация endpoints;
- `internal/transport/http/middlewares/` - JWT/role middleware и logging;
- `internal/transport/http/handlers/` - HTTP handlers;
- `internal/transport/http/presenters/` - преобразование доменных моделей в HTTP DTO;
- `internal/service/` - бизнес-логика gateway;
- `internal/transport/rpc/semantic_client.go` - gRPC-клиент semantic-service;
- `proto/service.proto` - gRPC-контракт с semantic-service;
- `gen/go/` - сгенерированные protobuf/gRPC файлы;
- `docs/` - сгенерированный Swagger;
- `tools/migrator/` и `db/migrations/` - мигратор и SQL-миграции, если используется локальная БД gateway.

## Быстрый старт в корневом стеке

Обычно gateway запускается из корня репозитория вместе с nginx, frontend и semantic-service:

```bash
cd ../..
cp .env.example .env
docker compose --env-file .env up -d --build gateway
```

В корневом compose gateway:

- слушает `HTTP_PORT=8080` внутри контейнера;
- доступен наружу через nginx по `/api`;
- подключается к semantic-service по `semantic-service:${SEMANTIC_PORT:-5104}`;
- использует `SSO_HTTP_URL` для проверки токенов;
- не публикует порт напрямую, а использует `expose`.

## Изолированный Docker Compose

Сервисный `docker-compose.yml` полезен для разработки gateway отдельно от корневого стека.

1. Создайте внешнюю сеть, если она еще не создана:

```bash
docker network create grpc_network
```

2. Подготовьте `.env` в `services/gateway`:

```env
DOMAIN=localhost
PUBLIC_URL=http://localhost:8080
ALLOWED_REDIRECT_URLS=http://localhost
ALLOWED_CORS_ORIGINS=http://localhost,http://localhost:5173
HTTP_PORT=8080
SWAGGER_ENABLED=true
SWAGGER_USER=
SWAGGER_PASSWORD=
GRPC_TIMEOUT=24h
AI_GRPC_ADDR=semantic-service:5104
SSO_HTTP_URL=https://id.example.com
```

3. Запустите:

```bash
docker compose --env-file .env up --build
```

Если semantic-service запущен в другом compose, он должен быть подключен к `grpc_network`, а `AI_GRPC_ADDR` должен указывать на его network alias и порт.

## Локальная разработка

Требования:

- Go 1.23+;
- доступный SSO API;
- доступный semantic-service gRPC;
- `protoc`, если нужно пересоздавать gRPC stubs;
- `swag`, если нужно пересоздавать Swagger docs.

Запуск:

```bash
go run ./cmd
```

С переменными PowerShell:

```powershell
$env:HTTP_PORT="8080"
$env:ALLOWED_CORS_ORIGINS="http://localhost:5173"
$env:AI_GRPC_ADDR="localhost:5104"
$env:SSO_HTTP_URL="https://id.example.com"
go run ./cmd
```

## Переменные окружения

Обязательные для рабочего API:

- `ALLOWED_CORS_ORIGINS` - список origins через запятую. Если пусто, gateway завершает запуск;
- `SSO_HTTP_URL` - базовый URL внешнего SSO;
- `AI_GRPC_ADDR` - адрес semantic-service в формате `host:port`.

Основные:

- `DOMAIN` - домен сервиса, используется для Swagger host fallback;
- `PUBLIC_URL` - публичный URL, по нему выставляются Swagger host/scheme;
- `ALLOWED_REDIRECT_URLS` - список допустимых redirect URLs;
- `HTTP_PORT` - порт HTTP server, по умолчанию `8080`;
- `GRPC_TIMEOUT` - timeout для gRPC и SSO HTTP client, по умолчанию `5s`;
- `SWAGGER_ENABLED` - включает Swagger, по умолчанию `true`;
- `SWAGGER_USER`, `SWAGGER_PASSWORD` - если оба заданы, Swagger закрывается Basic Auth.

Переменные БД (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_SSL`) оставлены в конфигурации и миграторе, но основной runtime gateway сейчас работает как API/gRPC слой без собственной активной Postgres-зависимости в корневом compose.

## API

Base path: `/api`.

Все защищенные endpoints ожидают:

```http
Authorization: Bearer <token>
```

### Chats/search

- `POST /api/chats` - создать чат;
- `GET /api/chats` - список чатов пользователя;
- `GET /api/chats/{chat_id}/history` - история чата;
- `POST /api/chats/{chat_id}/history` - отправить поисковый запрос;
- `PUT /api/chats/{chat_id}` - переименовать чат;
- `DELETE /api/chats/{chat_id}` - удалить чат.

### Author submissions

Доступны авторизованным пользователям с ролями, которые возвращает SSO и которые допускает frontend workflow.

- `POST /api/submissions` - создать submission;
- `GET /api/submissions` - список своих submissions;
- `GET /api/submissions/{submission_id}` - получить свой submission;
- `PUT /api/submissions/{submission_id}` - обновить свой submission;
- `DELETE /api/submissions/{submission_id}` - удалить draft/rejected submission;
- `POST /api/submissions/{submission_id}/submit` - отправить на модерацию.

### Moderation

Требует роль `MODERATOR` или `ADMIN`.

- `GET /api/moderation/submissions` - очередь модерации;
- `GET /api/moderation/submissions/{submission_id}` - карточка submission;
- `PUT /api/moderation/submissions/{submission_id}` - обновить staged-данные;
- `POST /api/moderation/submissions/{submission_id}/moderate` - approve/reject.

При approve gateway вызывает semantic-service, где статья ставится в ingestion queue.

## Swagger

Swagger UI:

```text
http://localhost:8080/swagger/index.html
```

Если gateway работает за nginx, используйте:

```text
https://<domain>/swagger/index.html
```

Перегенерация docs:

```bash
swag init -g cmd/main.go -o docs
```

## gRPC stubs

Контракт лежит в `proto/service.proto`. Перегенерация:

```powershell
protoc -I proto `
  --go_out=gen/go --go_opt=paths=source_relative `
  --go-grpc_out=gen/go --go-grpc_opt=paths=source_relative `
  proto/service.proto
```

После изменения proto нужно синхронизировать контракт с `services/semantic/proto/service.proto` и Python-generated файлами semantic-service.

## Проверки

```bash
go test ./...
go vet ./...
```

Перед интеграционной проверкой убедитесь, что:

- `ALLOWED_CORS_ORIGINS` содержит origin frontend;
- `SSO_HTTP_URL` доступен из контейнера или локального окружения;
- `AI_GRPC_ADDR` указывает на живой semantic-service;
- Swagger включен, если нужен ручной smoke-test API.
