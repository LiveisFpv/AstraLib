# AstraLib Semantic Service

Semantic-service - Python gRPC сервис поиска и ingestion для AstraLib. Он хранит публикации, авторов, организации, историю чатов, author submissions и граф цитирований в PostgreSQL, кодирует тексты моделью `intfloat/multilingual-e5-large`, ищет ближайшие публикации в FAISS и поддерживает citation-aware weighted runtime.

## Возможности

- gRPC API для поиска и добавления публикаций;
- семантический поиск по FAISS;
- хранение истории чатов и результатов поиска;
- ingestion авторских публикаций после модерации;
- периодическое пополнение базы из OpenAlex;
- очередь ingestion-задач с retry/stale handling;
- хранение графа цитирований в PostgreSQL;
- pending citation edges для ссылок на еще не известные статьи;
- mutable weighted FAISS runtime с `paper_id` как external ID;
- инкрементальный пересчет citation-aware векторов для затронутого 2-hop closure;
- offline pipeline для OpenAlex, эмбеддингов, FAISS и citation cache.

## Архитектура

- `cmd/main.py` - точка входа gRPC сервиса;
- `src/config/config.py` - настройки БД, FAISS, модели и логирования;
- `src/http/grpc/` - gRPC server, handlers, auth helpers и generated protobuf;
- `src/services/search/` - FAISS searcher и search service;
- `src/services/ingestion/` - ingestion queue, scheduler, OpenAlex client, weighted runtime;
- `src/services/` - user, chat и submission services;
- `src/storage/` - repositories PostgreSQL;
- `src/domain/models/` - доменные модели;
- `src/parser/` - offline scripts для OpenAlex, E5, FAISS, citation cache и weighted runtime repair/bootstrap;
- `src/pipeline/` - orchestrated ingestion pipeline;
- `scripts/` - healthcheck, benchmark и runner pipeline-worker;
- `db/migrations/` - SQL-миграции;
- `tools/migrator/` - Go-мигратор.

## Быстрый старт в корневом стеке

Из корня репозитория:

```bash
cp .env.example .env
docker compose --env-file .env up -d --build semantic-postgres semantic-migrator semantic-service pipeline-worker
```

Корневой compose:

- поднимает PostgreSQL `semantic-postgres`;
- применяет миграции через `semantic-migrator`;
- запускает `semantic-service` на `SEMANTIC_PORT` внутри сети backend;
- монтирует `./services/semantic/data` в `/app/data`;
- запускает `pipeline-worker`;
- хранит Hugging Face cache в volume `hf-cache`;
- проверяет сервис через `scripts/healthcheck.py`.

Логи:

```bash
docker compose --env-file .env logs -f semantic-service
docker compose --env-file .env logs -f pipeline-worker
```

## Изолированный Docker Compose

В каталоге `services/semantic` есть отдельный compose для разработки сервиса.

1. Создайте внешнюю сеть для связи с gateway:

```bash
docker network create grpc_network
```

2. Подготовьте `.env`:

```env
SEMANTIC_HOST=0.0.0.0
SEMANTIC_PORT=5104
DB_HOST=postgres
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=password
DB_NAME=semantic_db
SSLMode=disable
FAISS_INDEX_PATH=data/index/faiss_both.index
FAISS_DOC_IDS_PATH=data/index/doc_ids_both.npy
EMBEDDING_MODEL_NAME=intfloat/multilingual-e5-large
EMBEDDING_BATCH_SIZE=128
INGESTION_SCHEDULER_ENABLED=true
INGESTION_OPENALEX_ENABLED=false
INGESTION_WEIGHTED_RUNTIME_REQUIRED=false
```

3. Запустите:

```bash
docker compose --env-file .env up -d --build
```

PostgreSQL будет опубликован на `localhost:15432`, а gRPC сервис - на `localhost:5104`.

## Локальный запуск

Требования:

- Python 3.12;
- PostgreSQL 14+;
- зависимости из `requirements.txt`;
- FAISS artifact files, если нужен реальный поиск;
- доступ к Hugging Face model cache или интернету для загрузки модели.

Установка:

```powershell
python -m venv .venv
. .venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
```

Если PostgreSQL поднят через сервисный compose:

```powershell
$env:DB_HOST="localhost"
$env:DB_PORT="15432"
$env:DB_USER="postgres"
$env:DB_PASSWORD="password"
$env:DB_NAME="semantic_db"
```

