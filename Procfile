web: gunicorn config.wsgi --bind 0.0.0.0:$PORT --access-logfile -
worker: celery -A config worker --loglevel INFO
beat: celery -A config beat --loglevel INFO
