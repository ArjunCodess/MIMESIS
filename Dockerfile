FROM python:3.14-slim AS runtime
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY src ./src
COPY services ./services
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps -e .
COPY configs ./configs
COPY apps/web/dist ./apps/web/dist
COPY apps/web/public/research ./apps/web/public/research
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
