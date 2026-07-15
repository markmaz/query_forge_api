FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/requirements.txt requirements/requirements.txt

RUN python -m pip install --upgrade pip \
    && pip install -r requirements/requirements.txt

COPY . .

EXPOSE 8000 8001

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
