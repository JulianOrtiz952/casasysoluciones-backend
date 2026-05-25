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

## Despliegue parcial (i1)

| Recurso | Ruta |
|---------|------|
| OpenAPI JSON | `GET /api/v1/schema/` |
| Swagger UI | `GET /api/v1/schema/swagger/` |
| Import Excel (solo ADMIN) | `POST /api/v1/admin/import/excel/` |
| API legada | `GET /api/v1/legacy/inmuebles/` (compat: `/api/v1/inmuebles/`) |

Detalle operativo y checklist de variables: [`docs/DEPLOY.md`](DEPLOY.md).

## Módulo gestión de tickets — HU-06 (RF-18 a RF-21, RF-29 parcial)

Personal operativo (`ADMIN`, `ASSISTANT`). Lógica en `pot/services/ticket_service.py`.

| RF | Método | Ruta | Notas |
|----|--------|------|-------|
| RF-18 | `POST` | `/api/v1/tickets/{id}/status/` | Transiciones validadas; `TicketStatusLog`; cierre forzado con `force_close` + `justification` (mín. 20) |
| RF-19 | `POST` | `/api/v1/tickets/{id}/reject/` | `{reason}` mín. 20 caracteres; email al arrendatario |
| RF-20 | `POST` | `/api/v1/tickets/{id}/assign/` | `{contractor_name}`, `visit_note` opcional → `IN_PROGRESS` |
| RF-21 | `POST` | `/api/v1/tickets/{id}/repair-evidence/` | Foto “después” (staff); fija `confirmation_deadline_at` (+1 día hábil) |
| RF-29 | `GET` | `/api/v1/tickets/stats/` | `pending_resolution`, `traffic_light`, conteos por estado |

Consulta y exportación staff:

- `GET /api/v1/tickets/` — listado (excluye `DRAFT`); filtros: `status`, `priority`, `damage_type`, `property_id`, `tenant_id`, `date_from`, `date_to`, `search`
- `GET /api/v1/tickets/{id}/` — detalle con historial de estados y evidencia reparación
- `GET /api/v1/tickets/export/?format=csv|xlsx` — exportación

Transiciones vía `status` (sin rechazo ni asignación directa):

- `OPEN` → `ACCEPTED`
- `IN_PROGRESS` → `CLOSED` (requiere evidencia reparación o `force_close`)
- Rechazo y asignación maestro: endpoints dedicados

Semáforo (`traffic_light`) sobre tickets `pending_resolution` (abiertos + aceptados sin maestro + en proceso): rojo/amarillo/verde por prioridad; gris si llevan más de 3 días sin actualización.

## Módulo seguimiento de tickets — HU-06 (RF-22, RF-23)

Arrendatario confirma o disputa tras evidencia de reparación. Personal operativo consulta timeline.

| RF | Método | Ruta | Notas |
|----|--------|------|-------|
| RF-22 | `POST` | `/api/v1/tickets/mine/{id}/confirm/` | Cierra ticket; `tenant_confirmed_at`; log `TENANT_CONFIRM` |
| RF-22 alt | `POST` | `/api/v1/tickets/mine/{id}/dispute/` | `{note}` mín. 10 caracteres → `ACCEPTED`; limpia maestro y plazo |
| RF-23 | comando | `python manage.py close_expired_tickets` | Recordatorio ~24 h antes + cierre automático si vence `confirmation_deadline_at` |
| — | `GET` | `/api/v1/tickets/{id}/timeline/` | Historial cronológico (`TicketStatusLog`); solo staff |

Requisitos para confirmar/disputar: estado `IN_PROGRESS`, evidencia reparación adjunta y `confirmation_deadline_at` definido (se fija al subir la primera evidencia — RF-21).

Detalle arrendatario (`GET /api/v1/tickets/mine/{id}/`) incluye `confirmation_deadline_at`, `awaits_tenant_confirmation`, `status_logs` y evidencia.

Job programado (cron): ejecutar `close_expired_tickets` al menos una vez al día hábil.

## Módulo comunicación en tickets — HU-08 (RF-24, RF-25)

Chat dentro del ticket y notificaciones in-app. El email se envía solo en eventos definidos (apertura, rechazo, solicitud de información); los mensajes normales del hilo no generan correo.

| RF | Método | Ruta | Notas |
|----|--------|------|-------|
| RF-24 | `GET` | `/api/v1/tickets/{id}/comments/` | Hilo cronológico (staff) |
| RF-24 | `POST` | `/api/v1/tickets/{id}/comments/` | `{body}`; bloqueado si `CLOSED` |
| RF-24 | `GET` | `/api/v1/tickets/mine/{id}/comments/` | Hilo (arrendatario) |
| RF-24 | `POST` | `/api/v1/tickets/mine/{id}/comments/` | Mensaje `NORMAL`; notifica in-app a staff |
| RF-25 | `POST` | `/api/v1/tickets/{id}/request-info/` | `{message}` min. 10 chars; solo staff; tipo `INFO_REQUEST`; email + notificación alta al arrendatario |
| — | `GET` | `/api/v1/notifications/` | Listado del usuario; `?unread=1` solo no leídas |
| — | `GET` | `/api/v1/notifications/unread-count/` | `{unread_count}` |
| — | `PATCH` | `/api/v1/notifications/{id}/read/` | Marca como leída |

Modelos: `TicketComment` (`message_type`: `NORMAL` | `INFO_REQUEST`), `Notification` (`priority`: `LOW` | `NORMAL` | `HIGH`).

## Módulo inventario final — HU-07 (RF-26 a RF-28)

Solo personal operativo (`ADMIN`, `ASSISTANT`) crea inventario `FINAL`. Lógica en `pot/services/inventory_service.py` y `pot/services/contract_service.py`.

| RF | Método | Ruta | Notas |
|----|--------|------|-------|
| RF-26 | `POST` | `/api/v1/inventories/` | `inventory_type=FINAL`; requiere inventario `INITIAL` en `ACCEPTED`; precarga espacios del inicial; crea/vincula `LeaseContract` activo |
| RF-27 | `GET` | `/api/v1/inventories/{id}/comparison/` | Tabla inicial vs final; `change_type` y `highlight` en deterioro |
| RF-28 | `GET` | `/api/v1/inventories/{id}/closure-document/` | PDF paz y salvo: comparativo + resumen tickets del contrato |

Cierre de contrato (fin de arriendo):

- `POST /api/v1/contracts/{id}/close/` — body opcional: `end_date`, `deactivate_tenant` (bool), `notes`
- Desvincula inquilino del inmueble; opcionalmente desactiva usuario si no tiene más inmuebles activos
- Bloquea cierre si hay tickets abiertos/aceptados/en proceso para ese inmueble y arrendatario

Modelo: `LeaseContract` (`property`, `tenant`, `start_date`, `end_date`, `status`, `final_inventory`).

## Nota de alcance

Reportes administrativos completos quedan en otro módulo de iteración 2.
