from django.contrib import admin
from .models import *

# Register your models here.
admin.site.register(Community)


class PersonAdmin(admin.ModelAdmin):
    raw_id_fields = (
        "user",
        "community",
    )


admin.site.register(Person, PersonAdmin)


class CommunityHostAdmin(admin.ModelAdmin):
    raw_id_fields = ("community",)


admin.site.register(CommunityHost, CommunityHostAdmin)


class PostAdmin(admin.ModelAdmin):
    raw_id_fields = ("upvotes", "owner", "community", "channel")


admin.site.register(Post, PostAdmin)


class ChatRoomAdmin(admin.ModelAdmin):
    raw_id_fields = ("community", "private_members")


admin.site.register(ChatRoom, ChatRoomAdmin)


class ChannelAdmin(admin.ModelAdmin):
    raw_id_fields = ("community", "private_members")


admin.site.register(Channel, ChannelAdmin)
