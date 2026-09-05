from django.contrib import admin
from .models import Room, Player

@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['code', 'state', 'created_at']
    list_filter = ['state']

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ['name', 'room', 'position']
    list_filter = ['room']
