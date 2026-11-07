# One image, three roles (P1-04): api (default CMD), worker (compose command), db is postgres.
# Base pinned tag@digest (P1-03); the index digest covers linux/amd64 and linux/arm64.
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# uv installs exactly what uv.lock says (runtime deps only)
RUN pip install --no-cache-dir uv==0.13.7

WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

COPY app ./app
COPY config ./config

RUN useradd --system --uid 10001 --no-create-home appuser
USER appuser

EXPOSE 8080
CMD ["python", "-m", "app.api"]
