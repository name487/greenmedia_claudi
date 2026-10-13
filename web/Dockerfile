# Green Media web app (Django, presentation only — talks to the API at API_URL).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DJANGO_DEBUG=0
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput \
 && useradd --create-home app && chown -R app /app
USER app
EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn greenmedia_web.wsgi --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout 120 --access-logfile -"]
