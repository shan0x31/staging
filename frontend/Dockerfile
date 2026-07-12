# Build the static frontend, then serve it (and proxy the API) with Caddy.
FROM node:22-slim AS build
WORKDIR /build
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /build/dist /srv/www
COPY Caddyfile /etc/caddy/Caddyfile
