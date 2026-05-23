from django.shortcuts import redirect


class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        p = request.path
        allow = (
            p.startswith('/admin/')
            or p.startswith('/static/')
            or p.startswith('/media/')
            or p.startswith('/api/')
            or p in ('/login/', '/logout/', '/password/first/')
            or p.startswith('/reset-password')
        )
        u = getattr(request, 'user', None)
        if u and u.is_authenticated and not getattr(u, 'password_changed', True) and not allow:
            return redirect('pot:password_change_first')
        return self.get_response(request)
