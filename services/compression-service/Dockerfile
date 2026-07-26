FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install curl, ffmpeg, and Intel Quick Sync (VAAPI) hardware drivers
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    intel-media-va-driver-non-free \
    i965-va-driver-shaders \
    libmfx1 \
    libva-drm2 \
    libva2 \
    && rm -rf /var/lib/apt/lists/*

COPY shared /app/shared
COPY services/compression-service/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY services/compression-service/app /app/app

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8005/health || exit 1

CMD ["python", "app/main.py"]
