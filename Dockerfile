FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ANALYTICS_PORT=8006

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=appuser:appuser app ./app

USER appuser
EXPOSE 8006
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"$ANALYTICS_PORT\""]
