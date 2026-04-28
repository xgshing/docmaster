from django.contrib.auth import logout
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, response, status, views
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.tokens import RefreshToken

from audit.models import AuditLog
from .models import SessionEvent, User, UserGroup, UserGroupMembership
from .permissions import IsAdminOrSuperAdmin, IsSuperAdmin
from .serializers import (
    ChangePasswordSerializer,
    GroupSerializer,
    LoginSerializer,
    MembershipSerializer,
    ResetPasswordSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
    UserSerializer,
)


class LoginView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        old_session = user.current_session_key
        from .authentication import new_session_id

        sid = new_session_id()
        user.current_session_key = sid
        user.last_login_ip = request.META.get("REMOTE_ADDR")
        user.save(update_fields=["current_session_key", "last_login_ip"])
        if old_session and old_session != sid:
            SessionEvent.objects.filter(user=user, session_key=old_session, invalidated_at__isnull=True).update(
                invalidated_at=timezone.now(), reason="kicked_by_new_login"
            )
        SessionEvent.objects.create(user=user, session_key=sid)

        refresh = RefreshToken.for_user(user)
        refresh["sid"] = sid
        access = refresh.access_token
        access["sid"] = sid
        return response.Response(
            {
                "access": str(access),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            }
        )


class LogoutView(views.APIView):
    def post(self, request):
        if request.user.is_authenticated:
            request.user.current_session_key = ""
            request.user.save(update_fields=["current_session_key"])
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class CurrentUserView(views.APIView):
    def get(self, request):
        return response.Response(UserSerializer(request.user).data)


class UserListCreateView(generics.ListCreateAPIView):
    queryset = User.objects.all().order_by("id")

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAdminOrSuperAdmin()]
        return [IsSuperAdmin()]

    def get_serializer_class(self):
        return UserSerializer if self.request.method == "GET" else UserCreateSerializer

    def perform_create(self, serializer):
        user = serializer.save()
        AuditLog.objects.create(
            actor=self.request.user.username,
            action_type="create_user",
            content=f"创建用户 {user.username}",
            ip_address=self.request.META.get("REMOTE_ADDR", ""),
        )


class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = User.objects.all().order_by("id")

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAdminOrSuperAdmin()]
        return [IsSuperAdmin()]

    def get_serializer_class(self):
        if self.request.method in {"PUT", "PATCH"}:
            return UserUpdateSerializer
        return UserSerializer

    def perform_update(self, serializer):
        user = serializer.save()
        AuditLog.objects.create(
            actor=self.request.user.username,
            action_type="update_user",
            content=f"更新用户 {user.username}",
            ip_address=self.request.META.get("REMOTE_ADDR", ""),
        )

    def perform_destroy(self, instance):
        username = instance.username
        instance.delete()
        AuditLog.objects.create(
            actor=self.request.user.username,
            action_type="delete_user",
            content=f"删除用户 {username}",
            ip_address=self.request.META.get("REMOTE_ADDR", ""),
        )


class ResetPasswordView(views.APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, pk: int):
        user = get_object_or_404(User, pk=pk)
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user.set_password(serializer.validated_data["password"])
        user.save(update_fields=["password"])
        AuditLog.objects.create(
            actor=request.user.username,
            action_type="reset_password",
            content=f"重置用户密码 {user.username}",
            ip_address=request.META.get("REMOTE_ADDR", ""),
        )
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class ChangePasswordView(views.APIView):
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        AuditLog.objects.create(
            actor=request.user.username,
            action_type="change_password",
            content=f"修改个人密码 {request.user.username}",
            ip_address=request.META.get("REMOTE_ADDR", ""),
        )
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class GroupListCreateView(generics.ListCreateAPIView):
    queryset = UserGroup.objects.select_related("creator").all().order_by("name")
    serializer_class = GroupSerializer
    permission_classes = [IsAdminOrSuperAdmin]

    def perform_create(self, serializer):
        group = serializer.save(creator=self.request.user, creator_role=self.request.user.role)
        AuditLog.objects.create(
            actor=self.request.user.username,
            action_type="create_group",
            content=f"创建分组 {group.name}",
            ip_address=self.request.META.get("REMOTE_ADDR", ""),
        )


class GroupDetailView(generics.RetrieveDestroyAPIView):
    queryset = UserGroup.objects.select_related("creator").all()
    serializer_class = GroupSerializer
    permission_classes = [IsAdminOrSuperAdmin]

    def perform_destroy(self, instance):
        if self.request.user.role != "super_admin" and instance.creator_id != self.request.user.id:
            raise PermissionDenied("您没有执行该操作的权限。")
        group_name = instance.name
        instance.delete()
        AuditLog.objects.create(
            actor=self.request.user.username,
            action_type="delete_group",
            content=f"删除分组 {group_name}",
            ip_address=self.request.META.get("REMOTE_ADDR", ""),
        )


class MembershipListCreateView(generics.ListCreateAPIView):
    queryset = UserGroupMembership.objects.select_related("user", "group").all()
    serializer_class = MembershipSerializer
    permission_classes = [IsAdminOrSuperAdmin]

    def perform_create(self, serializer):
        membership = serializer.save()
        AuditLog.objects.create(
            actor=self.request.user.username,
            action_type="assign_group",
            content=f"将用户 {membership.user.username} 分配到分组 {membership.group.name}",
            ip_address=self.request.META.get("REMOTE_ADDR", ""),
        )


class MembershipDetailView(generics.DestroyAPIView):
    queryset = UserGroupMembership.objects.select_related("user", "group").all()
    serializer_class = MembershipSerializer
    permission_classes = [IsAdminOrSuperAdmin]

    def perform_destroy(self, instance):
        AuditLog.objects.create(
            actor=self.request.user.username,
            action_type="remove_group_membership",
            content=f"移除用户 {instance.user.username} 的分组 {instance.group.name}",
            ip_address=self.request.META.get("REMOTE_ADDR", ""),
        )
        instance.delete()
