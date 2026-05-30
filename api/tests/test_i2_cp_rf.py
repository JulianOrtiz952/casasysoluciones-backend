"""Matriz de casos de prueba CP-RF-18 a CP-RF-30 (iteración 2, documento de ingeniería).

Cada CP-RF-XX valida el requerimiento funcional RF-XX correspondiente vía API `/api/v1/`.
Los escenarios canónicos viven en los módulos `test_i2_*.py` indicados abajo.
"""

import importlib
import pkgutil
import re
import unittest

CP_RF_I2_MATRIX = {
    'CP-RF-18': {
        'rf': 'RF-18',
        'module': 'test_i2_tickets_gestion',
        'tests': [
            'test_cp_rf_18_staff_list_filters_status_transitions_rf18',
            'test_cp_rf_18_accept_status_transition_logs_rf18',
            'test_cp_rf_18_staff_export_csv_rf18',
        ],
        'summary': 'Gestión de tickets: listado, filtros, transiciones de estado y exportación.',
    },
    'CP-RF-19': {
        'rf': 'RF-19',
        'module': 'test_i2_tickets_gestion',
        'tests': ['test_cp_rf_19_reject_reason_min_length_and_notify_rf19'],
        'summary': 'Rechazo con motivo mínimo 20 caracteres y notificación al arrendatario.',
    },
    'CP-RF-20': {
        'rf': 'RF-20',
        'module': 'test_i2_tickets_gestion',
        'tests': ['test_cp_rf_20_assign_contractor_moves_in_progress_rf20'],
        'summary': 'Asignar maestro subcontratado y pasar a IN_PROGRESS.',
    },
    'CP-RF-21': {
        'rf': 'RF-21',
        'module': 'test_i2_tickets_gestion',
        'tests': ['test_cp_rf_21_repair_evidence_required_to_close_rf21'],
        'summary': 'Evidencia de reparación obligatoria para cerrar ticket.',
    },
    'CP-RF-22': {
        'rf': 'RF-22',
        'module': 'test_i2_tickets_seguimiento',
        'tests': [
            'test_cp_rf_22_tenant_confirm_closes_ticket_rf22',
            'test_cp_rf_22_tenant_dispute_returns_accepted_rf22',
        ],
        'summary': 'Confirmación o disputa de reparación por arrendatario.',
    },
    'CP-RF-23': {
        'rf': 'RF-23',
        'module': 'test_i2_tickets_seguimiento',
        'tests': [
            'test_cp_rf_23_staff_timeline_rf23',
            'test_cp_rf_23_auto_close_expired_confirmation_rf23',
        ],
        'summary': 'Timeline, cierre automático por vencimiento de confirmación.',
    },
    'CP-RF-24': {
        'rf': 'RF-24',
        'module': 'test_i2_comunicacion',
        'tests': [
            'test_cp_rf_24_comments_thread_chronological_rf24',
            'test_cp_rf_24_blocks_comments_on_closed_ticket_rf24',
        ],
        'summary': 'Hilo de comentarios cronológico; bloqueado si ticket cerrado.',
    },
    'CP-RF-25': {
        'rf': 'RF-25',
        'module': 'test_i2_comunicacion',
        'tests': [
            'test_cp_rf_25_request_info_staff_only_rf25',
            'test_cp_rf_25_request_info_min_length_rf25',
        ],
        'summary': 'Solicitud de información por staff con notificación alta y correo.',
    },
    'CP-RF-26': {
        'rf': 'RF-26',
        'module': 'test_i2_inventories_final',
        'tests': ['test_cp_rf_26_create_final_preloads_spaces_rf26'],
        'summary': 'Inventario FINAL precargado desde inicial aceptado (solo staff).',
    },
    'CP-RF-27': {
        'rf': 'RF-27',
        'module': 'test_i2_inventories_final',
        'tests': ['test_cp_rf_27_comparison_highlights_deterioration_rf27'],
        'summary': 'Comparación inicial vs final con deterioro resaltado.',
    },
    'CP-RF-28': {
        'rf': 'RF-28',
        'module': 'test_i2_inventories_final',
        'tests': ['test_cp_rf_28_closure_document_pdf_rf28'],
        'summary': 'PDF paz y salvo con comparativo y registro en historial.',
    },
    'CP-RF-29': {
        'rf': 'RF-29',
        'module': 'test_i2_reportes',
        'tests': [
            'test_cp_rf_29_ticket_stats_pending_resolution_rf29',
            'test_cp_rf_29_reports_traffic_light_pending_resolution_rf29',
        ],
        'summary': 'Semáforo y pending_resolution en stats y reportes.',
    },
    'CP-RF-30': {
        'rf': 'RF-30',
        'module': 'test_i2_reportes',
        'tests': [
            'test_cp_rf_30_assistant_forbidden_on_reports_rf30',
            'test_cp_rf_30_properties_with_open_tickets_rf30',
            'test_cp_rf_30_tenants_with_active_tickets_rf30',
            'test_cp_rf_30_repair_history_closed_tickets_rf30',
            'test_cp_rf_30_export_excel_with_filters_rf30',
        ],
        'summary': 'Reportes administrativos, export Excel y RBAC solo ADMIN.',
    },
}


def _collect_i2_test_methods():
    loader = unittest.defaultTestLoader
    methods = set()
    package = importlib.import_module('api.tests')
    prefix = f'{package.__name__}.'
    for module_info in pkgutil.iter_modules(package.__path__):
        if not module_info.name.startswith('test_i2_') or module_info.name == 'test_i2_cp_rf':
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


class CP_RF_I2_CoverageTests(unittest.TestCase):
    """Verifica que los 13 casos CP-RF de iteración 2 estén implementados."""

    def test_all_cp_rf_18_to_30_cases_registered(self):
        self.assertEqual(len(CP_RF_I2_MATRIX), 13)
        self.assertEqual(list(CP_RF_I2_MATRIX.keys())[0], 'CP-RF-18')
        self.assertEqual(list(CP_RF_I2_MATRIX.keys())[-1], 'CP-RF-30')

    def test_all_cp_rf_i2_test_methods_exist(self):
        available = _collect_i2_test_methods()
        missing = []
        for case_id, meta in CP_RF_I2_MATRIX.items():
            for test_name in meta['tests']:
                if test_name not in available:
                    missing.append(f'{case_id} -> {meta["module"]}.{test_name}')
        self.assertEqual(missing, [], msg='Faltan métodos de prueba: ' + ', '.join(missing))

    def test_cp_rf_test_names_follow_convention(self):
        pattern = re.compile(r'^test_cp_rf_\d{2}_')
        for name in _collect_i2_test_methods():
            self.assertRegex(name, pattern, msg=f'Nombre fuera de convención: {name}')


class I2RegressionI1Tests(unittest.TestCase):
    """Regresión iteración 1: matriz CP-RF-01..17 intacta tras cambios i2."""

    def test_regression_i1_cp_rf_matrix_methods_exist(self):
        from api.tests.test_i1_cp_rf import CP_RF_I1_MATRIX, CP_RF_I1_CoverageTests

        case = CP_RF_I1_CoverageTests('test_all_cp_rf_i1_test_methods_exist')
        case.debug()
        self.assertEqual(len(CP_RF_I1_MATRIX), 17)

    def test_regression_i1_catalogs_endpoint_available(self):
        from rest_framework.test import APIClient
        from pot.models import CustomUser

        admin = CustomUser.objects.create_user(
            email='reg-i1@test.com',
            password='AdminPass123!',
            role=CustomUser.Role.ADMIN,
            password_changed=True,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        r = client.get('/api/v1/catalogs/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('ticket_status', r.data)
