FROM node:22-alpine AS build
WORKDIR /site/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html frontend/vite.config.js frontend/docs-plugin.js frontend/styles.css ./
COPY frontend/src ./src
COPY frontend/DESIGN.md ./DESIGN.md
COPY docs /site/docs
COPY README.md /site/README.md
RUN npm run build

FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /site/frontend/dist /usr/share/nginx/html
