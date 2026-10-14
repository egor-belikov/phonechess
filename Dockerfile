# syntax=docker/dockerfile:1.6
# Сборка из корня репозитория: docker build -f Dockerfile .
FROM python:3.12-slim

WORKDIR /app

# Stockfish: official release build (Debian package lags several versions behind).
# "universal" binary picks the best instruction set (sse/avx2/avx512) at runtime, so it runs on any x86-64 VPS.
ARG STOCKFISH_VERSION=sf_19
ARG STOCKFISH_SHA256=9defc0d4e55d49c65a6d042f3e571a39fcea499ade6dbe741b53b8c65e03611f
ADD --checksum=sha256:${STOCKFISH_SHA256} \
    https://github.com/official-stockfish/Stockfish/releases/download/${STOCKFISH_VERSION}/stockfish-linux-x86-64-universal.tar.gz \
    /tmp/stockfish.tar.gz
RUN tar -xzf /tmp/stockfish.tar.gz -C /tmp stockfish/stockfish-linux-x86-64-universal \
    && install -m 0755 /tmp/stockfish/stockfish-linux-x86-64-universal /usr/local/bin/stockfish \
    && rm -rf /tmp/stockfish /tmp/stockfish.tar.gz \
    && echo quit | /usr/local/bin/stockfish | head -n 1
ENV STOCKFISH_PATH=/usr/local/bin/stockfish

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

RUN pip install --no-cache-dir -r /app/backend/requirements.txt

WORKDIR /app/backend
EXPOSE 8000

ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
