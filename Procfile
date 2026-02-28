web: python manage.py migrate && python create_first_superuser.py && python setup_roles.py && gunicorn core.wsgi:application --bind 0.0.0.0:8000
