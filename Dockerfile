# Сборка из корня репозитория: docker build -f Dockerfile .
FROM python:3.12-slim

WORKDIR /app

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

RUN pip install --no-cache-dir -r /app/backend/requirements.txt

WORKDIR /app/backend
EXPOSE 8000

ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
