from django.urls import path

from pot import views

app_name = 'pot'

urlpatterns = [
    path('login/', views.PotLoginView.as_view(), name='login'),
    path('logout/', views.PotLogoutView.as_view(), name='logout'),
    path('reset-password/', views.PasswordResetRequestView.as_view(), name='password_reset'),
    path('reset-password/<str:token>/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password/first/', views.FirstPasswordChangeView.as_view(), name='password_change_first'),
    path('dashboard/', views.DashboardStaffView.as_view(), name='dashboard_staff'),
    path('dashboard/tenant/', views.DashboardTenantView.as_view(), name='dashboard_tenant'),
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/create/', views.UserCreateView.as_view(), name='user_create'),
    path('users/<int:user_id>/', views.UserDetailView.as_view(), name='user_detail'),
    path('users/<int:user_id>/role/', views.UserEditRoleView.as_view(), name='user_edit_role'),
    path('users/<int:user_id>/deactivate/', views.UserDeactivateView.as_view(), name='user_deactivate'),
    path('users/<int:user_id>/reactivate/', views.UserReactivateView.as_view(), name='user_reactivate'),
    path('users/<int:user_id>/properties/associate/', views.AssociatePropertyView.as_view(), name='associate_property'),
    path(
        'users/<int:user_id>/properties/<int:property_id>/dissociate/',
        views.DissociatePropertyView.as_view(),
        name='dissociate_property',
    ),
    path('properties/', views.PropertyListView.as_view(), name='property_list'),
    path('properties/create/', views.PropertyCreateView.as_view(), name='property_create'),
    path('properties/<int:property_id>/', views.PropertyDetailView.as_view(), name='property_detail'),
    path('properties/<int:property_id>/edit/', views.PropertyEditView.as_view(), name='property_edit'),
    path('properties/<int:property_id>/history/', views.PropertyHistoryFilterView.as_view(), name='property_history'),
    path('inventories/create/', views.InventoryCreateView.as_view(), name='inventory_create'),
    path('properties/<int:property_id>/inventories/create/', views.InventoryCreateView.as_view(), name='inventory_create_for_property'),
    path('inventories/<int:inventory_id>/', views.InventoryDetailView.as_view(), name='inventory_detail'),
    path('inventories/<int:inventory_id>/spaces/', views.InventorySpaceManagementView.as_view(), name='inventory_spaces'),
    path('inventories/spaces/<int:space_id>/delete/', views.InventorySpaceDeleteView.as_view(), name='inventory_space_delete'),
    path('inventories/spaces/<int:space_id>/photo/upload/', views.InventoryPhotoUploadView.as_view(), name='inventory_photo_upload'),
    path('inventories/photos/<int:photo_id>/delete/', views.InventoryPhotoDeleteView.as_view(), name='inventory_photo_delete'),
    path('inventories/<int:inventory_id>/pdf/', views.InventoryGeneratePDFView.as_view(), name='inventory_pdf'),
    path('inventories/<int:inventory_id>/finalize/', views.InventoryFinalizationView.as_view(), name='inventory_finalize'),
    path('inventories/<int:inventory_id>/resolve-observations/', views.InventoryResolveObservationsView.as_view(), name='inventory_resolve_observations'),
    path('my-inventories/', views.InventoryTenantListView.as_view(), name='my_inventories'),
    path('inventories/<int:inventory_id>/sign/', views.InventorySigningPageView.as_view(), name='inventory_sign'),
    path('inventories/<int:inventory_id>/sign-confirm/', views.InventorySignConfirmView.as_view(), name='inventory_sign_confirm'),
    path('inventories/<int:inventory_id>/observations/', views.InventoryObservationRegisterView.as_view(), name='inventory_observations'),
]
