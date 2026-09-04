from pathlib import Path
import os
import sys
import dj_database_url
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

# -----------------------------------------------------------------------------
# FASE A & 2: AMBIENTE (APP_ENV) - FAIL-CLOSED STRICT
# -----------------------------------------------------------------------------
APP_ENV = os.getenv('APP_ENV', '').lower().strip()

if not APP_ENV:
    raise RuntimeError(
        "SECURITY ERROR: APP_ENV environment variable is missing or empty. "
        "Must be explicitly set to 'development' or 'production'."
    )

if APP_ENV not in ('development', 'production'):
    raise RuntimeError(
        f"SECURITY ERROR: APP_ENV has invalid value '{APP_ENV}'. "
        "Allowed values are strictly 'development' or 'production'."
    )

IS_DEV = APP_ENV == 'development'
IS_PRODUCTION = APP_ENV == 'production'

# -----------------------------------------------------------------------------
# FASE F & 3: DEBUG & PARSING SEGURO DE BOOLEANOS
# -----------------------------------------------------------------------------
raw_debug = os.getenv('DEBUG', '').lower().strip()

if IS_DEV:
    DEBUG = raw_debug in ('true', '1', 'yes') if raw_debug else True
else:
    DEBUG = raw_debug in ('true', '1', 'yes')

if IS_PRODUCTION and DEBUG:
    raise RuntimeError(
        "SECURITY ERROR: DEBUG cannot be True when APP_ENV=production. "
        "Set DEBUG=False in production environment."
    )

# -----------------------------------------------------------------------------
# FASE E & 4: SECRET_KEY & GUARDARRAÍLES
# -----------------------------------------------------------------------------
DEV_DEFAULT_SECRET = 'django-insecure-dev-only-local-casasysoluciones-key-change-in-prod'
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY') or os.getenv('SECRET_KEY')

if IS_PRODUCTION:
    if not SECRET_KEY:
        raise RuntimeError(
            "SECURITY ERROR: Production environment (APP_ENV=production) requires DJANGO_SECRET_KEY "
            "to be explicitly set via environment variables."
        )
    if SECRET_KEY == DEV_DEFAULT_SECRET or 'insecure' in SECRET_KEY.lower():
        raise RuntimeError(
            "SECURITY ERROR: Production environment (APP_ENV=production) cannot use a development "
            "or insecure SECRET_KEY."
        )
else:
    if not SECRET_KEY:
        SECRET_KEY = DEV_DEFAULT_SECRET

# -----------------------------------------------------------------------------
# FASE G & 9 & 10 & 11: ALLOWED_HOSTS, CORS & CSRF (PARSING SEGURO)
# -----------------------------------------------------------------------------
raw_hosts = os.getenv('ALLOWED_HOSTS', '')
parsed_hosts = [h.strip() for h in raw_hosts.split(',') if h.strip()]

if IS_DEV:
    ALLOWED_HOSTS = parsed_hosts if parsed_hosts else ['localhost', '127.0.0.1', '0.0.0.0', '[::1]']
    raw_cors = os.getenv('CORS_ALLOWED_ORIGINS', '')
    CORS_ALLOWED_ORIGINS = [o.strip() for o in raw_cors.split(',') if o.strip()] if raw_cors else ['http://localhost:3000', 'http://127.0.0.1:3000']
    raw_csrf = os.getenv('CSRF_TRUSTED_ORIGINS', '')
    CSRF_TRUSTED_ORIGINS = [t.strip() for t in raw_csrf.split(',') if t.strip()] if raw_csrf else ['http://localhost:3000', 'http://127.0.0.1:3000']
    CORS_ALLOW_ALL_ORIGINS = False
else:
    if not parsed_hosts:
        raise RuntimeError(
            "SECURITY ERROR: Production environment (APP_ENV=production) requires explicit ALLOWED_HOSTS."
        )
    if '*' in parsed_hosts:
        raise RuntimeError(
            "SECURITY ERROR: ALLOWED_HOSTS cannot contain wildcard '*' in production."
        )
    ALLOWED_HOSTS = parsed_hosts
    
    raw_cors = os.getenv('CORS_ALLOWED_ORIGINS', '')
    CORS_ALLOWED_ORIGINS = [o.strip() for o in raw_cors.split(',') if o.strip()]
    if not CORS_ALLOWED_ORIGINS:
        raise RuntimeError(
            "SECURITY ERROR: Production environment (APP_ENV=production) requires explicit CORS_ALLOWED_ORIGINS."
        )
        
    raw_csrf = os.getenv('CSRF_TRUSTED_ORIGINS', '')
    CSRF_TRUSTED_ORIGINS = [t.strip() for t in raw_csrf.split(',') if t.strip()]
    if not CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS = list(CORS_ALLOWED_ORIGINS)
        
    CORS_ALLOW_ALL_ORIGINS = False


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'drf_spectacular',
    'corsheaders',
    'storages',
    'pot',
    'api',
    'rest_framework_simplejwt.token_blacklist',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'pot.middleware.ForcePasswordChangeMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


