# Imagen de despliegue: frontend compilado + API en un solo servicio web.
# La app y la API comparten dirección, así que no hay CORS ni cookies de terceros (Safari las bloquea).
#
#   docker build -t tpv .
#   docker run -p 8000:8000 -e MONGO_URL=... -e DB_NAME=... -e JWT_SECRET=... -e ADMIN_PASSWORD=... tpv

# ---------- 1. Frontend ----------
FROM node:20-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN yarn install --network-timeout 600000
COPY frontend/ ./
# Vacío = la API está en la misma dirección que la app
ENV REACT_APP_BACKEND_URL="" GENERATE_SOURCEMAP=false DISABLE_ESLINT_PLUGIN=true NODE_OPTIONS=--max-old-space-size=4096
RUN yarn build

# ---------- 2. Backend ----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=frontend /app/frontend/build /app/frontend/build
RUN useradd --create-home --uid 10001 app && mkdir -p uploads && chown -R app uploads
USER app

# Valores pensados para un servidor: archivos dentro de MongoDB (sin disco permanente) y cookies SameSite=Lax.
ENV FILE_STORAGE=mongo COOKIE_SAMESITE=lax PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
