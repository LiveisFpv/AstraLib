# AstraLib Frontend

Frontend AstraLib - Vue 3 приложение для поиска научных публикаций, работы с чатами, авторскими материалами, модерацией и администрированием пользователей. Приложение использует внешний SSO для входа, OAuth redirect и получения ролей.

## Стек

- Vue 3, TypeScript, Vite 7;
- Pinia для состояния;
- Vue Router 4;
- Axios для SSO API и ALib Gateway API;
- Vitest + jsdom;
- ESLint 9 + Prettier;
- Nginx для production-раздачи статических файлов.

## Основные возможности

- вход, регистрация, refresh/logout и OAuth через внешний SSO;
- восстановление сессии при старте приложения;
- защищенные маршруты и role-based guards;
- семантический поиск через gateway `/api/chats/{chat_id}/history`;
- история чатов пользователя;
- просмотр публикаций;
- кабинет автора с черновиками, отправкой на модерацию и статусами;
- панель модератора для редактирования staged-данных и approve/reject;
- панель администратора для управления пользователями через SSO;
- локализация `ru/en`;
- настройки темы и UI-состояний через Pinia.

## Быстрый старт

Требования:

- Node.js `^20.19.0` или `>=22.12.0`;
- npm;
- запущенные gateway и SSO API либо корректные внешние URL.

Установка:

```bash
npm install
```

Создайте `.env.local` или используйте переменные окружения:

```env
VITE_API_BASE_URL=http://localhost:5173
VITE_FRONTEND_BASE_URL=http://localhost:5173
VITE_SSO_CLIENT_ID_URL=https://id.example.com/api
VITE_ALIB_API_URL=http://localhost/api
```

Запуск dev server:

```bash
npm run dev
```

По умолчанию Vite доступен на `http://localhost:5173`.

## Docker

### Изолированный frontend compose

Dev-режим:

```bash
docker compose --profile dev up --build
```

Production-режим:

```bash
docker compose --profile prod up --build
```

Оба профиля публикуют приложение на `http://localhost` через порт `80`. Production-профиль также объявляет порт `443`, если он используется в nginx-конфигурации.

### Корневой compose

Из корня репозитория frontend запускается как часть общего стека:

```bash
docker compose --env-file .env up -d --build
```

Для разработки с HMR:

```bash
docker compose --env-file .env --profile dev up --build nginx-dev
```

В корневом production compose переменные `VITE_*` передаются как build args, поэтому после изменения `.env` нужно пересобрать образ frontend.

## Скрипты npm

- `npm run dev` - Vite dev server;
- `npm run build` - type-check и production build;
- `npm run build-only` - только `vite build`;
- `npm run preview` - предпросмотр `dist`;
- `npm run test:unit` - Vitest;
- `npm run type-check` - `vue-tsc --build`;
- `npm run lint` - ESLint с автоисправлением;
- `npm run format` - Prettier для `src/`.

## Переменные окружения

- `VITE_FRONTEND_BASE_URL` - публичный URL frontend. Используется для OAuth redirect URL.
- `VITE_SSO_CLIENT_ID_URL` - базовый URL SSO API, обычно `https://id.example.com/api`.
- `VITE_ALIB_API_URL` - базовый URL gateway API, обычно `/api` за nginx или `http://localhost:8080/api` при прямом локальном запуске gateway.
- `VITE_API_BASE_URL` - общий базовый URL, зарезервирован для совместимости с конфигурацией проекта.

Пример для production за nginx:

```env
VITE_FRONTEND_BASE_URL=https://example.com
VITE_API_BASE_URL=https://example.com
VITE_ALIB_API_URL=/api
VITE_SSO_CLIENT_ID_URL=https://id.example.com/api
```

## Архитектура

- `src/main.ts` - инициализация Vue, Pinia, router, темы и восстановления сессии;
- `src/router/index.ts` - маршруты, auth guard, role guard и redirect logic;
- `src/config.ts` - чтение `VITE_*`;
- `src/api/base/useBaseApi.ts` - Axios-клиент SSO с refresh при `401`;
- `src/api/base/useAlibApi.ts` - Axios-клиент gateway;
- `src/api/useSSOApi.ts` - методы SSO: login, OAuth, profile, admin users;
- `src/api/useAlibApi.ts` - методы gateway: chats, submissions, moderation;
- `src/api/types.ts` - DTO frontend API;
- `src/stores/` - Pinia stores: auth, chat, paper, settings, toast;
- `src/views/` - страницы приложения;
- `src/components/` - общие UI-компоненты;
- `src/assets/theme.css` - CSS-переменные темы;
- `src/i18n.ts` - простая локализация.

## Маршруты

- `/auth` - публичная страница входа;
- `/` - главная страница, требует авторизацию;
- `/search/:uid` - поиск и чат;
- `/paper/:uid` - просмотр публикации;
- `/paper/my` - кабинет автора, роли `AUTHOR`, `MODERATOR`, `ADMIN`;
- `/admin` - панель администратора, роль `ADMIN`;
- `/moderator` - панель модератора, роли `MODERATOR`, `ADMIN`.

`/paper/add` и `/paper/:id/edit` перенаправляют в кабинет автора.

## API-интеграции

### SSO

Frontend вызывает SSO напрямую через `VITE_SSO_CLIENT_ID_URL`:

- `POST /auth/login`;
- `POST /auth/logout`;
- `POST /auth/refresh`;
- `GET /auth/authenticate`;
- `POST /auth/create`;
- `POST /auth/password-reset`;
- `PUT /auth/update`;
- `GET /oauth/{provider}`;
- `GET /auth/admin/users`;
- `PUT /auth/admin/users/{id}`.

### ALib Gateway

Frontend вызывает gateway через `VITE_ALIB_API_URL`:

- `/chats`;
- `/chats/{chat_id}/history`;
- `/submissions`;
- `/submissions/{submission_id}/submit`;
- `/moderation/submissions`;
- `/moderation/submissions/{submission_id}/moderate`.

## Workflow авторских публикаций

Автор может создать черновик, обновить его, отправить на модерацию и отслеживать статусы:

- `draft`;
- `pending`;
- `approved`;
- `rejected`.

Удаление доступно только для `draft` и `rejected`. После approve gateway отправляет данные в semantic-service, где публикация попадает в ingestion queue.

## Проверки

```bash
npm run type-check
npm run test:unit
npm run build
```

При изменении API-контрактов дополнительно проверьте сценарии входа, refresh token, поиск, создание submission и модерацию в браузере.
