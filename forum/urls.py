from django.urls import path
from . import views, analytics_views
from knox import views as knox_views

urlpatterns = [
    path("community/list", views.CommunityList.as_view(), name="community_list"),
    path("community/create", views.CommunityCreate.as_view(), name="community_create"),
    path(
        "community/<str:community_url>",
        views.CommunityDetail.as_view(),
        name="community_detail",
    ),
    path(
        "community/<str:community_url>/privacy",
        views.CommunityPrivacy.as_view(),
        name="community_privacy",
    ),
    path(
        "community/<str:community_url>/search_key",
        views.SearchKey.as_view(),
        name="search_key",
    ),
    path(
        "community/<str:community_url>/upload_photo",
        views.CommunityUploadPhoto.as_view(),
        name="community_upload_photo",
    ),
    path(
        "community/<str:community_url>/email_invites",
        views.CommunityEmailInvite.as_view(),
        name="community_email_invite",
    ),
    path(
        "community/<str:community_url>/upload_favicon",
        views.CommunityUploadFavicon.as_view(),
        name="community_upload_favicon",
    ),
    path(
        "channel/<int:channel_id>",
        views.ChannelDetail.as_view(),
        name="channel_detail",
    ),
    path(
        "channel/<int:channel_id>/add_members",
        views.ChannelAddMembers.as_view(),
        name="channel_add_members",
    ),
    path(
        "channel/<int:channel_id>/remove_members",
        views.ChannelRemoveMembers.as_view(),
        name="channel_add_members",
    ),
    path("channels", views.ChannelList.as_view(), name="channel_list"),
    path("post/create", views.PostCreate.as_view(), name="post_create"),
    path("post/<int:post_id>", views.PostDetail.as_view(), name="post_detail"),
    path("post/<int:post_id>/vote", views.PostVote.as_view(), name="post_vote"),
    path(
        "post/<int:post_id>/comment",
        views.CommentCreate.as_view(),
        name="comment_create",
    ),
    path("post/<int:post_id>/pin", views.PinPost.as_view(), name="pin_post"),
    path(
        "post/upload_file/<str:filename>",
        views.PostFileUpload.as_view(),
        name="post_upload_file",
    ),
    path(
        "comment/<int:comment_id>", views.CommentDetail.as_view(), name="comment_detail"
    ),
    path(
        "comment/<int:comment_id>/vote",
        views.CommentVote.as_view(),
        name="comment_vote",
    ),
    path(
        "community/<str:community_url>/posts",
        views.CommunityPostList.as_view(),
        name="community_post_list",
    ),
    path(
        "community/<str:community_url>/people",
        views.CommunityPersonList.as_view(),
        name="community_people_list",
    ),
    path(
        "_person/<int:person_id>", views.PersonDetail.as_view(), name="person_detail",
    ),
    path(
        "person/<int:person_id>/upload_photo",
        views.PersonUploadPhoto.as_view(),
        name="person_upload_photo",
    ),
    path(
        "chatrooms/<int:room_id>/messages/create",
        views.CreateMessage.as_view(),
        name="create_message",
    ),
    path(
        "community/<str:community_url>/chatrooms",
        views.ChatRoomList.as_view(),
        name="chatroom_list",
    ),
    path(
        "chatrooms/<int:room_id>/messages",
        views.ChatRoomMessages.as_view(),
        name="chatroom_messages",
    ),
    path(
        "chatrooms/<int:room_id>",
        views.ChatRoomDetail.as_view(),
        name="chatroom_detail",
    ),
    path(
        "chatrooms/<int:room_id>/read",
        views.ChatRoomRead.as_view(),
        name="chatroom_read",
    ),
    path(
        "messages/<int:message_id>",
        views.MessageDetail.as_view(),
        name="message_detail",
    ),
    path("conversations", views.DirectMessageCreate.as_view(), name="direct_messages"),
    path("_login", views.LoginAPI.as_view(), name="login"),
    path("register_user", views.RegisterUser.as_view(), name="register_user"),
    path("self", views.Self.as_view(), name="self"),
    path("notifications", views.Notifications.as_view(), name="notifications"),
    path(
        "notification_check",
        views.ReadNotifications.as_view(),
        name="notification_check",
    ),
    path(
        "notification_frequency",
        views.NotificationFrequency.as_view(),
        name="notification_frequency",
    ),
    path("logout", knox_views.LogoutView.as_view(), name="knox_logout"),
    path(
        "create_user", views.External_CreateUser.as_view(), name="external_create_user"
    ),
    path("google_auth", views.GoogleAuth.as_view(), name="google_auth"),
    path(
        "person/<str:person_email>",
        views.External_PersonDetail.as_view(),
        name="external_person_detail",
    ),
    path(
        "login/<str:person_email>",
        views.External_LoginUser.as_view(),
        name="external_login",
    ),
    path(
        "generate_superadmin_token",
        views.Generate_Superadmin_Token.as_view(),
        name="generate_superadmin_token",
    ),
    path("accept_welcome", views.AcceptWelcome.as_view(), name="accept_welcome"),
    path("active_user", views.ActiveUser.as_view(), name="active_user"),
    path("password_reset", views.PasswordReset.as_view(), name="password_reset"),
    path(
        "request_password_reset/<str:community_url>",
        views.RequestPasswordReset.as_view(),
        name="request_password_reset",
    ),
    # views for the admin analytics
    path("analytics", analytics_views.AnalyticsUsers.as_view(), name="analytics_users"),
]
