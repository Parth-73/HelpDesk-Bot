FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend_src
COPY frontend_src/package*.json ./
RUN npm ci
COPY frontend_src/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY SD_Assessment/SD_Assessment/course_docs/ SD_Assessment/SD_Assessment/course_docs/
RUN python -m backend.app.scripts.prepare_faq_model
COPY --from=frontend /build/frontend_src/dist/ frontend_src/dist/
ENV APP_ENV=production PORT=8000
CMD ["/bin/sh", "-c", "python -m backend.app.init_db && python -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
