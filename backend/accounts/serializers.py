from django.contrib.auth import authenticate
from rest_framework import serializers

from .models import Role, User, UserGroup, UserGroupMembership


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(username=attrs["username"], password=attrs["password"])
        if not user:
            raise serializers.ValidationError("用户名或密码错误。")
        if not user.is_enabled:
            raise serializers.ValidationError("账号已禁用。")
        attrs["user"] = user
        return attrs


class UserSerializer(serializers.ModelSerializer):
    groups = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "reserved_email",
            "role",
            "is_enabled",
            "personal_root",
            "groups",
        ]

    def get_groups(self, obj):
        return [membership.group.name for membership in obj.group_memberships.select_related("group")]


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8, max_length=8)

    class Meta:
        model = User
        fields = ["username", "password", "role", "email", "reserved_email", "first_name", "last_name"]

    def validate_role(self, value):
        request = self.context["request"]
        if request.user.role != Role.SUPER_ADMIN and value != Role.USER:
            raise serializers.ValidationError("仅超级管理员可创建管理员账号。")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["username", "role", "email", "reserved_email", "first_name", "last_name", "is_enabled"]

    def validate_role(self, value):
        request = self.context["request"]
        if request.user.role != Role.SUPER_ADMIN and value != Role.USER:
            raise serializers.ValidationError("仅超级管理员可以调整管理员角色。")
        return value


class ResetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, min_length=8, max_length=8)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8, max_length=8)

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError("当前密码不正确。")
        return attrs


class GroupSerializer(serializers.ModelSerializer):
    creator_name = serializers.CharField(source="creator.username", read_only=True)

    class Meta:
        model = UserGroup
        fields = ["id", "name", "creator", "creator_name", "creator_role", "parent", "created_at"]
        read_only_fields = ["creator", "creator_role", "created_at"]


class MembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserGroupMembership
        fields = ["id", "user", "group", "created_at"]
        read_only_fields = ["created_at"]