Запуск:

```powershell
python cmd/main.py
```

Healthcheck:

```powershell
python scripts/healthcheck.py
```

## Конфигурация

### Сервис и логирование

- `SEMANTIC_HOST` - host gRPC server, в Docker задается `0.0.0.0`;
- `SEMANTIC_PORT` - gRPC port, по умолчанию `5104`;
- `LOG_LEVEL` - уровень логирования;
- `LOGSTASH_HOST`, `LOGSTASH_PORT` - отправка логов в Logstash, если настроено.

### PostgreSQL

- `DATABASE_URL` - полный SQLAlchemy URL, если задан;
- `DB_HOST`;
- `DB_PORT`;
- `DB_USER`;
- `DB_PASSWORD`;
- `DB_NAME`;
- `SSLMode` или `DB_SSL_MODE`.

### Индекс и модель

- `FAISS_INDEX_PATH` - путь к FAISS index;
- `FAISS_DOC_IDS_PATH` - путь к numpy mapping file;
- `EMBEDDING_MODEL_NAME` - модель encoder, по умолчанию `intfloat/multilingual-e5-large`;
- `EMBEDDING_BATCH_SIZE`;
- `EMBEDDING_LORA_PATH` - опциональный LoRA adapter.

### Ingestion scheduler

- `INGESTION_SCHEDULER_ENABLED`;
- `INGESTION_SCHEDULER_POLL_SECONDS`;
- `INGESTION_SCHEDULER_MAX_TASKS`;
- `INGESTION_TASK_STALE_SECONDS`;
- `INGESTION_TASK_RETRY_SECONDS`;
- `INGESTION_TASK_MAX_ATTEMPTS`;
- `INGESTION_WEIGHTED_RUNTIME_REQUIRED`.

### OpenAlex top-up

- `INGESTION_OPENALEX_ENABLED`;
- `INGESTION_OPENALEX_INTERVAL_SECONDS`;
- `INGESTION_OPENALEX_LIMIT`;
- `INGESTION_OPENALEX_TIMEOUT_SECONDS`;
- `INGESTION_OPENALEX_LANGUAGES`;
- `OPENALEX_EMAIL`.

### Offline pipeline

- `DATA_ROOT`;
- `PIPELINE_RAW_DIR`;
- `PIPELINE_PROCESSED_DIR`;
- `PIPELINE_INDEX_DIR`;
- `PIPELINE_CITATION_EDGES`;
- `PIPELINE_CITATION_CACHE_DIR`;
- `PIPELINE_CITATION_WEIGHTS`;
- `PIPELINE_CITATION_RECOMPUTE`;
- `PIPELINE_OPENALEX_EN`;
- `PIPELINE_OPENALEX_RU`;
- `PIPELINE_OPENALEX_CHUNK`;
- `PIPELINE_OPENALEX_GZIP`;
- `PIPELINE_OPENALEX_RESUME`;
- `PIPELINE_LOG_LEVEL`.

## Миграции

Compose применяет миграции автоматически через `semantic-migrator`.

Ключевые миграции:

- `1_init` - базовые таблицы;
- `2_add` - расширения схемы;
- `3_ingestion_queue` - очередь ingestion;
- `4_citation_graph` - `citation_edges` и `pending_citation_edges`;
- `5_author_submissions` - author submission workflow.

Ручной запуск мигратора:

```bash
go run tools/migrator/main.go --user=postgres --password=password --host=localhost --port=15432 --dbname=semantic_db --migrations-path=./db/migrations
```

## gRPC API

Proto: `proto/service.proto`.

Основные RPC:

- `SearchPaper(SearchRequest) -> ChatMessage`;
- `AddPaper(AddRequest) -> PaperResponse`;
- пользовательские, чатовые и submission методы, используемые gateway.

### SearchPaper

Вход:

- `Input_data` - текст запроса;
- `Chat_id`;
- `User_id`.

Сервис кодирует запрос E5-моделью, ищет ближайшие документы в FAISS, сохраняет сообщение в историю чата и возвращает `ChatMessage` с найденными публикациями.

### AddPaper

Вход:

- `ID` - опциональный внешний идентификатор;
- `Title`;
- `Abstract`;
- `Year`;
- `Best_oa_location`;
- `Referenced_works`;
- `Related_works`.

