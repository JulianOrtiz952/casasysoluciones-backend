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

### Gestión de inmuebles (HU-02, RF-06, RF-07)

Personal operativo (`ADMIN` o `ASSISTANT`). Lógica en `pot/services/property_service.py`.

| RF | Método | Ruta |
|----|--------|------|
| RF-06 | `POST` | `/api/v1/properties/` — dirección única; `code` autogenerado (`PRO-xxxxx`); estado inicial `AVAILABLE` |
| RF-07 | `GET` | `/api/v1/properties/{id}/history/` — historial cronológico (tickets, inventarios, arrendatarios) |

Adicionales:

- `GET /api/v1/properties/` — listado paginado (`status`, `type`, `city`, `search`)
- `GET /api/v1/properties/{id}/` — detalle con arrendatario activo
- `PATCH /api/v1/properties/{id}/` — actualizar datos y estado (registra evento si cambia estado)
- `GET /api/v1/properties/stats/` — conteos por estado y tipo

Filtros de historial: `date_from`, `date_to`, `event_type`, `tenant_id`.

### Inventario inicial (HU-03 / HU-04, RF-08 a RF-12)

Personal operativo crea y edita; arrendatario firma u observa. Lógica en `pot/services/inventory_service.py` y `pot/services/signature_service.py`.

| RF | Método | Ruta |
|----|--------|------|
| RF-08 | `POST` | `/api/v1/inventories/` — `type=INITIAL`, estado `IN_PROGRESS`; requiere inmueble y arrendatario asociado activo |
| RF-09 | `POST` | `/api/v1/inventories/{id}/spaces/` — agregar espacio dinámico |
| RF-09 | `DELETE` | `/api/v1/inventories/{id}/spaces/{space_id}/` |
| RF-09 | `GET` | `/api/v1/inventories/space-templates/?property_type=` — plantilla sugerida por tipo de inmueble |
| RF-10 | `POST` | `/api/v1/inventories/{id}/spaces/{space_id}/photos/` — JPG/PNG ≤ 5 MB |
| RF-11 | `POST` | `/api/v1/inventories/{id}/sign/` — firma del arrendatario (inventario `PENDING_SIGNATURE`) |
| RF-11 alt | `POST` | `/api/v1/inventories/{id}/observations/` — observaciones del arrendatario |
| RF-12 | `GET` | `/api/v1/inventories/{id}/pdf/` — PDF con espacios y fotos; registro en historial del inmueble |

Wizard y flujo staff:

- `PATCH /api/v1/inventories/{id}/step/1/` — fecha de entrega y observaciones generales
- `PUT /api/v1/inventories/{id}/step/2/spaces/` — reemplazo masivo de espacios
- `POST /api/v1/inventories/{id}/save-draft/`
- `POST /api/v1/inventories/{id}/finalize/` → `PENDING_SIGNATURE` (notifica al arrendatario)
- `POST /api/v1/inventories/{id}/resolve-observations/` — solo `ADMIN`; vuelve a `PENDING_SIGNATURE`

Arrendatario:

- `GET /api/v1/inventories/mine/` — inventarios pendientes de firma
- `GET /api/v1/inventories/{id}/` — detalle del propio inventario

Listado staff: `GET /api/v1/inventories/` con filtros `type`, `status`, `property_id`, `tenant_id`.

Condición de espacio: `GOOD`, `REGULAR`, `BAD`.

## Módulo creación de tickets — HU-05 (RF-13 a RF-17)

Solo arrendatarios (`TENANT`). Radicado autogenerado `TK-xxxxx`.

| RF | Método | Endpoint | Notas |
|----|--------|----------|-------|
| RF-13 | `POST` | `/api/v1/tickets/mine/` | Estado `OPEN`; notifica admin + assistant por email |
| RF-13 | `POST` | `/api/v1/tickets/mine/draft/` | Estado `DRAFT`; sin notificación |
| RF-14 | body | `property_id` | Obligatorio si >1 inmueble activo; auto si solo uno |
| RF-15 | body | `damage_type`, `damage_type_other` | Catálogo; `OTHER` exige texto (mín. 3 caracteres) |
| RF-16 | body | `priority` | `LOW`, `MEDIUM`, `HIGH` obligatorio |
| RF-17 | `POST` | `/api/v1/tickets/mine/{id}/attachments/` | Máx. 5 imágenes JPG/PNG ≤5 MB |

Consulta arrendatario:

- `GET /api/v1/tickets/mine/` — listado paginado (filtro opcional `status`)
- `GET /api/v1/tickets/mine/{id}/` — detalle con adjuntos

Body create (ejemplo):

```json
{
  "property_id": 1,
  "description": "Fuga en lavamanos",
  "damage_type": "PLUMBING",
  "priority": "HIGH"
}
```

## Nota de alcance

Gestión de tickets (estados, asignación, chat) queda para iteración 2.
