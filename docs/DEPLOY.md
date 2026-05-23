# Despliegue — Casa y Soluciones Backend (borrador i1)

Guía operativa para despliegue parcial de **iteración 1**: auth, usuarios, inmuebles POT, inventario inicial, creación de tickets, API legada y carga Excel.

## Checklist pre-despliegue

- [ ] Python 3.12+ y dependencias instaladas (`pip install -r requirements.txt`)
- [ ] Migraciones aplicadas (`python manage.py migrate`)
- [ ] Superusuario ADMIN creado (`python create_first_superuser.py`)
- [ ] Roles base configurados si aplica (`python setup_roles.py`)
- [ ] Variables de entorno definidas (ver tabla abajo)
- [ ] `DEBUG=False` en producción
- [ ] `ALLOWED_HOSTS` con dominios reales
- [ ] Correo SMTP configurado para credenciales y notificaciones
- [ ] Almacenamiento R2/S3 configurado o `media/` local con respaldo
- [ ] CORS restringido al dominio del frontend (no dejar `CORS_ALLOW_ALL_ORIGINS` en prod)
- [ ] Servidor WSGI (gunicorn) detrás de proxy HTTPS
- [ ] Schema OpenAPI i1 accesible: `/api/v1/schema/`, Swagger `/api/v1/schema/swagger/`
- [ ] Carga inicial Excel probada en staging (`POST /api/v1/admin/import/excel/`)

## Variables de entorno

| Variable | Obligatoria | Descripción | Ejemplo |
|----------|-------------|-------------|---------|
| `DEBUG` | Sí | Modo depuración | `False` |
| `ALLOWED_HOSTS` | Sí | Hosts permitidos (coma) | `api.casasysoluciones.com` |
| `SECRET_KEY` | Sí (prod) | Clave Django | *(generar valor seguro)* |
| `LOGIN_ATTEMPT_LIMIT` | No | Intentos antes de bloqueo | `5` |
| `LOGIN_COOLDOWN` | No | Segundos de bloqueo | `900` |
| `SESSION_COOKIE_AGE` | No | Duración sesión HTML POT | `3600` |
| `SESSION_COOKIE_SECURE` | Prod | Cookie solo HTTPS | `True` |
| `EMAIL_BACKEND` | Sí (prod) | Backend correo | `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST` | Prod | Servidor SMTP | `smtp.example.com` |
| `EMAIL_PORT` | No | Puerto SMTP | `587` |
| `EMAIL_USE_TLS` | No | TLS SMTP | `True` |
| `EMAIL_HOST_USER` | Prod | Usuario SMTP | |
| `EMAIL_HOST_PASSWORD` | Prod | Contraseña SMTP | |
| `DEFAULT_FROM_EMAIL` | Sí | Remitente | `noreply@casasysoluciones.com` |
| `EMAIL_FAIL_SILENTLY` | No | No fallar en silencio | `False` |
| `POT_PUBLIC_BASE_URL` | Recomendada | URL base enlaces en emails | `https://app.example.com` |
| `AWS_ACCESS_KEY_ID` | R2/S3 | Credencial almacenamiento | |
| `AWS_SECRET_ACCESS_KEY` | R2/S3 | Credencial almacenamiento | |
| `AWS_STORAGE_BUCKET_NAME` | R2/S3 | Bucket | |
| `AWS_S3_ENDPOINT_URL` | R2 | Endpoint R2 | |
| `AWS_S3_CUSTOM_DOMAIN` | No | CDN dominio público | |

Sin bucket configurado, los archivos se guardan en `media/` local (`MEDIA_ROOT`).

## Endpoints de referencia (i1)

| Recurso | Ruta |
|---------|------|
| OpenAPI JSON | `GET /api/v1/schema/` |
| Swagger UI | `GET /api/v1/schema/swagger/` |
| ReDoc | `GET /api/v1/schema/redoc/` |
| API legada catálogo | `GET /api/v1/legacy/inmuebles/` |
| Compat. legado (temporal) | `GET /api/v1/inmuebles/` |
| Import Excel (ADMIN) | `POST /api/v1/admin/import/excel/` |
| Auth JWT (legado clientes) | `POST /api/v1/token/` |

## Importación Excel inicial

Solo rol **ADMIN**. Formato `.xlsx`, primera hoja, fila 1 = encabezados.

**Columnas obligatorias:** `direccion`, `propietario`

**Opcionales:** `tipo`, `ciudad`, `edificio`, `unidad`, `estado`, `email`, `documento`, `tipo_documento`, `nombre`, `apellido`, `telefono`

```bash
curl -X POST "https://api.example.com/api/v1/admin/import/excel/?send_credentials=false" \
  -H "Authorization: Bearer <token_admin>" \
  -F "file=@carga_inicial.xlsx"
```

Query params:

- `send_credentials=true` — envía correo con contraseña temporal a arrendatarios nuevos
- `dry_run=true` — valida sin guardar

Respuesta `200` si todo OK; `207` si hubo errores por fila (detalle en `errors[]`).

## Coexistencia POT + API

- Vistas HTML POT en `/` (login, dashboards) **no se desactivan**.
- Nueva API en `/api/v1/` es **aditiva**.
- Dos modelos de inmueble: `api.Inmueble` (legado público) y `pot.Property` (gestión arriendos).

## Comandos útiles

```bash
python manage.py check --deploy
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn core.wsgi:application --bind 0.0.0.0:8000
```

## Alcance iteración 2 (no incluido en este despliegue)

Gestión avanzada de tickets, reportes, cierre automático, rate limiting login y schema OpenAPI completo.
