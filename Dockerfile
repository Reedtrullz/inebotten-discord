# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Accept commit hash from Coolify or the local deploy script
ARG SOURCE_COMMIT=""
ARG COMMIT_SHA=""
ENV SOURCE_COMMIT=$SOURCE_COMMIT
ENV COMMIT_SHA=$COMMIT_SHA

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    git \
    curl \
    wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install the reviewed production graph with artifact hashes.
COPY requirements/prod.lock requirements/prod.lock
RUN python -m pip install --require-hashes --no-cache-dir -r requirements/prod.lock

# Create a fixed-UID non-root runtime user and its persistent data directory
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin inebotten
ENV HOME=/home/inebotten
ENV HERMES_HOME=/home/inebotten/.hermes

# Copy the rest of the application code into the container
COPY . .

# Bake the current git commit hash into the image at build time
RUN python scripts/write_version.py --require-full
LABEL org.opencontainers.image.revision=$SOURCE_COMMIT \
      io.inebotten.config-schema="1" \
      io.inebotten.data-schema-min="0" \
      io.inebotten.data-schema-max="1"

# The bot stores data in ~/.hermes, now under the non-root user's home
RUN mkdir -p /home/inebotten/.hermes \
    && chown -R inebotten:inebotten /app /home/inebotten

USER inebotten

# Expose the bridge port (if needed for external access, though run_both uses localhost)
EXPOSE 3000
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "scripts/deployment_health.py"]

# Run the bot
CMD ["python", "scripts/run_both.py"]
