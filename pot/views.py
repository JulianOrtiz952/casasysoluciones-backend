from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.db import models, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from pot.forms import (
    AssociatePropertyForm,
    FirstPasswordChangeForm,
    InventoryInitialForm,
    InventoryPhotoUploadForm,
    InventorySpaceForm,
    LoginForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
    PropertyFilterForm,
    PropertyForm,
    PropertyHistoryFilterForm,
    UserEditRoleForm,
    UserTenantCreateForm,
)
from pot.models import (
    CustomUser,
    Inventory,
    InventorySpace,
    InventorySpacePhoto,
    InventoryTenantObservation,
    Property,
    PropertyHistory,
    Ticket,
    UserAudit,
    UserPropertyAssociation,
)
from pot.services.auth_service import (
    generar_password_temporal,
    generar_reset_token,
    limpiar_intentos_fallidos,
    registrar_intento_fallido,
    verificar_intento_login,
)
from pot.services.email_service import (
    enviar_credenciales_temporales,
    enviar_notificacion_propiedad_asociada,
    enviar_notificacion_rol_cambio,
    enviar_observaciones_inventario_admin,
    enviar_reset_password,
)
from pot.services.inventory_service import generar_pdf_inventario, guardar_thumbnail_foto, notificar_inventario_pendiente_firma
from pot.services.property_service import generar_codigo_propiedad, obtener_historial_filtrado, registrar_evento_propiedad
from pot.services.signature_service import completar_flujo_firma


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        u = self.request.user
        return u.role == CustomUser.Role.ADMIN


class StaffOperativeRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        u = self.request.user
        return u.is_staff_operative()


class PotLoginView(DjangoLoginView):
    template_name = 'auth/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if request.method == 'POST':
            email = (request.POST.get('username') or '').strip()
            if email:
                try:
                    cand = CustomUser.objects.get(email__iexact=email)
                except CustomUser.DoesNotExist:
                    cand = None
                if cand:
                    ok, until = verificar_intento_login(cand)
                    if not ok:
                        messages.error(
                            request,
                            f'Cuenta bloqueada. Intenta después de {until.strftime("%H:%M")}.',
                        )
                        return render(request, self.template_name, {'form': LoginForm()})
        return super().dispatch(request, *args, **kwargs)

    def form_invalid(self, form):
        email = (self.request.POST.get('username') or '').strip()
        if email:
            try:
                u = CustomUser.objects.get(email__iexact=email)
                registrar_intento_fallido(u)
            except CustomUser.DoesNotExist:
                pass
        return super().form_invalid(form)

    def form_valid(self, form):
        user = form.get_user()
        if not user.is_active:
            messages.error(self.request, 'Usuario desactivado.')
            return redirect('pot:login')
        limpiar_intentos_fallidos(user)
        return super().form_valid(form)

    def get_success_url(self):
        user = self.request.user
        if not user.password_changed:
            return reverse('pot:password_change_first')
        if user.role == CustomUser.Role.TENANT:
            return reverse('pot:dashboard_tenant')
        return reverse('pot:dashboard_staff')


class PotLogoutView(View):
    def get(self, request):
        logout(request)
        return redirect('pot:login')


class PasswordResetRequestView(View):
    def get(self, request):
        return render(request, 'auth/password_reset.html', {'form': PasswordResetRequestForm()})

    def post(self, request):
        form = PasswordResetRequestForm(request.POST)
        if not form.is_valid():
            return render(request, 'auth/password_reset.html', {'form': form})
        email = form.cleaned_data['email']
        try:
            user = CustomUser.objects.get(email__iexact=email)
        except CustomUser.DoesNotExist:
            messages.success(request, 'Si el email existe, recibirás instrucciones.')
            return redirect('pot:login')
        user.password_reset_token = generar_reset_token()
        user.password_reset_expires = timezone.now() + timedelta(hours=24)
        user.save(update_fields=['password_reset_token', 'password_reset_expires'])
        enviar_reset_password(user, user.password_reset_token, request)
        messages.success(request, 'Si el email existe, recibirás instrucciones.')
        return redirect('pot:login')


