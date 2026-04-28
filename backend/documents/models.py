from django.conf import settings
from django.db import models

from accounts.models import User, UserGroup


class SpaceType(models.TextChoices):
    PERSONAL = "personal", "个人文档库"
    SHARED = "shared", "共享空间"


class PermissionType(models.TextChoices):
    VIEW = "view", "查看"
    EDIT = "edit", "编辑"


class FileType(models.TextChoices):
    WORD = "word", "Word"
    EXCEL = "excel", "Excel"
    PPT = "ppt", "PPT"
    PDF = "pdf", "PDF"
    IMAGE = "image", "图片"
    OTHER = "other", "其他"


class PersonalLibraryMountKind(models.TextChoices):
    FOLDER = "folder", "文件夹"
    FILE = "file", "文件"


class SharedFolder(models.Model):
    name = models.CharField(max_length=255)
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name="shared_folders")
    parent = models.ForeignKey("self", blank=True, null=True, on_delete=models.CASCADE, related_name="children")
    storage_path = models.CharField(max_length=1024)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("parent", "name")

    def __str__(self) -> str:
        return self.name


class SharedPermission(models.Model):
    folder = models.ForeignKey(SharedFolder, on_delete=models.CASCADE, related_name="permissions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, blank=True, null=True, related_name="shared_permissions")
    group = models.ForeignKey(
        UserGroup, on_delete=models.CASCADE, blank=True, null=True, related_name="shared_permissions"
    )
    permission_type = models.CharField(max_length=8, choices=PermissionType.choices)


class PersonalLibraryMount(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="personal_mounts")
    name = models.CharField(max_length=255)
    source_path = models.CharField(max_length=512)
    kind = models.CharField(max_length=16, choices=PersonalLibraryMountKind.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("owner", "source_path")

    def __str__(self) -> str:
        return self.name


class PersonalLibraryEntry(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="personal_entries")
    mount = models.ForeignKey(
        PersonalLibraryMount,
        on_delete=models.CASCADE,
        related_name="entries",
        blank=True,
        null=True,
    )
    root_directory = models.CharField(max_length=1024)
    relative_path = models.CharField(max_length=1024)
    # Indexed with owner in a unique constraint; keep within MySQL utf8mb4 index limits.
    absolute_path = models.CharField(max_length=512)
    is_directory = models.BooleanField(default=False)
    file_size = models.BigIntegerField(default=0)
    last_modified_at = models.DateTimeField(blank=True, null=True)
    indexed_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        unique_together = ("owner", "absolute_path")


class Document(models.Model):
    name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=16, choices=FileType.choices, default=FileType.OTHER)
    file_size = models.BigIntegerField(default=0)
    storage_path = models.CharField(max_length=1024)
    cos_path = models.CharField(max_length=1024, blank=True)
    space_type = models.CharField(max_length=16, choices=SpaceType.choices)
    folder = models.ForeignKey(SharedFolder, on_delete=models.CASCADE, blank=True, null=True, related_name="documents")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_documents")
    last_edited_at = models.DateTimeField(auto_now=True)
    last_edited_by = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["name"], name="uq_shared_document_name_global", condition=models.Q(space_type="shared"))
        ]


class RecycleBinEntry(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="recycle_entries")
    original_path = models.CharField(max_length=1024)
    recycled_name = models.CharField(max_length=255, blank=True)
    file_size = models.BigIntegerField(default=0)
    deleted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="deleted_documents")
    deleted_at = models.DateTimeField(auto_now_add=True)
    expire_at = models.DateTimeField()
    moved_date = models.CharField(max_length=16)
    moved_time = models.CharField(max_length=16)
    folder = models.ForeignKey(SharedFolder, on_delete=models.SET_NULL, blank=True, null=True)


class DocumentLock(models.Model):
    document = models.OneToOneField(Document, on_delete=models.CASCADE, related_name="lock")
    locked_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="document_locks")
    session_key = models.CharField(max_length=64)
    locked_at = models.DateTimeField(auto_now_add=True)


class ArchiveEntry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="archive_entries")
    document = models.ForeignKey(Document, on_delete=models.CASCADE, blank=True, null=True)
    folder = models.ForeignKey(SharedFolder, on_delete=models.CASCADE, blank=True, null=True)
    archived_at = models.DateTimeField(auto_now_add=True)
    restored_at = models.DateTimeField(blank=True, null=True)


class ExportJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        COMPLETED = "completed", "已完成"
        FAILED = "failed", "失败"

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="export_jobs")
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="export_jobs")
    format = models.CharField(max_length=32, default="pdf")
    output_path = models.CharField(max_length=1024, blank=True)
    cos_path = models.CharField(max_length=1024, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)


SUPPORTED_EXTENSIONS = {
    ".doc": FileType.WORD,
    ".docx": FileType.WORD,
    ".xls": FileType.EXCEL,
    ".xlsx": FileType.EXCEL,
    ".ppt": FileType.PPT,
    ".pptx": FileType.PPT,
    ".pdf": FileType.PDF,
    ".jpg": FileType.IMAGE,
    ".jpeg": FileType.IMAGE,
    ".png": FileType.IMAGE,
}
