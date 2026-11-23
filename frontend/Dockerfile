# Stage 1: build the single-page app.
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Stage 2: Nginx serves the built files and proxies /api/ to the API container.
FROM nginx:stable-alpine
COPY --from=build /src/dist /usr/share/nginx/html
COPY nginx/mrs-common.conf /etc/nginx/snippets/mrs-common.conf
COPY nginx/https.conf nginx/http.conf /etc/nginx/mrs/
COPY --chmod=0755 nginx/40-select-mode.sh /docker-entrypoint.d/40-select-mode.sh
# Security fixes for the base system published since the base image was built.
RUN apk upgrade --no-cache && rm -f /etc/nginx/conf.d/default.conf
EXPOSE 80 443
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1/nginx-health || exit 1
