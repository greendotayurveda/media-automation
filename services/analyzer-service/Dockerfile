FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install ffmpeg, ffprobe, and mediainfo
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    mediainfo \
    && rm -rf /var/lib/apt/lists/*

COPY shared /app/shared
COPY services/analyzer-service/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY services/analyzer-service/app /app/app

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8003/health || exit 1

CMD ["python", "app/main.py"]
