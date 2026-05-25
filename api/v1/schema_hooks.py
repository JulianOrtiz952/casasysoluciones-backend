"""Filtros de schema OpenAPI para despliegue parcial iteración 1."""

I1_PATH_PREFIXES = (
    '/api/v1/auth/',
    '/api/v1/catalogs/',
    '/api/v1/users/',
    '/api/v1/tenants/',
    '/api/v1/properties/',
    '/api/v1/inventories/',
    '/api/v1/tickets/mine/',
    '/api/v1/tickets/',
    '/api/v1/notifications/',
    '/api/v1/admin/',
    '/api/v1/legacy/',
)

# Rutas de compatibilidad temporal del legado (sin prefijo legacy/)
LEGACY_COMPAT_PATHS = (
    '/api/v1/inmuebles/',
    '/api/v1/inquilinos/',
    '/api/v1/historial_alquiler/',
    '/api/v1/usuarios/',
    '/api/v1/auth/change-password/',
)


def preprocess_filter_i1(endpoints):
    """Incluye solo endpoints de iteración 1 y catálogo legado."""
    filtered = []
    for path, path_regex, method, callback in endpoints:
        if path.startswith(I1_PATH_PREFIXES) or path.startswith(LEGACY_COMPAT_PATHS):
            filtered.append((path, path_regex, method, callback))
    return filtered
