# python FastAPI
FROM python:3.11-slim

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] transformers sentence-transformers httpx
RUN chown -R appuser:appuser /app

USER appuser
EXPOSE 8001

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
