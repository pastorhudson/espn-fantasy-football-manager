web: uvicorn config.asgi:application --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'
worker: celery -A config worker --loglevel INFO
beat: celery -A config beat --loglevel INFO
