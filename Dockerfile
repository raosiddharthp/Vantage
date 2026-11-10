FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY app/requirements.txt app/requirements.txt
RUN pip install -r app/requirements.txt
COPY app app
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
