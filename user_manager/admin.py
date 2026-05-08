from django.contrib import admin
from .models import UserAcl, UserActionLog

@admin.register(UserActionLog)
class UserActionLogAdmin(admin.ModelAdmin):
    list_display = ('created', 'user', 'action', 'ip_address')
    list_filter = ('action', 'user')
    search_fields = ('action', 'details', 'user__username')
    readonly_fields = ('created', 'user', 'action', 'details', 'ip_address')

admin.site.register(UserAcl)
