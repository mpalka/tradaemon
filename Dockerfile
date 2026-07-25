FROM python:3.12-slim

# libgomp1: OpenMP runtime required by LightGBM wheels on Linux
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY config ./config
COPY scripts ./scripts

CMD ["python", "-m", "trademon.engine"]
