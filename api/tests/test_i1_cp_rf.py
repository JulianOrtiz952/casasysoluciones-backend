"""Matriz de casos de prueba CP-RF-01 a CP-RF-17 (iteración 1, documento de ingeniería).

Cada CP-RF-XX valida el requerimiento funcional RF-XX correspondiente vía API `/api/v1/`.
Los escenarios canónicos viven en los módulos `test_i1_*.py` indicados abajo.
"""

import importlib
import pkgutil
import re
import unittest

CP_RF_I1_MATRIX = {
    'CP-RF-01': {
        'rf': 'RF-01',
        'module': 'test_i1_base',
        'tests': ['test_cp_rf_01_login_email_cedula_lockout_rf01'],
        'summary': 'Login con email o cédula, error claro y bloqueo por intentos fallidos.',
    },
    'CP-RF-02': {
        'rf': 'RF-02',
        'module': 'test_i1_users',
        'tests': ['test_cp_rf_02_admin_creates_tenant_sends_email_rf02'],
        'summary': 'Solo ADMIN crea arrendatario y envía contraseña temporal por correo.',
    },
    'CP-RF-03': {
        'rf': 'RF-03',
        'module': 'test_i1_users',
        'tests': ['test_cp_rf_03_role_change_warns_open_tickets_rf03'],
        'summary': 'Cambio de rol con advertencia si hay tickets abiertos.',
    },
    'CP-RF-04': {
        'rf': 'RF-04',
        'module': 'test_i1_users',
        'tests': [
            'test_cp_rf_04_associate_tenant_property_rf04',
            'test_cp_rf_04_blocks_double_tenant_on_property_rf04',
        ],
        'summary': 'Asociación multi-inmueble y bloqueo de doble arrendatario activo.',
    },
    'CP-RF-05': {
        'rf': 'RF-05',
        'module': 'test_i1_users',
        'tests': ['test_cp_rf_05_deactivate_preserves_history_rf05'],
        'summary': 'Desactivar arrendatario sin borrar historial ni desvincular inmuebles.',
    },
    'CP-RF-06': {
        'rf': 'RF-06',
        'module': 'test_i1_properties',
        'tests': [
            'test_cp_rf_06_create_property_unique_code_rf06',
            'test_cp_rf_06_rejects_duplicate_address_rf06',
        ],
        'summary': 'Crear inmueble con código autogenerado y dirección única.',
    },
    'CP-RF-07': {
        'rf': 'RF-07',
        'module': 'test_i1_properties',
        'tests': ['test_cp_rf_07_property_history_chronological_rf07'],
        'summary': 'Historial cronológico del inmueble.',
    },
    'CP-RF-08': {
        'rf': 'RF-08',
        'module': 'test_i1_inventories',
        'tests': ['test_cp_rf_08_create_initial_inventory_rf08'],
        'summary': 'Crear inventario INITIAL en IN_PROGRESS con arrendatario asociado.',
    },
    'CP-RF-09': {
        'rf': 'RF-09',
        'module': 'test_i1_inventories',
        'tests': ['test_cp_rf_09_space_templates_and_dynamic_spaces_rf09'],
        'summary': 'Plantillas por tipo y espacios dinámicos.',
    },
    'CP-RF-10': {
        'rf': 'RF-10',
        'module': 'test_i1_inventories',
        'tests': [
            'test_cp_rf_10_photo_upload_and_validation_rf10',
            'test_cp_rf_10_rejects_oversized_image_rf10',
        ],
        'summary': 'Fotos JPG/PNG ≤5 MB con validación de tamaño.',
    },
    'CP-RF-11': {
        'rf': 'RF-11',
        'module': 'test_i1_inventories',
        'tests': [
            'test_cp_rf_11_tenant_signs_inventory_rf11',
            'test_cp_rf_11_tenant_observations_alternate_rf11',
        ],
        'summary': 'Firma del arrendatario o flujo alterno de observaciones.',
    },
    'CP-RF-12': {
        'rf': 'RF-12',
        'module': 'test_i1_inventories',
        'tests': ['test_cp_rf_12_inventory_pdf_generation_rf12'],
        'summary': 'Generación de PDF del inventario con registro en historial.',
    },
    'CP-RF-13': {
        'rf': 'RF-13',
        'module': 'test_i1_tickets',
        'tests': ['test_cp_rf_13_create_open_ticket_notify_staff_rf13'],
        'summary': 'Crear ticket OPEN con radicado TK-xxxxx y notificación a staff.',
    },
    'CP-RF-14': {
        'rf': 'RF-14',
        'module': 'test_i1_tickets',
        'tests': ['test_cp_rf_14_property_id_auto_and_required_rf14'],
        'summary': 'Selección de inmueble según cantidad de asociaciones activas.',
    },
    'CP-RF-15': {
        'rf': 'RF-15',
        'module': 'test_i1_tickets',
        'tests': ['test_cp_rf_15_damage_type_catalog_and_other_rf15'],
        'summary': 'Catálogo damage_type; OTHER exige texto adicional.',
    },
    'CP-RF-16': {
        'rf': 'RF-16',
        'module': 'test_i1_tickets',
        'tests': ['test_cp_rf_16_priority_required_rf16'],
        'summary': 'Prioridad obligatoria al crear ticket.',
    },
    'CP-RF-17': {
        'rf': 'RF-17',
        'module': 'test_i1_tickets',
        'tests': ['test_cp_rf_17_attachments_limit_and_format_rf17'],
        'summary': 'Máximo 5 adjuntos con validación de formato y tamaño.',
    },
}


def _collect_i1_test_methods():
    loader = unittest.defaultTestLoader
    methods = set()
    package = importlib.import_module('api.tests')
    prefix = f'{package.__name__}.'
    for module_info in pkgutil.iter_modules(package.__path__):
        if not module_info.name.startswith('test_i1_') or module_info.name == 'test_i1_cp_rf':
            continue
        module = importlib.import_module(prefix + module_info.name)
        suite = loader.loadTestsFromModule(module)
        for test in _flatten_tests(suite):
            if test._testMethodName.startswith('test_cp_rf_'):
                methods.add(test._testMethodName)
    return methods


def _flatten_tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten_tests(item)
        else:
            yield item


class CP_RF_I1_CoverageTests(unittest.TestCase):
    """Verifica que los 17 casos CP-RF de iteración 1 estén implementados."""

    def test_all_cp_rf_01_to_17_cases_registered(self):
        self.assertEqual(len(CP_RF_I1_MATRIX), 17)
        self.assertEqual(list(CP_RF_I1_MATRIX.keys())[0], 'CP-RF-01')
        self.assertEqual(list(CP_RF_I1_MATRIX.keys())[-1], 'CP-RF-17')

    def test_all_cp_rf_i1_test_methods_exist(self):
        available = _collect_i1_test_methods()
        missing = []
        for case_id, meta in CP_RF_I1_MATRIX.items():
            for test_name in meta['tests']:
                if test_name not in available:
                    missing.append(f'{case_id} -> {meta["module"]}.{test_name}')
        self.assertEqual(missing, [], msg='Faltan métodos de prueba: ' + ', '.join(missing))

    def test_cp_rf_test_names_follow_convention(self):
        pattern = re.compile(r'^test_cp_rf_\d{2}_')
        for name in _collect_i1_test_methods():
            self.assertRegex(name, pattern, msg=f'Nombre fuera de convención: {name}')
