from django.contrib import admin

from .models import Decision, ManagerPolicy


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(ManagerPolicy, ReadOnlyAdmin)
admin.site.register(Decision, ReadOnlyAdmin)