class PasswordResetConfirmView(View):
    def get(self, request, token):
        user = CustomUser.objects.filter(password_reset_token=token).first()
        if not user or not user.password_reset_expires or user.password_reset_expires < timezone.now():
            messages.error(request, 'Enlace inválido o expirado.')
            return redirect('pot:password_reset')
        return render(request, 'auth/password_reset_confirm.html', {'form': PasswordResetConfirmForm(), 'token': token})

    def post(self, request, token):
        user = CustomUser.objects.filter(password_reset_token=token).first()
        if not user or not user.password_reset_expires or user.password_reset_expires < timezone.now():
            messages.error(request, 'Enlace inválido o expirado.')
            return redirect('pot:password_reset')
        form = PasswordResetConfirmForm(request.POST)
        if not form.is_valid():
            return render(request, 'auth/password_reset_confirm.html', {'form': form, 'token': token})
        pwd = form.cleaned_data['new_password']
        try:
            validate_password(pwd, user=user)
        except DjangoValidationError as exc:
            for msg in exc.messages:
                form.add_error('new_password', msg)
            return render(request, 'auth/password_reset_confirm.html', {'form': form, 'token': token})
        user.set_password(pwd)
        user.password_reset_token = None
        user.password_reset_expires = None
        user.password_changed = True
        user.save()
        messages.success(request, 'Contraseña actualizada. Inicia sesión.')
        return redirect('pot:login')


class FirstPasswordChangeView(LoginRequiredMixin, View):
    def get(self, request):
        if request.user.password_changed:
            return redirect('pot:dashboard_tenant' if request.user.role == CustomUser.Role.TENANT else 'pot:dashboard_staff')
        return render(request, 'auth/password_change_first.html', {'form': FirstPasswordChangeForm()})

    def post(self, request):
        form = FirstPasswordChangeForm(request.POST)
        if not form.is_valid():
            return render(request, 'auth/password_change_first.html', {'form': form})
        pwd = form.cleaned_data['new_password']
        try:
            validate_password(pwd, user=request.user)
        except DjangoValidationError as exc:
            for msg in exc.messages:
                form.add_error('new_password', msg)
            return render(request, 'auth/password_change_first.html', {'form': form})
        request.user.set_password(pwd)
        request.user.password_changed = True
        request.user.save()
        messages.success(request, 'Contraseña actualizada.')
        if request.user.role == CustomUser.Role.TENANT:
            return redirect('pot:dashboard_tenant')
        return redirect('pot:dashboard_staff')


class DashboardStaffView(StaffOperativeRequiredMixin, View):
    def get(self, request):
        return render(request, 'dashboard_staff.html')


