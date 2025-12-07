FROM python:3.11-slim

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] pillow supabase httpx
RUN chown -R appuser:appuser /app

USER appuser
EXPOSE 8002

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
