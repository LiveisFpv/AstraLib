# Сервис семантического поиска AstraLib

Сервис индексирует и ищет научные публикации на базе OpenAlex и авторских материалов. Тексты кодируются `intfloat/multilingual-e5-large`, метаданные и граф цитирований хранятся в PostgreSQL, поиск выполняется через FAISS, доступ предоставляется по gRPC.

Ключевые возможности:
- семантический поиск по корпусу статей;
- фоновый ingestion новых работ из `AddPaper` и OpenAlex;
- mutable weighted FAISS runtime с `paper_id` как внешним ID;
- инкрементальный пересчёт citation-aware векторов для затронутых 2-hop соседей;
- хранение базовых эмбеддингов и citation cache в memmap-артефактах.

## Быстрый старт

### Docker Compose

Предусловия:
- Docker Desktop;
- внешняя сеть `grpc_network`, если она нужна другим сервисам:
  ```bash
  docker network create grpc_network
  ```

Минимальные настройки в `.env`:
- `FAISS_INDEX_PATH=data/index/faiss_both.index`
- `FAISS_DOC_IDS_PATH=data/index/doc_ids_both.npy`
- `DB_HOST=postgres`
- `DB_PORT=5432`
- `DB_USER`, `DB_PASSWORD`, `DB_NAME`

Запуск:
```bash
docker compose up -d --build
```

Проверка:
```bash
docker compose logs -f semantic-service
```

Compose поднимает:
- `postgres` с данными сервиса;
- `migrator`, который применяет все миграции из `db/migrations`;
- `semantic-service`;
- `pipeline-worker` для фонового пайплайна.

### Локальный запуск

Требования:
- Python 3.12;
- PostgreSQL 14+;
- установленный FAISS и зависимости из `requirements.txt`.

Установка:
```powershell
python -m venv .venv
. .venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
```

Если база поднята в Docker Compose, для локального запуска обычно нужно переопределить:
```powershell
$env:DB_HOST="localhost"
$env:DB_PORT="15432"
```

Запуск сервиса:
```powershell
python cmd/main.py
```

## Миграции

Ключевые миграции:
- `3_ingestion_queue` — очередь ingestion-задач;
- `4_citation_graph` — таблицы `citation_edges` и `pending_citation_edges`, backfill старых однонаправленных связей.

Если сервис стартует через Compose, миграции применяются автоматически. При локальном запуске их нужно применить вручную или через ваш мигратор.

## Данные и артефакты

Основные артефакты индекса:
- `data/index/faiss_both.index` — FAISS-индекс;
- `data/index/faiss_both.index.meta.json` — meta с типом индекса, `weights`, `id_mode`, путями к артефактам;
- `data/index/doc_emb_both.f16.memmap` — базовые эмбеддинги;
- `data/index/doc_ids_both.npy` — row storage `row_idx -> paper_id`;
- `data/index/citation_cache/*` — `out1/in1/out2/in2` mean memmap и count/degree arrays.

В weighted runtime source of truth для графа цитирований — таблица `citation_edges` в PostgreSQL. Parquet `edges` нужны только для оффлайн-сценариев.

## Ingestion

### Источники

Сервис умеет ingest:
- авторские статьи через `AddPaper` после модерации;
- последние статьи из OpenAlex по расписанию.

### Как работает author ingestion

`AddPaper` больше не является заглушкой. Теперь метод:
- валидирует входные поля;
- ставит задачу в очередь ingestion;
- сразу возвращает `PaperResponse`, где `State=queued:<task_id>`.

Дальше планировщик:
- забирает задачу из очереди;
- пишет статью и связи в PostgreSQL;
- дополняет `citation_edges` или `pending_citation_edges`;
- инкрементально обновляет FAISS.

### OpenAlex top-up

Если включён `INGESTION_OPENALEX_ENABLED=true`, сервис периодически запрашивает последние работы OpenAlex с ограничением по `limit` и языкам, после чего прогоняет их через тот же ingestion pipeline.

