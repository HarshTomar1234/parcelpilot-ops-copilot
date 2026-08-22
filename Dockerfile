FROM python:3.12-slim

WORKDIR /app

# Runtime dependencies only (api + llm) - dev tools (pytest/ruff/pyright)
# and the evaluation extras (deepeval/mlflow) are not needed to serve
# traffic and are deliberately left out of this image.
COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts
RUN pip install --no-cache-dir -e ".[llm,api]"

COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# The confidential source pack is NEVER copied into this image - see
# .dockerignore and docs/architecture_note.md's deployment section for
# how a prebuilt database reaches a running container instead.

ENV PARCELPILOT_DB_PATH=/app/build/parcelpilot.db
EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
