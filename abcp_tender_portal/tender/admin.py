from django.contrib import admin
from .models import ClientProfile, TenderJob, LoginCode


@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "profile_id")
    search_fields = ("name", "profile_id")


@admin.register(TenderJob)
class TenderJobAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "created_by", "client_profile", "status")
    list_filter = ("status", "client_profile")
    search_fields = ("id", "client_profile__name", "client_profile__profile_id")
    readonly_fields = ("created_at",)


@admin.register(LoginCode)
class LoginCodeAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "code", "created_at", "is_used")
    list_filter = ("is_used", "created_at")
    search_fields = ("user__username", "user__email", "code")

