from django.contrib import admin
from django.urls import path, include
from garage import accounts

admin.site.login = accounts.admin_login
admin.site.has_permission = lambda request: request.google_authenticated and request.user.is_active and request.user.is_staff
urlpatterns = [
    path('accounts/login/', accounts.login_page, name='account_login'),
    path('accounts/logout/', accounts.sign_out, name='account_logout'),
    path('accounts/google/login/', accounts.google_login, name='google_login'),
    path('accounts/google/login/callback/', accounts.google_callback, name='google_callback'),
    path('accounts/welcome/', accounts.welcome, name='account-welcome'),
    path('accounts/claim/', accounts.claim, name='garage-claim'),
    path('accounts/claim/resume/', accounts.resume_claim, name='garage-claim-resume'),
    path('accounts/import/', accounts.import_legacy, name='garage-import'),
    path('admin/', admin.site.urls),
    path('', include('garage.urls')),
]
