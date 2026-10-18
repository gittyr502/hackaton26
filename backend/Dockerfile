FROM python:3.12-slim

# Optional, for networks that intercept HTTPS: --build-arg PIP_EXTRA_ARGS="--trusted-host pypi.org --trusted-host files.pythonhosted.org"
ARG PIP_EXTRA_ARGS=""

WORKDIR /app/backend
COPY requirements.txt .
RUN pip install --no-cache-dir $PIP_EXTRA_ARGS -r requirements.txt

COPY . .
ENV DATA_DIR=/app/data \
    CONFIG_DIR=/app/config \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
