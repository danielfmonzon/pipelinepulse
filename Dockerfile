# PipelinePulse — slim, reproducible image. No secrets are baked in.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# App code + config + demo fixture (so the dry-run demo works out of the box).
COPY config.yaml ./
COPY tests/fixtures ./tests/fixtures

# Default to the safe, credential-free demo. Override `command` for real runs.
ENTRYPOINT ["pipelinepulse"]
CMD ["--dry-run", "--use-mock-data"]
