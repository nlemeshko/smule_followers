# ---------- build stage (optional, тут просто ставим зависимости) ----------
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Kyiv

# Системные зависимости (CA для TLS и tzdata)
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && update-ca-certificates

# Создаём непривилегированного пользователя
ARG UID=10001
ARG GID=10001
RUN groupadd -g ${GID} app && useradd -m -u ${UID} -g ${GID} app

# Рабочая директория
WORKDIR /app

# Сначала зависимости (лучше кэшируется)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY smule_bot.py ./

# Права
RUN chown -R app:app /app
USER app

# Запуск
CMD ["tail", "-f"]