Метод валидирует данные, ставит задачу в ingestion queue и возвращает `PaperResponse` со `State=queued:<task_id>`. Неразрешенные ссылки сохраняются в `pending_citation_edges` и могут быть разрешены позже, когда целевая публикация появится в базе.

## Данные и артефакты

Ожидаемая структура `data/index` для weighted runtime:

- `faiss_both.index` - FAISS index;
- `faiss_both.index.meta.json` - metadata: тип индекса, weights, id mode, paths;
- `doc_emb_both.f16.memmap` - базовые эмбеддинги;
- `doc_ids_both.npy` - mapping `row_idx -> paper_id`;
- `citation_cache/` - memmap/arrays для `out1`, `in1`, `out2`, `in2`, degrees и counts.

В runtime source of truth для цитирований - PostgreSQL table `citation_edges`. Parquet edges нужны только для offline-экспериментов.

## OpenAlex pipeline

### 1. Загрузка raw OpenAlex

```powershell
python src/parser/openalex_csv_parser.py `
  --email you@example.com `
  --outdir data/raw `
  --en 1000000 `
  --ru 550000 `
  --chunk-size 50000 `
  --gzip `
  --resume
```

### 2. Очистка

```powershell
python src/parser/clean_openalex.py `
  --indir data/raw `
  --outdir data/processed
```

### 3. Загрузка в БД

```powershell
python src/parser/load_openalex_to_db.py `
  --indir data/processed
```

### 4. Генерация эмбеддингов

```powershell
python src/parser/e5_embed_corpus.py `
  --outdir data/index `
  --model intfloat/multilingual-e5-large
```

### 5. Plain FAISS index

```powershell
python src/parser/e5_build_faiss.py `
  --emb-dir data/index `
  --index-type ivfpq `
  --metric ip `
  --nlist 4096 `
  --m 32 `
  --nbits 8
```

## Weighted runtime

Рекомендуемый production-режим - mutable weighted runtime, где FAISS хранит `paper_id` как external ID, а базовые эмбеддинги остаются в memmap.

Bootstrap:

```powershell
python src/parser/weighted_index_runtime.py bootstrap `
  --emb-dir data/index `
  --memfile doc_emb_both.f16.memmap `
  --doc-ids doc_ids_both.npy `
  --out data/index/faiss_both.index `
  --weights "self=1.0,out1=0.0,in1=0.05,out2=0.03,in2=0.025"
```

После успешного bootstrap включите строгую проверку:

```env
INGESTION_WEIGHTED_RUNTIME_REQUIRED=true
```

Repair или смена весов:

```powershell
python src/parser/weighted_index_runtime.py repair `
  --index data/index/faiss_both.index `
  --weights "self=1.0,out1=0.1,in1=0.07,out2=0.02,in2=0.01"
```

После `repair` нужен restart semantic-service.

## Pipeline worker

Одноразовый запуск полного pipeline:

```powershell
python scripts/run_pipeline.py --mode once
```

Долгоживущий worker:

```powershell
python scripts/run_pipeline.py --mode serve
```

В compose `pipeline-worker` запускается в режиме `serve`. По умолчанию trigger signal - `SIGUSR1` (`10`).

## Тестирование и отладка

Синтаксическая проверка:

```powershell
python -m compileall src cmd tests
```

Юнит-тесты:

```powershell
pytest
```

Точечные проверки:

```powershell
pytest tests/test_citation_math.py
pytest tests/test_grpc_auth.py
pytest tests/test_submission_service.py
```

Healthcheck:

```powershell
python scripts/healthcheck.py
```

Быстрая offline-проверка поиска:

```powershell
python src/parser/e5_test_search.py
```

Benchmark:

```powershell
python scripts/bench.py
```

## Ограничения

- weighted runtime поддерживает `insert` и `update`, но не полноценный `delete`;
- IVF/PQ index не retrain-ится на каждом обновлении;
- смена weights требует `repair` или нового `bootstrap`;
- если weighted runtime помечен dirty после ошибки обновления индекса, новые weighted writes блокируются до восстановления;
- локальные скрипты против Docker PostgreSQL обычно требуют `DB_HOST=localhost` и `DB_PORT=15432`;
- загрузка модели E5 может потребовать заранее подготовленный Hugging Face cache в окружениях без интернета.
