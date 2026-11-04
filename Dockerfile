FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --create-home --uid 10001 suraksha && mkdir -p data && chown -R suraksha:suraksha /app
USER suraksha

ENV PORT=8000
EXPOSE 8000

# Single worker only: scheduler, pipeline lock and caches are in-process.
# Lifespan ingests in the background so health checks answer immediately.
CMD python -m suraksha run --host 0.0.0.0 --port ${PORT}
