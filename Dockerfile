FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000
ENV APP_ENV=production

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY web ./web
# data/ costuma estar vazia ou só no .gitignore — criar no image para tokens/calendar em runtime
RUN mkdir -p /app/data
COPY run.py ./run.py

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
