# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Accept commit hash from Coolify
ARG SOURCE_COMMIT
ENV SOURCE_COMMIT=$SOURCE_COMMIT

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

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Bake the current git commit hash into the image at build time
RUN python scripts/write_version.py || echo "warning: could not write commit_hash.txt"

# Create a volume for persistent data
# The bot stores data in ~/.hermes which is /root/.hermes in this container
RUN mkdir -p /root/.hermes && chmod 700 /root/.hermes

# Expose the bridge port (if needed for external access, though run_both uses localhost)
EXPOSE 3000
EXPOSE 8080

# Run the bot
CMD ["python", "scripts/run_both.py"]
