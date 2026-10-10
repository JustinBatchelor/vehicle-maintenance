FROM docker.io/library/python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /opt/app
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock
COPY config ./config
COPY garage ./garage
COPY templates ./templates
COPY static ./static
COPY data ./data
COPY manage.py ./
RUN python manage.py collectstatic --noinput && chmod -R a=rX /opt/app
USER 1001
EXPOSE 8080
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "60", "--access-logfile", "-", "--access-logformat", "%(h)s %(m)s %(U)s %(s)s %(L)s", "--error-logfile", "-", "--worker-tmp-dir", "/tmp"]
