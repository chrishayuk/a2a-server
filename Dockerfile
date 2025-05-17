# --- builder ----------------------------------------------------------
FROM python:3.11-slim AS builder
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# 1️⃣  copy the whole project *including* src/ and README.md
COPY . .

# 2️⃣  install runtime deps + *your* package            (include dev extras if you like)
RUN pip install --upgrade pip \
    && pip install --no-cache-dir ".[dev]"

# --- runtime image ----------------------------------------------------
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

COPY src src
COPY README.md pyproject.toml agent-production.yaml .

CMD ["a2a-server", "--config", "agent-production.yaml"]
