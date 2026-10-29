#!/bin/sh
# web — миграции и gunicorn; иначе выполнить команду как есть (например: docker compose run --rm web python manage.py check).
set -e

case "$1" in
  web)
    # база может подниматься дольше веба — пробуем миграции несколько раз
    n=0
    until python manage.py migrate --noinput; do
      n=$((n + 1))
      [ "$n" -ge 10 ] && echo "База недоступна — проверьте DB_* в .env" && exit 1
      sleep 3
    done
    exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-3}" --timeout 60 --access-logfile - --error-logfile -
    ;;
  *)
    exec "$@"
    ;;
esac