def _is_linux_mountpoint(target_path: str) -> bool:
    """
    Verifica si target_path es un punto de montaje real leyendo
    /proc/self/mountinfo.

    Fail-closed:
    si no puede comprobarse de forma fiable, devuelve False.
    """
    target = os.path.abspath(target_path)
    mountinfo = Path("/proc/self/mountinfo")

    if not mountinfo.is_file():
        return False

    try:
        with mountinfo.open("r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()

                if len(parts) >= 5 and parts[4] == target:
                    return True

    except (OSError, UnicodeError):
        return False

    return False


# -----------------------------------------------------------------------------
# FASE C & 2 & 3 & 4 & 5: BASE DE DATOS (DB_ENGINE & GUARDARRAÍLES FAIL-CLOSED)
# -----------------------------------------------------------------------------
DB_ENGINE = os.getenv("DB_ENGINE", "").lower().strip()

if not DB_ENGINE:
    raise RuntimeError(
        "SECURITY ERROR: DB_ENGINE environment variable is missing or empty. "
        "Must be explicitly set to 'sqlite' or 'postgresql'."
    )

if DB_ENGINE not in ('sqlite', 'postgresql'):
    raise RuntimeError(
        f"SECURITY ERROR: DB_ENGINE has invalid value '{DB_ENGINE}'. "
        "Allowed values are strictly 'sqlite' or 'postgresql'."
    )

if IS_DEV:
    # En desarrollo: Forzar rígidamente SQLite local en backend/data/db_dev.sqlite3
    DB_DIR = BASE_DIR / 'data'
    DB_DIR.mkdir(exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DB_DIR / "db_dev.sqlite3",
            "OPTIONS": {
                "timeout": 20,
            }
        }
    }
else:
    if DB_ENGINE == 'sqlite':
        sqlite_path_str = os.getenv("SQLITE_DB_PATH", "").strip()
        if not sqlite_path_str:
            raise RuntimeError(
                "SECURITY ERROR: Production SQLite requires SQLITE_DB_PATH environment variable to be set."
            )
        raw_sqlite_path = Path(sqlite_path_str)
        if not raw_sqlite_path.is_absolute():
            raise RuntimeError(
                f"SECURITY ERROR: Production SQLITE_DB_PATH must be an absolute path (got '{sqlite_path_str}')."
            )
        
        # Guardarraíl 1: Verificar que /app/data sea un punto de montaje persistente real (/proc/self/mountinfo)
        if not _is_linux_mountpoint("/app/data"):
            raise RuntimeError(
                "SECURITY ERROR: Production SQLite requires /app/data to be a persistent mount. "
                "The bind mount from host to /app/data is missing or not mounted."
            )
        
        expected_sqlite_path = Path("/app/data/db.sqlite3").resolve()
        resolved_sqlite_path = raw_sqlite_path.resolve()
        
        # Guardarraíl 2: Verificar la ruta exacta /app/data/db.sqlite3
        if resolved_sqlite_path != expected_sqlite_path:
            raise RuntimeError(
                f"SECURITY ERROR: Production SQLITE_DB_PATH must resolve exactly to '/app/data/db.sqlite3'. "
                f"Invalid or untrusted database path specified (got '{sqlite_path_str}' which resolves to '{resolved_sqlite_path}')."
            )
        
        # Guardarraíl 3: Verificar que la base de datos real exista y no sea un archivo vacío (0 bytes)
        if not resolved_sqlite_path.is_file() or resolved_sqlite_path.stat().st_size == 0:
            raise RuntimeError(
                "SECURITY ERROR: Production SQLite database file '/app/data/db.sqlite3' does not exist or is empty (0 bytes). "
                "Production environment will not auto-create an empty database."
            )
        
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": resolved_sqlite_path,
                "OPTIONS": {
                    "timeout": 20,
                }
            }
        }
    elif DB_ENGINE == 'postgresql':
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError(
                "SECURITY ERROR: Production PostgreSQL (DB_ENGINE=postgresql) requires DATABASE_URL to be set."
            )
        DATABASES = {
            "default": dj_database_url.parse(database_url, conn_max_age=600)
        }



# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
LANGUAGE_CODE = 'es'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'pot.CustomUser'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'

SESSION_COOKIE_AGE = int(os.environ.get('SESSION_COOKIE_AGE', '3600'))
SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False') == 'True'
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_COOKIE_HTTPONLY = True

LOGIN_ATTEMPT_LIMIT = int(os.environ.get('LOGIN_ATTEMPT_LIMIT', '5'))
LOGIN_COOLDOWN = int(os.environ.get('LOGIN_COOLDOWN', '900'))

EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@localhost')
EMAIL_FAIL_SILENTLY = os.environ.get('EMAIL_FAIL_SILENTLY', 'False') == 'True'
POT_PUBLIC_BASE_URL = os.environ.get('POT_PUBLIC_BASE_URL', '')

STATICFILES_DIRS = [BASE_DIR / 'static']

from datetime import timedelta

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PAGINATION_CLASS': 'api.v1.pagination.StandardResultsSetPagination',
    'PAGE_SIZE': 20,
    'EXCEPTION_HANDLER': 'api.v1.exceptions.api_exception_handler',
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Casa y Soluciones API',
    'DESCRIPTION': 'API REST v1 — iteración 1 (usuarios, inmuebles, inventario inicial, tickets).',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'PREPROCESSING_HOOKS': ['api.v1.schema_hooks.preprocess_filter_i1'],
    'TAGS': [
        {'name': 'Auth', 'description': 'Autenticación RF-01'},
        {'name': 'Users', 'description': 'Gestión de usuarios RF-02 a RF-05'},
        {'name': 'Properties', 'description': 'Inmuebles POT RF-06, RF-07'},
        {'name': 'Inventories', 'description': 'Inventario inicial RF-08 a RF-12'},
        {'name': 'Tickets', 'description': 'Creación de tickets RF-13 a RF-17'},
        {'name': 'Admin', 'description': 'Operaciones administrativas (carga Excel)'},
        {'name': 'Legacy', 'description': 'Catálogo público api.Inmueble (compatibilidad)'},
        {'name': 'Catalogs', 'description': 'Enums y catálogos'},
    ],
    'SCHEMA_PATH_PREFIX': '/api/v1/',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# -----------------------------------------------------------------------------
# FASE B & D & 7: ALMACENAMIENTO (STORAGE & GUARDARRAÍLES FAIL-CLOSED)
# -----------------------------------------------------------------------------
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', '').strip()
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '').strip()
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '').strip()
AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL', '').strip()
AWS_S3_CUSTOM_DOMAIN = os.environ.get('AWS_S3_CUSTOM_DOMAIN', '').strip()

AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': 'max-age=86400',
}
AWS_S3_SIGNATURE_VERSION = 's3v4'
AWS_S3_REGION_NAME = 'auto'
AWS_S3_ADDRESSING_STYLE = 'path'

if IS_DEV:
    # En desarrollo local: NUNCA inicializar R2/S3. SIEMPRE usar FileSystemStorage local.
    if AWS_STORAGE_BUCKET_NAME or AWS_ACCESS_KEY_ID:
        print("[NOTICE DE SEGURIDAD] Variables Cloudflare R2 / AWS encontradas en desarrollo. "
              "Serán ignoradas automáticamente para aislar el entorno local.")

    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'
elif IS_PRODUCTION:
    # En producción: NINGÚN fallback silencioso a disco local. Exigir R2 completo.
    missing_r2_vars = []
    if not AWS_ACCESS_KEY_ID: missing_r2_vars.append("AWS_ACCESS_KEY_ID")
    if not AWS_SECRET_ACCESS_KEY: missing_r2_vars.append("AWS_SECRET_ACCESS_KEY")
    if not AWS_STORAGE_BUCKET_NAME: missing_r2_vars.append("AWS_STORAGE_BUCKET_NAME")
    if not AWS_S3_ENDPOINT_URL: missing_r2_vars.append("AWS_S3_ENDPOINT_URL")
    
    if missing_r2_vars:
        raise RuntimeError(
            f"SECURITY ERROR: Production environment (APP_ENV=production) requires Cloudflare R2 storage variables. "
            f"Missing required variable(s): {', '.join(missing_r2_vars)}."
        )

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

