FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_PATH=/data/medibridge.db

WORKDIR /app

RUN groupadd --system --gid 10001 medibridge \
    && useradd --system --uid 10001 --gid medibridge --home-dir /app medibridge \
    && mkdir -p /data /app/uploads \
    && chown -R medibridge:medibridge /data /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY --chown=medibridge:medibridge backend /app/backend
COPY --chown=medibridge:medibridge frontend /app/frontend
COPY --chown=medibridge:medibridge data /app/data
COPY --chown=medibridge:medibridge release-approvals.example.json /app/release-approvals.example.json
COPY --chown=medibridge:medibridge run.py /app/run.py

USER medibridge
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["python", "run.py"]
