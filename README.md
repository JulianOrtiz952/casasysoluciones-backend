El backend de Casas y Soluciones sirve para gestionar inmuebles en arriendo, usuarios y arrendatarios mediante una API.<br>
Centraliza los reportes de daños, la asignación de técnicos y los inventarios de entrega y devolución con fotografías, observaciones y firma digital.

# Casas y Soluciones — Backend

Servicio desarrollado con Django. La interfaz web se encuentra en el [repositorio del frontend](https://github.com/JulianOrtiz952/casasysoluciones-frontend).

## Funcionalidades

- **Catálogo público:** consulta de inmuebles con fotografías, descripción y precio mensual.
- **Gestión de inmuebles:** registro de casas, apartamentos, locales y bodegas; seguimiento de disponibilidad, arriendo y mantenimiento.
- **Usuarios y arrendatarios:** administración de cuentas y asociación de usuarios a propiedades.
- **Tickets:** registro de daños, prioridades, fotografías, asignación de técnicos e historial de atención.
- **Inventarios:** registro inicial y final del estado de los espacios, fotografías, observaciones, firma digital y descarga en PDF.
- **Reportes:** indicadores de propiedades e incidencias y exportación de tickets en CSV.
- **Carga masiva:** importación y exportación de inmuebles y usuarios mediante archivos Excel.
- **Notificaciones:** correos relacionados con cuentas, propiedades, tickets e inventarios.

## Roles

- **Administrador:** gestión general de la plataforma.
- **Asistente administrativo:** apoyo en la operación inmobiliaria.
- **Arrendatario:** consulta de su propiedad, inventarios y solicitudes.
- **Técnico:** atención y seguimiento de los tickets asignados.

## Tecnologías

- Python 3.12, Django 6 y Django REST Framework.
- Autenticación JWT con Simple JWT.
- SQLite local en desarrollo; SQLite persistente o PostgreSQL en producción.
- Almacenamiento local en desarrollo y Cloudflare R2 mediante S3 en producción.
- ReportLab para PDF, openpyxl para Excel y drf-spectacular para OpenAPI.

## Estructura

```text
casasysoluciones-backend/
├── core/              # Configuración de Django y rutas
├── pot/               # Modelos, servicios y lógica inmobiliaria
├── api/               # API REST, incluida la versión 1
├── templates/         # Plantillas web y de correo
├── docs/              # Documentación de API y despliegue
├── manage.py
├── requirements.txt
└── Dockerfile
```

## Requisitos

- Python 3.12, versión utilizada por el Dockerfile.
- Git para clonar el repositorio.
- El frontend en ejecución para utilizar la interfaz web completa.

## Instalación y ejecución local

Los comandos utilizan PowerShell. Si ya clonaste el repositorio, comienza desde su carpeta y omite `git clone` y `cd`.

```powershell
git clone https://github.com/JulianOrtiz952/casasysoluciones-backend.git
cd casasysoluciones-backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Si ya tienes un archivo `.env`, conserva su configuración y revisa que incluya estos valores para desarrollo:

```dotenv
APP_ENV=development
DEBUG=True
DB_ENGINE=sqlite
ALLOWED_HOSTS=localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=http://localhost:3000
CSRF_TRUSTED_ORIGINS=http://localhost:3000
```

`APP_ENV` y `DB_ENGINE` son obligatorios. En desarrollo, la configuración utiliza la base de datos `data/db_dev.sqlite3` y guarda los archivos subidos en `media/`. No se necesitan credenciales de R2 ni una conexión a PostgreSQL para ejecutar el proyecto localmente.

Crea las tablas, registra la cuenta administradora e inicia el servidor:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

El backend estará disponible en [http://localhost:8000](http://localhost:8000). El comando `createsuperuser` crea una cuenta con rol de administrador.

## Correos en desarrollo

Por defecto, Django imprime los correos en la terminal del backend. Para enviarlos mediante SMTP, configura `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` y las variables `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` y `DEFAULT_FROM_EMAIL` en el entorno del backend.

## Comandos útiles

Desde la raíz del repositorio, con el entorno local configurado:

```powershell
.\.venv\Scripts\python.exe manage.py check       # Revisar la configuración de Django
.\.venv\Scripts\python.exe manage.py migrate     # Aplicar migraciones pendientes
.\.venv\Scripts\python.exe manage.py test        # Ejecutar las pruebas descubiertas por Django
```

## Documentación de la API

Con el backend en ejecución, puedes consultar:

- [Swagger UI](http://localhost:8000/api/v1/schema/swagger/).
- [ReDoc](http://localhost:8000/api/v1/schema/redoc/).
- [Esquema OpenAPI](http://localhost:8000/api/v1/schema/).
- [Administración de Django](http://localhost:8000/admin/).

La API se publica bajo `/api/v1/`. Los endpoints protegidos utilizan el encabezado `Authorization: Bearer <token>`.

## Despliegue

El backend incluye un `Dockerfile` con Python 3.12 y Gunicorn. La configuración de producción requiere `APP_ENV=production`, `DEBUG=False`, una clave `DJANGO_SECRET_KEY`, hosts y orígenes permitidos explícitos, y las credenciales de almacenamiento R2.

Para la base de datos, se admite PostgreSQL mediante `DB_ENGINE=postgresql` y `DATABASE_URL`. La opción SQLite exige un volumen persistente montado en `/app/data` y una base de datos existente y no vacía en `/app/data/db.sqlite3`.

La [guía de despliegue del backend](docs/DEPLOY.md) contiene notas de la primera iteración. Para los requisitos actuales de entorno, base de datos y almacenamiento, toma como referencia la configuración de [core/settings.py](core/settings.py) y la plantilla [.env.example](.env.example).
