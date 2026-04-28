# ELK stack

Данный репозиторий запускает минимальный ELK стек (Elasticsearch + Logstash + Kibana)
для приема логов от сервисов AstraLib через TCP и просмотра в Kibana.

## Что входит

- Elasticsearch 8.17.2 (одиночный узел, security отключен).
- Logstash 8.17.2 (TCP inputs на `5044` и `5050`, вывод в data stream).
- Kibana 8.17.2 (security отключен).

## Требования

- Docker и Docker Compose.
- Внешняя сеть Docker `grpc_network`.

Создание сети (один раз):

```bash
docker network create grpc_network
```

## Быстрый старт

```bash
docker compose up -d
```

Проверка статуса:

```bash
docker compose ps
```

Остановка:

```bash
docker compose down
```

## Порты

- Elasticsearch: `9200` (HTTP), `9300` (transport)
- Logstash: `5044`, `5050` (TCP input), `9600` (monitoring API)
- Kibana: `5601`

## Как отправлять логи

Logstash принимает JSON lines по TCP на `5044` и `5050`.
В pipeline добавляется поле:

- `service = gateway_service`

Вывод идет в data stream:

- type: `logs`
- dataset: `gateway_service`
- namespace: `default`

## Конфигурация

- `docker-compose.yml` — сервисы, лимиты памяти, healthchecks и сеть.
- `logstash.conf` — inputs, filters и output в Elasticsearch.
- `kibana.yml` — отключение security и reporting.

## Полезные URL

- Elasticsearch health: `http://localhost:9200/_cluster/health`
- Kibana status: `http://localhost:5601/status`

