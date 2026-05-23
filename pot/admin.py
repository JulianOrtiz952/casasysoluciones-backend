from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from pot.models import (
    CustomUser,
    Inventory,
    InventorySignature,
    InventorySpace,
    InventorySpacePhoto,
    InventoryTenantObservation,
    Property,
    PropertyHistory,
    Ticket,
    TicketAttachment,
    UserAudit,
    UserPropertyAssociation,
)


@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin):
    ordering = ('email',)
    list_display = ('email', 'first_name', 'last_name', 'role', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_active')
    search_fields = ('email', 'first_name', 'last_name')
    filter_horizontal = ()
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            'POT',
            {
                'fields': (
                    'phone',
                    'public_code',
                    'document_type',
                    'document_number',
                    'avatar',
                    'role',
                    'password_changed',
                    'login_attempts',
                    'login_locked_until',
                ),
            },
        ),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'password1', 'password2', 'role', 'phone')}),
    )


admin.site.register(UserPropertyAssociation)
admin.site.register(UserAudit)
admin.site.register(Property)
admin.site.register(PropertyHistory)
admin.site.register(Ticket)
admin.site.register(TicketAttachment)
admin.site.register(Inventory)
admin.site.register(InventorySpace)
admin.site.register(InventorySpacePhoto)
admin.site.register(InventorySignature)
admin.site.register(InventoryTenantObservation)
