FROM node:22-bookworm AS web-build

WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.10-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8787

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-studio.txt ./
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements-studio.txt

COPY app ./app
COPY src ./src
COPY studio_api ./studio_api
COPY start-api.py ./
COPY --from=web-build /app/web/dist ./web/dist

RUN mkdir -p workspace

EXPOSE 8787

CMD ["python", "start-api.py"]