class DashboardTenantView(LoginRequiredMixin, UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.role == CustomUser.Role.TENANT

    def get(self, request):
        props = Property.objects.filter(
            tenant_associations__user=request.user,
            tenant_associations__dissociated_at__isnull=True,
        ).distinct()
        return render(request, 'dashboard_tenant.html', {'properties': props})


class UserListView(AdminRequiredMixin, View):
    def get(self, request):
        qs = CustomUser.objects.all().order_by('-created_at')
        role = request.GET.get('role')
        active = request.GET.get('active')
        if role:
            qs = qs.filter(role=role)
        if active == '1':
            qs = qs.filter(is_active=True)
        elif active == '0':
            qs = qs.filter(is_active=False)
        users = []
        for u in qs[:200]:
            props = list(
                UserPropertyAssociation.objects.filter(user=u, dissociated_at__isnull=True).select_related('property')
            )
            users.append({'user': u, 'associations': props})
        return render(request, 'users/user_list.html', {'users': users, 'role': role, 'active': active})


class UserCreateView(AdminRequiredMixin, View):
    def get(self, request):
        return render(request, 'users/user_create.html', {'form': UserTenantCreateForm()})

    def post(self, request):
        form = UserTenantCreateForm(request.POST)
        if not form.is_valid():
            return render(request, 'users/user_create.html', {'form': form})
        data = form.cleaned_data
        props = list(data.pop('properties'))
        for p in props:
            if UserPropertyAssociation.objects.filter(property=p, dissociated_at__isnull=True).exists():
                messages.error(request, f'Inmueble {p.code} ya tiene arrendatario activo.')
                form.add_error('properties', 'Quita inmuebles ya asignados.')
                return render(request, 'users/user_create.html', {'form': form})
        temp = generar_password_temporal()
        with transaction.atomic():
            user = CustomUser.objects.create_user(
                email=data['email'],
                password=temp,
                first_name=data.get('first_name') or '',
                last_name=data.get('last_name') or '',
                phone=data.get('phone') or '',
                role=CustomUser.Role.TENANT,
                password_changed=False,
            )
            for p in props:
                UserPropertyAssociation.objects.create(user=user, property=p, created_by=request.user)
                p.status = Property.Status.RENTED
                p.save(update_fields=['status', 'updated_at'])
                registrar_evento_propiedad(
                    p,
                    PropertyHistory.EventType.TENANT_ASSOCIATED,
                    f'Asociado {user.email}',
                    created_by=request.user,
                    related_user=user,
                )
            UserAudit.objects.create(
                user=user,
                action='CREATED',
                details={'email': user.email, 'role': user.role},
                changed_by=request.user,
            )
        enviar_credenciales_temporales(user, temp, request)
        messages.success(request, 'Arrendatario creado.')
        return redirect('pot:user_detail', user_id=user.pk)


class UserDetailView(LoginRequiredMixin, View):
    def get(self, request, user_id):
        target = get_object_or_404(CustomUser, pk=user_id)
        if request.user.role != CustomUser.Role.ADMIN and request.user.pk != target.pk:
            messages.error(request, 'Sin permiso.')
            return redirect('pot:dashboard_staff')
        assocs = UserPropertyAssociation.objects.filter(user=target).select_related('property').order_by('-associated_at')
        audits = UserAudit.objects.filter(user=target).order_by('-created_at')[:50]
        open_tickets = Ticket.objects.filter(tenant=target, status=Ticket.Status.OPEN).exists()
        return render(
            request,
            'users/user_detail.html',
            {
                'target': target,
                'associations': assocs,
                'audits': audits,
                'open_tickets': open_tickets,
                'role_form': UserEditRoleForm(initial={'role': target.role}),
                'assoc_form': AssociatePropertyForm(),
            },
        )


class UserEditRoleView(AdminRequiredMixin, View):
    def post(self, request, user_id):
        target = get_object_or_404(CustomUser, pk=user_id)
        form = UserEditRoleForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Rol inválido.')
            return redirect('pot:user_detail', user_id=user_id)
        new_role = form.cleaned_data['role']
        if new_role == target.role:
            return redirect('pot:user_detail', user_id=user_id)
        if not request.POST.get('confirm') and Ticket.objects.filter(tenant=target, status=Ticket.Status.OPEN).exists():
            messages.warning(request, 'Usuario tiene tickets abiertos. Confirma cambio de rol.')
            return redirect(f'/users/{user_id}/?need_confirm_role=1')
        old = target.role
        target.role = new_role
        target.save(update_fields=['role', 'updated_at'])
        UserAudit.objects.create(
            user=target,
            action='ROLE_CHANGED',
            details={'from': old, 'to': new_role},
            changed_by=request.user,
        )
        enviar_notificacion_rol_cambio(target, target.get_role_display(), request.user)
        messages.success(request, 'Rol actualizado.')
        return redirect('pot:user_detail', user_id=user_id)


class UserDeactivateView(AdminRequiredMixin, View):
    def post(self, request, user_id):
        target = get_object_or_404(CustomUser, pk=user_id)
        if target.pk == request.user.pk:
            messages.error(request, 'No puedes desactivarte.')
            return redirect('pot:user_detail', user_id=user_id)
        if not request.POST.get('confirm'):
            if Ticket.objects.filter(tenant=target, status=Ticket.Status.OPEN).exists():
                messages.warning(request, 'Tiene tickets activos. Confirma.')
                return redirect(f'/users/{user_id}/?need_confirm_deactivate=1')
            pending_inv = Inventory.objects.filter(
                tenant=target,
                status__in=[
                    Inventory.Status.PENDING_SIGNATURE,
                    Inventory.Status.IN_PROGRESS,
                    Inventory.Status.OBSERVATIONS_PENDING,
                ],
            ).exists()
            if pending_inv:
                messages.warning(request, 'Tiene inventarios sin cerrar. Confirma.')
                return redirect(f'/users/{user_id}/?need_confirm_deactivate=1')
        target.is_active = False
        target.save(update_fields=['is_active', 'updated_at'])
        now = timezone.now()
        for a in UserPropertyAssociation.objects.filter(user=target, dissociated_at__isnull=True):
            a.dissociated_at = now
            a.save(update_fields=['dissociated_at'])
            prop = a.property
            prop.status = Property.Status.AVAILABLE
            prop.save(update_fields=['status', 'updated_at'])
            registrar_evento_propiedad(
                prop,
                PropertyHistory.EventType.TENANT_DISSOCIATED,
                f'Desasociado {target.email} (usuario desactivado)',
                created_by=request.user,
                related_user=target,
            )
        UserAudit.objects.create(
            user=target,
            action='DEACTIVATED',
            details={},
            changed_by=request.user,
        )
        messages.success(request, 'Usuario desactivado.')
        return redirect('pot:user_list')


class UserReactivateView(AdminRequiredMixin, View):
    def post(self, request, user_id):
        target = get_object_or_404(CustomUser, pk=user_id)
        target.is_active = True
        target.save(update_fields=['is_active', 'updated_at'])
        UserAudit.objects.create(user=target, action='REACTIVATED', details={}, changed_by=request.user)
        messages.success(request, 'Usuario reactivado. Reasocia inmuebles.')
        return redirect('pot:user_detail', user_id=user_id)


class AssociatePropertyView(AdminRequiredMixin, View):
    def post(self, request, user_id):
        target = get_object_or_404(CustomUser, pk=user_id, role=CustomUser.Role.TENANT)
        form = AssociatePropertyForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Datos inválidos.')
            return redirect('pot:user_detail', user_id=user_id)
        prop = form.cleaned_data['property']
        if UserPropertyAssociation.objects.filter(property=prop, dissociated_at__isnull=True).exists():
            messages.error(request, 'Inmueble ya tiene arrendatario activo.')
            return redirect('pot:user_detail', user_id=user_id)
        UserPropertyAssociation.objects.create(user=target, property=prop, created_by=request.user)
        prop.status = Property.Status.RENTED
        prop.save(update_fields=['status', 'updated_at'])
        registrar_evento_propiedad(
            prop,
            PropertyHistory.EventType.TENANT_ASSOCIATED,
            f'Asociado {target.email}',
            created_by=request.user,
            related_user=target,
        )
        enviar_notificacion_propiedad_asociada(target, prop, request)
        UserAudit.objects.create(
            user=target,
            action='PROPERTY_ASSOCIATED',
            details={'property_id': prop.pk, 'code': prop.code},
            changed_by=request.user,
        )
        messages.success(request, 'Inmueble asociado.')
        return redirect('pot:user_detail', user_id=user_id)


class DissociatePropertyView(AdminRequiredMixin, View):
    def post(self, request, user_id, property_id):
        target = get_object_or_404(CustomUser, pk=user_id)
        prop = get_object_or_404(Property, pk=property_id)
        assoc = UserPropertyAssociation.objects.filter(user=target, property=prop, dissociated_at__isnull=True).first()
        if not assoc:
            messages.error(request, 'Asociación no encontrada.')
            return redirect('pot:user_detail', user_id=user_id)
        assoc.dissociated_at = timezone.now()
        assoc.save(update_fields=['dissociated_at'])
        prop.status = Property.Status.AVAILABLE
        prop.save(update_fields=['status', 'updated_at'])
        registrar_evento_propiedad(
            prop,
            PropertyHistory.EventType.TENANT_DISSOCIATED,
            f'Desasociado {target.email}',
            created_by=request.user,
            related_user=target,
        )
        messages.success(request, 'Inmueble desasociado.')
        return redirect('pot:user_detail', user_id=user_id)


class PropertyListView(StaffOperativeRequiredMixin, ListView):
    model = Property
    template_name = 'properties/property_list.html'
    context_object_name = 'properties'
    paginate_by = 20

    def get_queryset(self):
        qs = Property.objects.all().order_by('-created_at')
        form = PropertyFilterForm(self.request.GET)
        if form.is_valid():
            if form.cleaned_data.get('status'):
                qs = qs.filter(status=form.cleaned_data['status'])
            if form.cleaned_data.get('property_type'):
                qs = qs.filter(type=form.cleaned_data['property_type'])
            s = (form.cleaned_data.get('search') or '').strip()
            if s:
                qs = qs.filter(models.Q(address__icontains=s) | models.Q(code__icontains=s))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['filter_form'] = PropertyFilterForm(self.request.GET)
        return ctx


class PropertyCreateView(StaffOperativeRequiredMixin, View):
    def get(self, request):
        return render(request, 'properties/property_create.html', {'form': PropertyForm()})

    def post(self, request):
        form = PropertyForm(request.POST)
        if not form.is_valid():
            return render(request, 'properties/property_create.html', {'form': form})
        prop = form.save(commit=False)
        prop.code = generar_codigo_propiedad()
        prop.status = Property.Status.AVAILABLE
        prop.created_by = request.user
        prop.save()
        registrar_evento_propiedad(
            prop,
            PropertyHistory.EventType.CREATED,
            f'Inmueble creado {prop.code}',
            created_by=request.user,
            details={'address': prop.address},
        )
        messages.success(request, 'Inmueble registrado.')
        return redirect('pot:property_detail', property_id=prop.pk)


class PropertyDetailView(StaffOperativeRequiredMixin, View):
    def get(self, request, property_id):
        prop = get_object_or_404(Property, pk=property_id)
        hist_form = PropertyHistoryFilterForm(request.GET)
        events = prop.history.all().order_by('-created_at')[:500]
        if hist_form.is_valid():
            d = hist_form.cleaned_data
            events = obtener_historial_filtrado(
                prop,
                fecha_desde=d.get('fecha_desde'),
                fecha_hasta=d.get('fecha_hasta'),
                tipo_evento=d.get('tipo_evento') or None,
                tenant_id=d.get('tenant').pk if d.get('tenant') else None,
            )
        tenant = prop.get_active_tenant()
        return render(
            request,
            'properties/property_detail.html',
            {'property': prop, 'history': events, 'hist_form': hist_form, 'active_tenant': tenant},
        )


class PropertyEditView(StaffOperativeRequiredMixin, View):
    def get(self, request, property_id):
        prop = get_object_or_404(Property, pk=property_id)
        return render(request, 'properties/property_edit.html', {'form': PropertyForm(instance=prop), 'property': prop})

    def post(self, request, property_id):
        prop = get_object_or_404(Property, pk=property_id)
        old_status = prop.status
        form = PropertyForm(request.POST, instance=prop)
        if not form.is_valid():
            return render(request, 'properties/property_edit.html', {'form': form, 'property': prop})
        form.save()
        prop.refresh_from_db()
        if old_status != prop.status:
            registrar_evento_propiedad(
                prop,
                PropertyHistory.EventType.STATUS_CHANGE,
                f'Estado {old_status} → {prop.status}',
                created_by=request.user,
                details={'old': old_status, 'new': prop.status},
            )
        messages.success(request, 'Inmueble actualizado.')
        return redirect('pot:property_detail', property_id=prop.pk)


class PropertyHistoryFilterView(StaffOperativeRequiredMixin, View):
    def get(self, request, property_id):
        prop = get_object_or_404(Property, pk=property_id)
        form = PropertyHistoryFilterForm(request.GET)
        if not form.is_valid():
            return JsonResponse({'events': []})
        d = form.cleaned_data
        qs = obtener_historial_filtrado(
            prop,
            fecha_desde=d.get('fecha_desde'),
            fecha_hasta=d.get('fecha_hasta'),
            tipo_evento=d.get('tipo_evento') or None,
            tenant_id=d.get('tenant').pk if d.get('tenant') else None,
        )
        data = [
            {
                'id': e.pk,
                'type': e.event_type,
                'type_display': e.get_event_type_display(),
                'description': e.description,
                'at': e.created_at.isoformat(),
            }
            for e in qs[:200]
        ]
        return JsonResponse({'events': data})


class InventoryCreateView(StaffOperativeRequiredMixin, View):
    def get(self, request, property_id=None):
        initial = {}
        if property_id:
            initial['property'] = get_object_or_404(Property, pk=property_id)
        form = InventoryInitialForm(initial=initial)
        return render(request, 'inventory/inventory_create.html', {'form': form, 'property_id': property_id})

    def post(self, request, property_id=None):
        form = InventoryInitialForm(request.POST)
        if not form.is_valid():
            return render(request, 'inventory/inventory_create.html', {'form': form, 'property_id': property_id})
        inv = form.save(commit=False)
        inv.inventory_type = Inventory.Type.INITIAL
        inv.status = Inventory.Status.IN_PROGRESS
        inv.created_by = request.user
        prop = inv.property
        ten = inv.tenant
        if Inventory.objects.filter(
            property=prop,
            inventory_type=Inventory.Type.INITIAL,
            status=Inventory.Status.ACCEPTED,
        ).exists():
            messages.error(request, 'Ya existe inventario inicial aceptado para este inmueble.')
            return render(request, 'inventory/inventory_create.html', {'form': form, 'property_id': property_id})
        if not UserPropertyAssociation.objects.filter(user=ten, property=prop, dissociated_at__isnull=True).exists():
            messages.error(request, 'Arrendatario no está asociado a este inmueble.')
            return render(request, 'inventory/inventory_create.html', {'form': form, 'property_id': property_id})
        try:
            inv.save()
        except Exception:
            messages.error(request, 'No se pudo crear (¿duplicado propiedad/arrendatario/tipo?).')
            return render(request, 'inventory/inventory_create.html', {'form': form, 'property_id': property_id})
        registrar_evento_propiedad(
            prop,
            PropertyHistory.EventType.INVENTORY_CREATED,
            f'Inventario inicial #{inv.pk}',
            created_by=request.user,
            related_user=ten,
            details={'inventory_id': inv.pk},
        )
        messages.success(request, 'Inventario en registro.')
        return redirect('pot:inventory_spaces', inventory_id=inv.pk)


class InventoryDetailView(StaffOperativeRequiredMixin, View):
    def get(self, request, inventory_id):
        inv = get_object_or_404(Inventory.objects.select_related('property', 'tenant'), pk=inventory_id)
        return render(request, 'inventory/inventory_detail.html', {'inventory': inv})


class InventorySpaceManagementView(StaffOperativeRequiredMixin, View):
    def get(self, request, inventory_id):
        inv = get_object_or_404(Inventory, pk=inventory_id)
        if not inv.is_editable():
            messages.error(request, 'Inventario no editable.')
            return redirect('pot:inventory_detail', inventory_id=inv.pk)
        return render(
            request,
            'inventory/inventory_spaces.html',
            {'inventory': inv, 'space_form': InventorySpaceForm()},
        )

    def post(self, request, inventory_id):
        inv = get_object_or_404(Inventory, pk=inventory_id)
        if not inv.is_editable():
            messages.error(request, 'Inventario no editable.')
            return redirect('pot:inventory_detail', inventory_id=inv.pk)
        form = InventorySpaceForm(request.POST)
        if form.is_valid():
            sp = form.save(commit=False)
            sp.inventory = inv
            sp.order = inv.spaces.count()
            sp.save()
            messages.success(request, 'Espacio agregado.')
        else:
            messages.error(request, 'Revisa el formulario de espacio.')
        return redirect('pot:inventory_spaces', inventory_id=inv.pk)


class InventorySpaceDeleteView(StaffOperativeRequiredMixin, View):
    def post(self, request, space_id):
        sp = get_object_or_404(InventorySpace, pk=space_id)
        inv = sp.inventory
        if not inv.is_editable():
            messages.error(request, 'No se puede eliminar.')
            return redirect('pot:inventory_spaces', inventory_id=inv.pk)
        inv_id = inv.pk
        sp.delete()
        messages.success(request, 'Espacio eliminado.')
        return redirect('pot:inventory_spaces', inventory_id=inv_id)


class InventoryPhotoUploadView(StaffOperativeRequiredMixin, View):
    def post(self, request, space_id):
        sp = get_object_or_404(InventorySpace, pk=space_id)
        inv = sp.inventory
        if not inv.is_editable():
            messages.error(request, 'No editable.')
            return redirect('pot:inventory_spaces', inventory_id=inv.pk)
        form = InventoryPhotoUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return redirect('pot:inventory_spaces', inventory_id=inv.pk)
        photo = InventorySpacePhoto.objects.create(
            space=sp,
            image=form.cleaned_data['image'],
            description=form.cleaned_data.get('description') or '',
            uploaded_by=request.user,
        )
        try:
            guardar_thumbnail_foto(photo)
        except Exception:
            pass
        messages.success(request, 'Foto subida.')
        return redirect('pot:inventory_spaces', inventory_id=inv.pk)


class InventoryPhotoDeleteView(StaffOperativeRequiredMixin, View):
    def post(self, request, photo_id):
        photo = get_object_or_404(InventorySpacePhoto, pk=photo_id)
        inv = photo.space.inventory
        if not inv.is_editable():
            messages.error(request, 'No se puede eliminar.')
            return redirect('pot:inventory_spaces', inventory_id=inv.pk)
        inv_id = inv.pk
        photo.delete()
        messages.success(request, 'Foto eliminada.')
        return redirect('pot:inventory_spaces', inventory_id=inv_id)


class InventoryGeneratePDFView(LoginRequiredMixin, View):
    def get(self, request, inventory_id):
        inv = get_object_or_404(Inventory.objects.prefetch_related('spaces__photos'), pk=inventory_id)
        if inv.spaces.count() < 1:
            messages.error(request, 'Agrega al menos un espacio.')
            return redirect('pot:inventory_detail', inventory_id=inv.pk)
        if request.user.role == CustomUser.Role.TENANT:
            if inv.tenant_id != request.user.pk:
                messages.error(request, 'Sin acceso.')
                return redirect('pot:my_inventories')
        elif not request.user.is_staff_operative():
            messages.error(request, 'Sin acceso.')
            return redirect('pot:dashboard_staff')
        pdf = generar_pdf_inventario(inv)
        name = f'INVENTORY-{inv.property.code}-{timezone.now().strftime("%Y%m%d")}.pdf'
        resp = HttpResponse(pdf.read(), content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="{name}"'
        return resp


class InventoryFinalizationView(StaffOperativeRequiredMixin, View):
    def post(self, request, inventory_id):
        inv = get_object_or_404(Inventory, pk=inventory_id)
        if inv.spaces.count() < 1:
            messages.error(request, 'Mínimo 1 espacio.')
            return redirect('pot:inventory_spaces', inventory_id=inv.pk)
        inv.status = Inventory.Status.PENDING_SIGNATURE
        inv.save(update_fields=['status', 'updated_at'])
        notificar_inventario_pendiente_firma(inv, request)
        messages.success(request, 'Pendiente de firma. Notificación enviada.')
        return redirect('pot:inventory_detail', inventory_id=inv.pk)


class InventoryTenantListView(LoginRequiredMixin, UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.role == CustomUser.Role.TENANT

    def get(self, request):
        qs = Inventory.objects.filter(
            tenant=request.user,
            status=Inventory.Status.PENDING_SIGNATURE,
        ).select_related('property')
        return render(request, 'inventory/my_inventories.html', {'inventories': qs})


class InventorySigningPageView(LoginRequiredMixin, UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.role == CustomUser.Role.TENANT

    def get(self, request, inventory_id):
        inv = get_object_or_404(Inventory.objects.prefetch_related('spaces__photos'), pk=inventory_id)
        if inv.tenant_id != request.user.pk:
            messages.error(request, 'No es tu inventario.')
            return redirect('pot:my_inventories')
        if inv.status != Inventory.Status.PENDING_SIGNATURE:
            messages.info(request, 'Inventario no está pendiente de firma.')
            return redirect('pot:my_inventories')
        return render(request, 'inventory/inventory_sign_page.html', {'inventory': inv})


class InventorySignConfirmView(LoginRequiredMixin, UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.role == CustomUser.Role.TENANT

    def post(self, request, inventory_id):
        inv = get_object_or_404(Inventory, pk=inventory_id)
        if inv.tenant_id != request.user.pk or inv.status != Inventory.Status.PENDING_SIGNATURE:
            messages.error(request, 'No se puede firmar.')
            return redirect('pot:my_inventories')
        completar_flujo_firma(inv, request.user, request)
        messages.success(request, 'Inventario firmado.')
        return redirect('pot:my_inventories')


class InventoryObservationRegisterView(LoginRequiredMixin, UserPassesTestMixin, View):
    def test_func(self):
        return self.request.user.role == CustomUser.Role.TENANT

    def post(self, request, inventory_id):
        inv = get_object_or_404(Inventory, pk=inventory_id)
        if inv.tenant_id != request.user.pk or inv.status != Inventory.Status.PENDING_SIGNATURE:
            messages.error(request, 'No disponible.')
            return redirect('pot:my_inventories')
        text = (request.POST.get('observation_text') or '').strip()
        if not text:
            messages.error(request, 'Escribe observaciones.')
            return redirect('pot:inventory_sign', inventory_id=inv.pk)
        InventoryTenantObservation.objects.create(inventory=inv, observation_text=text, created_by=request.user)
        inv.status = Inventory.Status.OBSERVATIONS_PENDING
        inv.save(update_fields=['status', 'updated_at'])
        registrar_evento_propiedad(
            inv.property,
            PropertyHistory.EventType.TENANT_OBSERVATIONS,
            'Arrendatario registró observaciones',
            created_by=request.user,
            related_user=request.user,
            details={'inventory_id': inv.pk},
        )
        enviar_observaciones_inventario_admin(inv, text)
        messages.success(request, 'Observaciones enviadas. Admin revisará.')
        return redirect('pot:my_inventories')


class InventoryResolveObservationsView(AdminRequiredMixin, View):
    def post(self, request, inventory_id):
        inv = get_object_or_404(Inventory, pk=inventory_id)
        if inv.status != Inventory.Status.OBSERVATIONS_PENDING:
            messages.error(request, 'Estado incorrecto.')
            return redirect('pot:inventory_detail', inventory_id=inv.pk)
        inv.status = Inventory.Status.PENDING_SIGNATURE
        inv.save(update_fields=['status', 'updated_at'])
        notificar_inventario_pendiente_firma(inv, request)
        messages.success(request, 'Devuelto a pendiente de firma.')
        return redirect('pot:inventory_detail', inventory_id=inv.pk)