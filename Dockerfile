FROM python:3.12-slim

# libgomp1: OpenMP runtime required by LightGBM wheels on Linux
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# README.md and LICENSE are build inputs, not documentation, because pyproject.toml
# names them in `readme` and `license-files`: hatchling validates both while
# generating metadata and fails the build outright if either is missing. They sit
# beside pyproject.toml rather than later, where they would be too late to help.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY config ./config
COPY scripts ./scripts

CMD ["python", "-m", "tradaemon.engine"]
