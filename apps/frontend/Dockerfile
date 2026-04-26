FROM node:22-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM deps AS dev
COPY . .
EXPOSE 80
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "80"]

FROM deps AS build
ARG VITE_API_BASE_URL=http://localhost
ARG VITE_FRONTEND_BASE_URL=http://localhost
ARG VITE_SSO_CLIENT_ID_URL=https://id.liveisfpv.ru/api
ARG VITE_ALIB_API_URL=http://localhost:8080/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_FRONTEND_BASE_URL=$VITE_FRONTEND_BASE_URL \
    VITE_SSO_CLIENT_ID_URL=$VITE_SSO_CLIENT_ID_URL \
    VITE_ALIB_API_URL=$VITE_ALIB_API_URL
COPY . .
RUN npm run build

FROM nginx:stable-alpine AS prod
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
