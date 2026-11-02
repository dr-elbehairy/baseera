FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt pyproject.toml README.md ./
COPY baseera ./baseera
COPY apps ./apps
RUN pip install -r requirements.txt && pip install -e .
RUN useradd -m baseera && mkdir -p /app/data && chown -R baseera /app
USER baseera
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://localhost:8000/api/health || exit 1
CMD ["uvicorn", "baseera.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
