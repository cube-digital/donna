from __future__ import annotations

from django.contrib import admin

from donna.workspaces.models import Workspace, WorkspaceMembership


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at", "updated_at")
    search_fields = ("name", "slug")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("name",)


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(admin.ModelAdmin):
    list_display = ("workspace", "user", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("workspace__name", "user__email")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("workspace", "user")
