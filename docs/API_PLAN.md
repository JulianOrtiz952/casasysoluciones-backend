# API Plan — Iteración 1 (Base)

Este documento describe la base aditiva de `api/v1` implementada en backend, sin reemplazar rutas existentes de `pot/` ni del API legado.

## Principios aplicados

- La capa nueva vive en `api/v1/`.
- El legado sigue activo en:
  - `/api/v1/legacy/...`
  - `/api/v1/...` (compatibilidad temporal para clientes actuales).
- Se reutiliza lógica de autenticación de `pot/services/auth_service.py`.

## Endpoints base implementados

### Auth (RF-01 base)

- `POST /api/v1/auth/login/`
  - Acepta `email` o `document_number`.
  - Mantiene bloqueo por intentos fallidos (`LOGIN_ATTEMPT_LIMIT`, `LOGIN_COOLDOWN`) usando `auth_service`.
- `POST /api/v1/auth/refresh/`
- `POST /api/v1/auth/logout/`
- `GET /api/v1/auth/me/`
- `POST /api/v1/auth/reset/`
- `POST /api/v1/auth/reset/confirm/`
- `POST /api/v1/auth/first-change/`

### Catálogos

- `GET /api/v1/catalogs/`
  - Incluye roles, tipos de documento, catálogos de inmueble e inventario.
  - Incluye enums planeados para tickets (damage_type, priority, status y transiciones).

## RBAC base

- `IsAdmin`, `IsStaffOperative`, `IsTenant`, `IsStaffOperativeOrReadOnly` en `api/v1/permissions.py`.
- Endpoints `me`, `logout` y `first-change` requieren autenticación.

## Migraciones incluidas (i1-base)

Extensiones sobre `pot`:

- `CustomUser`
  - `public_code`
  - `document_type`
  - `document_number`
  - `avatar`
- `Property`
  - `city`
  - `building_name`
  - `unit_label`
  - `cover_image`

Se incluye `RunPython` para poblar `public_code` en usuarios existentes.

## Infraestructura API transversal

- Handler unificado de errores (`api.v1.exceptions.api_exception_handler`).
- Paginación estándar (`api.v1.pagination.StandardResultsSetPagination`).
- Inclusión de `token_blacklist` para invalidación de refresh tokens.

### Gestión de usuarios (HU-01, RF-02 a RF-05)

Solo rol `ADMIN`. Lógica en `pot/services/user_service.py`.

| RF | Método | Ruta |
|----|--------|------|
| RF-02 | `POST` | `/api/v1/users/` — crea arrendatario, asocia inmuebles, envía contraseña temporal por correo |
| RF-03 | `PATCH` | `/api/v1/users/{id}/role/` — cambio de rol; `confirm: true` si hay tickets abiertos |
| RF-04 | `POST` | `/api/v1/tenants/{id}/properties/` — asociar inmueble (bloquea doble arrendatario activo) |
| RF-05 | `POST` | `/api/v1/users/{id}/deactivate/` — desactiva sin borrar; desvincula inmuebles |

Adicionales:

- `GET /api/v1/users/` — listado paginado (`role`, `active`, `search`)
- `GET /api/v1/users/{id}/` — detalle con asociaciones y auditoría reciente
- `PATCH /api/v1/users/{id}/` — actualizar perfil (nombre, teléfono, documento)
- `GET /api/v1/users/stats/` — conteos por rol y estado
- `GET /api/v1/tenants/` — listado de arrendatarios
- `DELETE /api/v1/tenants/{id}/properties/{property_id}/` — desasociar inmueble

## Nota de alcance

Los módulos de inmuebles, inventarios y tickets de negocio quedan para iteraciones posteriores según el plan.
