from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    ChangePasswordView,
    CurrentUserView,
    GroupDetailView,
    GroupListCreateView,
    LoginView,
    LogoutView,
    MembershipDetailView,
    MembershipListCreateView,
    ResetPasswordView,
    UserDetailView,
    UserListCreateView,
)


urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", CurrentUserView.as_view(), name="me"),
    path("password/change/", ChangePasswordView.as_view(), name="change-password"),
    path("users/", UserListCreateView.as_view(), name="users"),
    path("users/<int:pk>/", UserDetailView.as_view(), name="user-detail"),
    path("users/<int:pk>/reset-password/", ResetPasswordView.as_view(), name="user-reset-password"),
    path("groups/", GroupListCreateView.as_view(), name="groups"),
    path("groups/<int:pk>/", GroupDetailView.as_view(), name="group-detail"),
    path("memberships/", MembershipListCreateView.as_view(), name="memberships"),
    path("memberships/<int:pk>/", MembershipDetailView.as_view(), name="membership-detail"),
]
