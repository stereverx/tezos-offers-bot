# syntax=docker/dockerfile:1

# Multi-arch: the target may be arm64 (Oracle's free A1 shape is Ampere) or
# amd64 (GCP e2-micro, AWS Lightsail). Buildx picks the right base image for
# whichever platform the build is running on.
FROM --platform=$TARGETPLATFORM python:3.12-slim

# Keep the image small and avoid writing bytecode into the layer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so code edits do not invalidate the install layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

# Run unprivileged. The bot only needs outbound network, never root.
RUN useradd --create-home --uid 1000 botuser \
    && chown -R botuser:botuser /app
USER botuser

CMD ["python", "-m", "bot.main"]