### Переменные ingestion

Очередь и планировщик:
- `INGESTION_SCHEDULER_ENABLED`
- `INGESTION_SCHEDULER_POLL_SECONDS`
- `INGESTION_SCHEDULER_MAX_TASKS`
- `INGESTION_TASK_STALE_SECONDS`
- `INGESTION_TASK_RETRY_SECONDS`
- `INGESTION_TASK_MAX_ATTEMPTS`

OpenAlex:
- `INGESTION_OPENALEX_ENABLED`
- `INGESTION_OPENALEX_INTERVAL_SECONDS`
- `INGESTION_OPENALEX_LIMIT`
- `INGESTION_OPENALEX_TIMEOUT_SECONDS`
- `INGESTION_OPENALEX_LANGUAGES`
- `OPENALEX_EMAIL`

Weighted runtime:
- `INGESTION_WEIGHTED_RUNTIME_REQUIRED`

Если `INGESTION_WEIGHTED_RUNTIME_REQUIRED=true`, сервис не стартует с несовместимым или немигрированным weighted runtime.

## Построение индекса

### 1. Генерация эмбеддингов

```powershell
python src/parser/e5_embed_corpus.py `
  --outdir data/index `
  --model intfloat/multilingual-e5-large
```

Результат:
- `doc_embeddings.f16.memmap` или ваш кастомный memmap;
- `*.shape.json`;
- `doc_ids.npy`.

### 2. Обычный FAISS без citation-aware runtime

Если нужен plain индекс без weighted runtime:
```powershell
python src/parser/e5_build_faiss.py `
  --emb-dir data/index `
  --index-type ivfpq `
  --metric ip `
  --nlist 4096 `
  --m 32 `
  --nbits 8
```

В таком режиме сервис продолжит работать в простом append-only индексе без citation-aware пересчёта.

### 3. Bootstrap mutable weighted runtime

Это рекомендуемый режим для production ingestion с `--weights`.

Пример PowerShell:
```powershell
python src/parser/weighted_index_runtime.py bootstrap `
  --emb-dir data/index `
  --memfile doc_emb_both.f16.memmap `
  --doc-ids doc_ids_both.npy `
  --out data/index/faiss_both.index `
  --weights "self=1.0,out1=0.0,in1=0.05,out2=0.03,in2=0.025"
```

Что делает bootstrap:
- при необходимости backfill-ит старые citation relations в `citation_edges`;
- строит citation cache из БД;
- пересобирает FAISS в mutable runtime;
- пишет `id_mode=paper_id` и `weights` в `faiss.index.meta.json`;
- при миграции старого индекса умеет конвертировать legacy `doc_ids.npy` с OpenAlex string IDs в числовые `paper_id`.

После успешного bootstrap рекомендуется включить:
```env
INGESTION_WEIGHTED_RUNTIME_REQUIRED=true
```

и перезапустить сервис.

### 4. Repair / смена весов

Если нужно восстановить runtime или поменять веса:
```powershell
python src/parser/weighted_index_runtime.py repair `
  --index data/index/faiss_both.index `
  --weights "self=1.0,out1=0.1,in1=0.07,out2=0.02,in2=0.01"
```

Важно:
- runtime читает веса из `faiss.index.meta.json`, а не из env;
- после `repair` нужен restart сервиса;
- инкрементальная схема поддерживает `insert + update`, но не delete.

## Citation-aware runtime

В weighted runtime:
- FAISS хранит `paper_id` как внешний ID;
- row storage с базовыми эмбеддингами остаётся в memmap;
- при insert/update статьи сервис пересчитывает только точный affected 2-hop closure по `citation_edges`;
- для affected узлов заново считаются `out1`, `in1`, `out2`, `in2`;
- затем выполняется `remove_ids + add_with_ids` для обновлённых `paper_id`.

Если после DB commit обновление индекса падает, ставится dirty marker. В этом состоянии сервис блокирует новые weighted writes до `repair`.

## Подготовка данных OpenAlex

Ручной пайплайн:

1. Загрузка raw OpenAlex:
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

2. Очистка:
```powershell
python src/parser/clean_openalex.py `
  --indir data/raw `
  --outdir data/processed
