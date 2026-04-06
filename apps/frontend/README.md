# ALib Frontend

Фронтенд веб‑приложения на Vue 3 для интеллектуального поиска и управления публикациями со входом через SSO, ролями (USER/AUTHOR, MODERATOR, ADMIN), кабинетом автора и очередью модерации. Проект собран на Vite и TypeScript, использует Pinia, Vue Router и Axios.

## Стек

- Vue 3 + TypeScript, Vite 7
- Pinia, Vue Router 4
- Axios
- Vitest + jsdom
- ESLint 9 + Prettier

## Быстрый старт (локально)

1. Требования: Node.js ^20.19.0 или >=22.12.0.
2. Установите зависимости:

```bash
npm install
```

3. Настройте переменные окружения (см. раздел «Переменные окружения») в `.env` или `.env.local`.
4. Запуск в режиме разработки:

```bash
npm run dev
```

Vite поднимется на http://localhost:5173 (по умолчанию).

## Docker (dev/prod)

### Dev

```bash
docker compose --profile dev up --build
```

Dev‑сервер доступен на http://localhost (порт 80).

Полезно знать:

- Изменения в `src/`, `public/`, `index.html` применяются сразу (HMR).
- Изменения в `.env` или `vite.config.ts` требуют перезапуска контейнера.
- Если изменили `package.json`/`package-lock.json`, выполните установку в контейнере:

```bash
docker compose --profile dev run --rm frontend-dev npm install
```

### Prod

```bash
docker compose --profile prod up --build
```

Nginx раздаёт статику на http://localhost (порт 80).

## Скрипты npm

- `dev` — запуск dev‑сервера Vite
- `build` — проверка типов и сборка (`vue-tsc` + `vite build`)
- `preview` — предпросмотр собранного приложения
- `test:unit` — юнит‑тесты (Vitest)
- `type-check` — отдельная проверка типов (vue-tsc)
- `lint` — ESLint с авто‑исправлением
- `format` — Prettier форматирует `src/`

## Архитектура и ключевые файлы

- `src/main.ts` — инициализация приложения, Pinia и Router; установка темы и попытка авто‑аутентификации при старте.
- `src/router/index.ts` — маршруты и глобальные гард‑перехватчики (auth, роли, редиректы).
- `src/stores/` — Pinia‑хранилища (auth/chat/paper/settings/toast).
- `src/api/` — слой API на Axios:
  - `src/api/base/useBaseApi.ts` — клиент для SSO с перехватом 401 → refresh.
  - `src/api/base/useAlibApi.ts` — клиент для ALib API.
  - `src/api/useSSOApi.ts` — методы SSO.
  - `src/api/useAlibApi.ts` — методы чатов, author submissions и moderation.
- `src/views/` — страницы приложения.
- `src/components/` — UI‑компоненты (панели, чат, тосты, диалоги).
- `src/i18n.ts` — простая i18n (en/ru).
- `src/assets/theme.css` — тема и CSS‑переменные.

## Переменные окружения

Файл `.env` в репозитории содержит пример значений для локальной разработки:

```env
VITE_API_BASE_URL=http://localhost:5173
VITE_FRONTEND_BASE_URL=http://localhost:5173
VITE_SSO_CLIENT_ID_URL=https://domain/api
VITE_ALIB_API_URL=http://domain/api
```

Назначение:

- `VITE_FRONTEND_BASE_URL` — базовый URL фронтенда (для redirect URL OAuth).
- `VITE_SSO_CLIENT_ID_URL` — базовый URL SSO‑сервиса.
- `VITE_ALIB_API_URL` — базовый URL ALib API.
- `VITE_API_BASE_URL` — зарезервирован для общего базового URL.

## Сборка и деплой

1. Соберите проект: `npm run build` — результат в `dist/`.
2. Раздавайте как статический сайт (Nginx/Apache/облако).
3. Для продакшна используйте `.env.production` и корректно настройте CORS/куки на бэкенде.

## Submission workflow

- Авторские страницы работают через `/api/submissions`:
  - создание и обновление черновиков;
  - отправка на модерацию;
  - просмотр статусов `draft | pending | approved | rejected`;
  - удаление только `draft` и `rejected`.
- Модераторская панель работает через `/api/moderation/submissions`:
  - загрузка очереди;
  - редактирование staged-данных;
  - комментарий модератора;
  - `approve` / `reject`.
- Источник ролей на клиенте — SSO `/auth/authenticate`.

## Лицензия

Проект распространяется по лицензии Apache 2.0. См. файл `LICENSE`.
