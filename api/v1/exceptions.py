from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler


class APIError(APIException):
    status_code = 400
    default_code = 'bad_request'

    def __init__(self, code, message, status_code=None, details=None):
        self.code = code
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}
        super().__init__(detail=message, code=code)


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response

    if isinstance(exc, APIError):
        response.data = {
            'error': {
                'code': exc.code,
                'message': exc.message,
                'details': exc.details,
            }
        }
        return response

    if isinstance(response.data, dict) and 'detail' in response.data:
        detail = response.data['detail']
        message = str(detail)
        code = getattr(exc, 'default_code', 'error')
        response.data = {
            'error': {
                'code': code,
                'message': message,
                'details': {},
            }
        }
    elif isinstance(response.data, dict):
        response.data = {
            'error': {
                'code': 'validation_error',
                'message': 'Error de validación.',
                'details': response.data,
            }
        }
    return response