```

3. Загрузка в БД:
```powershell
python src/parser/load_openalex_to_db.py `
  --indir data/processed
```

`build_edges.py` по-прежнему полезен для оффлайн-экспериментов с parquet `edges`, но для runtime bootstrap он больше не обязателен: сервис строит citation cache напрямую из PostgreSQL.

## gRPC API

Proto: `proto/service.proto`

Ключевые RPC:
- `SearchPaper(SearchRequest) -> ChatMessage`
- `AddPaper(AddRequest) -> PaperResponse`

### SearchPaper

Ожидает:
- `Input_data`
- `Chat_id`
- `User_id`

Сервис:
- кодирует запрос E5;
- ищет ближайшие статьи в FAISS;
- пишет сообщение в историю чата;
- возвращает `ChatMessage` с `papers`.

### AddPaper

Ожидает:
- `ID` — опциональный идентификатор статьи;
- `Title`, `Abstract`, `Year`, `Best_oa_location`;
- `Referenced_works`, `Related_works`.

Результат:
- статья ставится в ingestion queue;
- в ответе возвращается исходный `PaperResponse`;
- поле `State` содержит `queued:<task_id>`.

Неразрешённые ссылки не теряются: они сохраняются в `pending_citation_edges` и автоматически разрешаются, когда целевая статья появится позже.

## Конфигурация

Основные переменные:
- сервис и логирование: `LOG_LEVEL`, `LOGSTASH_HOST`, `LOGSTASH_PORT`, `SEMANTIC_PORT`
- база: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `SSLMode`
- индекс и модель: `FAISS_INDEX_PATH`, `FAISS_DOC_IDS_PATH`, `EMBEDDING_MODEL_NAME`, `EMBEDDING_BATCH_SIZE`, `EMBEDDING_LORA_PATH`
- ingestion: см. раздел выше
- pipeline: `PIPELINE_OPENALEX_EN`, `PIPELINE_OPENALEX_RU`, `PIPELINE_OPENALEX_CHUNK`

Значения по умолчанию смотрите в:
- `src/config/config.py`
- `src/services/ingestion/settings.py`
- `src/pipeline/settings.py`

## Архитектура

Основные компоненты:
- `cmd/main.py` — точка входа;
- `src/http/grpc/*` — gRPC API;
- `src/services/search/*` — поиск;
- `src/services/ingestion/*` — очередь, scheduler, OpenAlex client, weighted runtime;
- `src/storage/*` — доступ к PostgreSQL;
- `src/parser/*` — оффлайн pipeline и утилиты bootstrap/repair;
- `db/migrations/*` — схема базы и миграции.

## Тестирование и отладка

Полезные команды:

Синтаксическая проверка:
```powershell
python -m compileall src cmd tests
```

Юнит-тесты pure math для citation-aware recompute:
```powershell
pytest tests/test_citation_math.py
```

Healthcheck:
```powershell
python scripts/healthcheck.py
```

Быстрая оффлайн-проверка поиска:
```powershell
python src/parser/e5_test_search.py
```

## Ограничения

- инкрементальный weighted runtime поддерживает `insert + update`, но не `delete`;
- IVF/PQ не retrain-ится на каждом апдейте, для этого нужен оффлайн rebuild/repair;
- смена weights требует `repair` или нового bootstrap;
- если runtime помечен как dirty, новые weighted writes блокируются до восстановления;
- если вы запускаете локальные скрипты против Dockerized Postgres, используйте `DB_HOST=localhost` и `DB_PORT=15432`.
