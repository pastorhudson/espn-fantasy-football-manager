from django.contrib import admin

from .models import (
    FantasyTeam,
    FreeAgentSnapshot,
    League,
    MatchupSnapshot,
    RosterSlot,
    RosterSnapshot,
    TradeOffer,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(League, ReadOnlyAdmin)
admin.site.register(FantasyTeam, ReadOnlyAdmin)
admin.site.register(RosterSnapshot, ReadOnlyAdmin)
admin.site.register(RosterSlot, ReadOnlyAdmin)
admin.site.register(MatchupSnapshot, ReadOnlyAdmin)
admin.site.register(FreeAgentSnapshot, ReadOnlyAdmin)
admin.site.register(TradeOffer, ReadOnlyAdmin)
