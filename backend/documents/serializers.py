from rest_framework import serializers

from .models import (
    ArchiveEntry,
    Document,
    DocumentLock,
    ExportJob,
    PersonalLibraryEntry,
    PersonalLibraryMount,
    RecycleBinEntry,
    SharedFolder,
    SharedPermission,
)
from .services import document_permission_level, folder_permission_level


class SharedFolderSerializer(serializers.ModelSerializer):
    creator_name = serializers.CharField(source="creator.username", read_only=True)
    permission = serializers.SerializerMethodField()

    class Meta:
        model = SharedFolder
        fields = [
            "id",
            "name",
            "creator",
            "creator_name",
            "parent",
            "storage_path",
            "is_archived",
            "created_at",
            "permission",
        ]
        read_only_fields = ["creator", "storage_path", "created_at"]

    def get_permission(self, obj):
        request = self.context.get("request")
        return folder_permission_level(request.user, obj) if request else "none"


class SharedPermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SharedPermission
        fields = ["id", "folder", "user", "group", "permission_type"]


class PersonalLibraryMountSerializer(serializers.ModelSerializer):
    class Meta:
        model = PersonalLibraryMount
        fields = ["id", "owner", "name", "source_path", "kind", "created_at", "updated_at"]
        read_only_fields = ["owner", "created_at", "updated_at"]


class DocumentSerializer(serializers.ModelSerializer):
    last_edited_by_name = serializers.CharField(source="last_edited_by.username", read_only=True)
    owner_name = serializers.CharField(source="owner.username", read_only=True)
    permission = serializers.SerializerMethodField()
    folder_name = serializers.CharField(source="folder.name", read_only=True)

    class Meta:
        model = Document
        fields = [
            "id",
            "name",
            "file_type",
            "file_size",
            "storage_path",
            "cos_path",
            "space_type",
            "folder",
            "folder_name",
            "owner",
            "owner_name",
            "last_edited_at",
            "last_edited_by",
            "last_edited_by_name",
            "created_at",
            "is_deleted",
            "permission",
        ]
        read_only_fields = ["file_type", "owner", "last_edited_at", "last_edited_by", "created_at", "is_deleted"]

    def get_permission(self, obj):
        request = self.context.get("request")
        return document_permission_level(request.user, obj) if request else "none"


class PersonalLibraryEntrySerializer(serializers.ModelSerializer):
    mount_name = serializers.CharField(source="mount.name", read_only=True)
    mount_kind = serializers.CharField(source="mount.kind", read_only=True)

    class Meta:
        model = PersonalLibraryEntry
        fields = "__all__"
        read_only_fields = ["indexed_at"]


class RecycleBinEntrySerializer(serializers.ModelSerializer):
    document_name = serializers.CharField(source="document.name", read_only=True)

    class Meta:
        model = RecycleBinEntry
        fields = "__all__"


class DocumentLockSerializer(serializers.ModelSerializer):
    locked_by_name = serializers.CharField(source="locked_by.username", read_only=True)

    class Meta:
        model = DocumentLock
        fields = ["id", "document", "locked_by", "locked_by_name", "session_key", "locked_at"]
        read_only_fields = ["locked_by", "session_key", "locked_at"]


class ArchiveEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = ArchiveEntry
        fields = "__all__"


class ExportJobSerializer(serializers.ModelSerializer):
    document_name = serializers.CharField(source="document.name", read_only=True)

    class Meta:
        model = ExportJob
        fields = "__all__"
