FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd -g 1001 appgroup && useradd -u 1001 -g appgroup -m appuser
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=1001:1001 app ./app
COPY --chown=1001:1001 scripts ./scripts
RUN mkdir -p /app/data /app/papers && chown -R appuser:appgroup /app/data /app/papers
USER 1001:1001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.api.main:app", "--workers", "1", "--host", "0.0.0.0", "--port", "8000"]
