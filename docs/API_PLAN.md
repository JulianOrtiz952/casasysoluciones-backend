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

## Nota de alcance

Esta iteración implementa la base transversal solicitada (estructura `api/v1`, auth, RBAC, migraciones y catálogos). Los módulos funcionales de usuarios, inmuebles, inventarios y tickets de negocio quedan para iteraciones posteriores según el plan.
