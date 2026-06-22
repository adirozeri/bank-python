# Slim official image; matches the project's Python 3.12.
FROM python:3.12-slim

# Predictable, container-friendly Python behavior:
#   - no .pyc files written
#   - stdout/stderr unbuffered so logs show up immediately (important in k8s)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies in their own cached layer: only re-runs when
# requirements.txt changes, not on every source edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application source.
COPY . .

# Run as a non-root user (least privilege; the app needs no root access).
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# The app listens on 8000.
EXPOSE 8000

# --host 0.0.0.0 is REQUIRED: it binds all interfaces so the container accepts
# connections from outside itself. The uvicorn default 127.0.0.1 would only be
# reachable from within the container, making the service unusable in k8s.
# Module path is app.main:app (the FastAPI app lives in the `app` package),
# not main:app.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
