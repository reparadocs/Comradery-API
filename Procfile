release: python manage.py migrate
web: gunicorn lionhearted.wsgi --preload --workers 1
worker: python manage.py rqworker default 