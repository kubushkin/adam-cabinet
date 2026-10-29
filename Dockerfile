# Образ личного кабинета: Django + gunicorn, статика раздаётся whitenoise (отдельный nginx для теста не нужен).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# статика собирается при сборке образа; ключ здесь временный — настоящий приходит из .env при запуске
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && useradd --system --uid 10001 --home /app cabinet \
    && chmod +x docker/entrypoint.sh

USER cabinet
EXPOSE 8000
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["web"]
