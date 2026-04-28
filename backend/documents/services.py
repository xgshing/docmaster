from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import json
import ntpath
import posixpath
import shutil
import ssl
import urllib.parse
import urllib.request
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from audit.models import AccessLog, AuditLog, ShareHistory
from .models import (
    ArchiveEntry,
    Document,
    ExportJob,
    PersonalLibraryEntry,
    PersonalLibraryMount,
    PersonalLibraryMountKind,
    RecycleBinEntry,
    SharedFolder,
    SharedPermission,
    SUPPORTED_EXTENSIONS,
)
from .onlyoffice import decode_jwt, encode_jwt
from .storage import (
    build_document_cos_key,
    build_export_cos_key,
    cache_document_from_cos,
    copy_to_export,
    persist_document_to_storage,
    remove_local_file,
    storage_client,
)


PERMISSION_RANK = {"none": 0, "view": 1, "edit": 2, "manage": 3}
EDITOR_TYPES = {
    "word": "word",
    "excel": "cell",
    "ppt": "slide",
}


def detect_file_type(filename: str) -> str:
    return SUPPORTED_EXTENSIONS.get(Path(filename).suffix.lower(), "other")


def move_personal_file_to_trash(source_path: str) -> str:
    source = Path(source_path)
    stamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    target = settings.DOCMASTER_LOCAL_TRASH_ROOT / f"{source.stem}_{stamp}{source.suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return str(target)


def sanitize_name(name: str) -> str:
    return Path(name).name.strip()


def mount_display_name(source_path: str) -> str:
    cleaned = source_path.replace("\\", "/").rstrip("/")
    return cleaned.split("/")[-1] if cleaned else source_path


def get_user_group_ids(user) -> list[int]:
    if not getattr(user, "is_authenticated", False):
        return []
    return list(user.group_memberships.values_list("group_id", flat=True))


def highest_permission(values) -> str:
    result = "none"
    for value in values:
        if PERMISSION_RANK.get(value, 0) > PERMISSION_RANK[result]:
            result = value
    return result


def folder_permission_level(user, folder: SharedFolder | None) -> str:
    if not folder or not getattr(user, "is_authenticated", False):
        return "none"
    if user.role == Role.SUPER_ADMIN:
        return "manage"
    if folder.space_type == "personal":
        return "manage" if folder.creator_id == user.id else "none"
    if folder.creator_id == user.id:
        return "manage"

    group_ids = get_user_group_ids(user)
    current = folder
    visited_ids: set[int] = set()
    while current:
        if current.id in visited_ids:
            break
        visited_ids.add(current.id)
        direct_permissions = current.permissions.filter(user=user).values_list("permission_type", flat=True)
        if direct_permissions:
            return highest_permission(direct_permissions)
        if group_ids:
            group_permissions = current.permissions.filter(group_id__in=group_ids).values_list(
                "permission_type", flat=True
            )
            if group_permissions:
                return highest_permission(group_permissions)
        current = current.parent
    return "none"


def document_permission_level(user, document: Document) -> str:
    if not getattr(user, "is_authenticated", False) or document.is_deleted:
        return "none"
    if user.role == Role.SUPER_ADMIN:
        return "manage"
    if document.space_type == "personal":
        return "manage" if document.owner_id == user.id else "none"
    if document.folder_id:
        return folder_permission_level(user, document.folder)
    return "edit" if document.owner_id == user.id else "none"


def ensure_permission(user, document: Document | None = None, folder: SharedFolder | None = None, level: str = "view"):
    actual = folder_permission_level(user, folder) if folder else document_permission_level(user, document)
    if PERMISSION_RANK[actual] < PERMISSION_RANK[level]:
        raise PermissionDenied("您没有执行该操作的权限。")
    return actual


def get_accessible_documents(user):
    if not getattr(user, "is_authenticated", False):
        return Document.objects.none()
    if user.role == Role.SUPER_ADMIN:
        return Document.objects.select_related("owner", "folder", "last_edited_by").filter(is_deleted=False)

    group_ids = get_user_group_ids(user)
    visible_folders = SharedFolder.objects.filter(
        Q(creator=user)
        | Q(permissions__user=user)
        | Q(permissions__group_id__in=group_ids)
    ).distinct()

    return Document.objects.select_related("owner", "folder", "last_edited_by").filter(
        Q(space_type="personal", owner=user) | Q(space_type="shared", folder__in=visible_folders),
        is_deleted=False,
    ).distinct()


def get_accessible_folders(user):
    if not getattr(user, "is_authenticated", False):
        return SharedFolder.objects.none()
    if user.role == Role.SUPER_ADMIN:
        return SharedFolder.objects.select_related("creator", "parent").all().order_by("name")
    group_ids = get_user_group_ids(user)
    return (
        SharedFolder.objects.select_related("creator", "parent")
        .filter(
            Q(space_type="personal", creator=user)
            | Q(space_type="shared", creator=user)
            | Q(space_type="shared", permissions__user=user)
            | Q(space_type="shared", permissions__group_id__in=group_ids)
        )
        .distinct()
        .order_by("name")
    )


def get_accessible_folders_for_space(user, space_type: str):
    return get_accessible_folders(user).filter(space_type=space_type)


def unique_shared_name(name: str, conflict_strategy: str = "cancel") -> tuple[str, Document | None]:
    existing = Document.objects.filter(space_type="shared", name=name, is_deleted=False).first()
    if not existing:
        return name, None

    if conflict_strategy == "rename":
        base = Path(name).stem
        suffix = Path(name).suffix
        dated_name = f"{base}_{timezone.localtime().strftime('%Y%m%d')}{suffix}"
        return unique_shared_name(dated_name, "overwrite")
    if conflict_strategy == "overwrite":
        return name, existing
    raise ValidationError("共享空间存在同名文件，请选择重命名或覆盖。")


def write_uploaded_file(target: Path, uploaded_file):
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        for chunk in uploaded_file.chunks():
            handle.write(chunk)


def build_storage_path(folder: SharedFolder | None, filename: str) -> Path:
    if folder:
        root = Path(folder.storage_path)
    else:
        root = settings.DOCMASTER_SHARED_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root / filename


def ensure_document_cached(document: Document) -> Path:
    target = Path(document.storage_path)
    if target.exists():
        return target
    if document.cos_path:
        return Path(cache_document_from_cos(document.cos_path, document.storage_path))
    return target


def store_shared_document(uploaded_file, folder: SharedFolder | None, filename: str) -> tuple[str, str]:
    target = build_storage_path(folder, filename)
    write_uploaded_file(target, uploaded_file)
    folder_key = str(target.parent.relative_to(settings.DOCMASTER_SHARED_ROOT)) if target.parent != settings.DOCMASTER_SHARED_ROOT else ""
    cos_key = build_document_cos_key(folder_key, filename)
    location = persist_document_to_storage(str(target), cos_key)
    return location.local_path, location.cos_path


def create_or_replace_shared_document(*, uploaded_file, owner, folder: SharedFolder | None, filename: str, conflict_strategy: str):
    safe_name = sanitize_name(filename)
    resolved_name, existing = unique_shared_name(safe_name, conflict_strategy)
    if existing:
        recycle_shared_document(existing, owner, reason="overwrite_shared_document")

    storage_path, cos_path = store_shared_document(uploaded_file, folder, resolved_name)
    document = Document.objects.create(
        name=resolved_name,
        file_type=detect_file_type(resolved_name),
        file_size=getattr(uploaded_file, "size", 0),
        storage_path=storage_path,
        cos_path=cos_path,
        space_type="shared",
        folder=folder,
        owner=owner,
        last_edited_by=owner,
    )
    ShareHistory.objects.create(document=document, sharer=owner, shared_with=folder.name if folder else "shared-root")
    AuditLog.objects.create(
        actor=owner.username,
        action_type="publish_shared_document",
        content=f"发布共享文档 {document.name}",
        ip_address="",
    )
    return document


def recycle_shared_document(document: Document, deleted_by, reason: str = "delete_shared_document"):
    if document.is_deleted:
        return
    now = timezone.localtime()
    recycle_name = f"{Path(document.name).stem}_{now.strftime('%Y%m%d')}_{now.strftime('%H%M%S')}{Path(document.name).suffix}"
    RecycleBinEntry.objects.create(
        document=document,
        original_path=document.storage_path,
        recycled_name=recycle_name,
        file_size=document.file_size,
        deleted_by=deleted_by,
        expire_at=now + timedelta(days=30),
        moved_date=now.strftime("%Y%m%d"),
        moved_time=now.strftime("%H%M%S"),
        folder=document.folder,
    )
    document.is_deleted = True
    document.save(update_fields=["is_deleted", "last_edited_at"])
    AuditLog.objects.create(
        actor=deleted_by.username,
        action_type=reason,
        content=f"回收站移入共享文档 {document.name}",
        ip_address="",
    )


def recycle_shared_folder(folder: SharedFolder, deleted_by):
    visited_ids: set[int] = set()

    def collect_descendant_ids(current: SharedFolder) -> list[int]:
        if current.id in visited_ids:
            return []
        visited_ids.add(current.id)
        output = [current.id]
        for child in current.children.all():
            output.extend(collect_descendant_ids(child))
        return output

    folder_ids = collect_descendant_ids(folder)
    documents = list(
        Document.objects.select_related("folder")
        .filter(folder_id__in=folder_ids, is_deleted=False)
        .order_by("id")
    )
    for document in documents:
        recycle_shared_document(document, deleted_by, reason="delete_shared_folder_document")

    # Detach recycled documents before deleting folders so the recycle-bin
    # records and soft-deleted documents are not removed by CASCADE.
    Document.objects.filter(id__in=[document.id for document in documents]).update(folder=None)
    SharedFolder.objects.filter(id__in=folder_ids).delete()
    AuditLog.objects.create(
        actor=deleted_by.username,
        action_type="delete_shared_folder",
        content=f"Recycle shared folder {folder.name}",
        ip_address="",
    )


def restore_recycle_entry(entry: RecycleBinEntry, restored_by):
    document = entry.document
    document.is_deleted = False
    document.last_edited_by = restored_by
    document.save(update_fields=["is_deleted", "last_edited_by", "last_edited_at"])
    AuditLog.objects.create(
        actor=restored_by.username,
        action_type="restore_shared_document",
        content=f"恢复共享文档 {document.name}",
        ip_address="",
    )
    entry.delete()


def purge_recycle_entry(entry: RecycleBinEntry, deleted_by):
    document = entry.document
    remove_local_file(document.storage_path)
    storage_client.delete_file(document.cos_path)
    AuditLog.objects.create(
        actor=deleted_by.username,
        action_type="purge_shared_document",
        content=f"彻底删除共享文档 {document.name}",
        ip_address="",
    )
    document.delete()


def create_archive_entry(user, document: Document | None = None, folder: SharedFolder | None = None):
    return ArchiveEntry.objects.get_or_create(user=user, document=document, folder=folder, restored_at__isnull=True)[0]


def restore_archive_entry(entry: ArchiveEntry):
    entry.restored_at = timezone.now()
    entry.save(update_fields=["restored_at"])


def document_file_path(document: Document) -> Path:
    return ensure_document_cached(document)


def document_extension(document: Document) -> str:
    return document_file_path(document).suffix.lower().lstrip(".")


def document_download_url(request, document: Document) -> str:
    token = _encode_document_token(document.pk, "download")
    url = reverse("document-download", args=[document.pk])
    return request.build_absolute_uri(f"{url}?token={token}")


def _encode_document_token(document_id: int, action: str) -> str:
    return encode_jwt({"document_id": document_id, "action": action}, settings.SECRET_KEY)


def _decode_document_token(token: str, document_id: int, action: str) -> bool:
    try:
        payload = decode_jwt(token, settings.SECRET_KEY)
    except ValueError:
        return False
    return payload.get("document_id") == document_id and payload.get("action") == action


def _encode_personal_session_token(session_id: str, action: str) -> str:
    return encode_jwt({"session_id": session_id, "action": action}, settings.SECRET_KEY)


def _decode_personal_session_token(token: str, session_id: str, action: str) -> bool:
    try:
        payload = decode_jwt(token, settings.SECRET_KEY)
    except ValueError:
        return False
    return payload.get("session_id") == session_id and payload.get("action") == action


def _personal_session_dir(user_id: int, entry_id: int) -> Path:
    return settings.DOCMASTER_PERSONAL_SESSION_ROOT / str(user_id) / str(entry_id)


def _personal_session_meta_path(session_dir: Path) -> Path:
    return session_dir / "session.json"


def _load_personal_session_meta(session_dir: Path) -> dict:
    return json.loads(_personal_session_meta_path(session_dir).read_text("utf-8"))


def _save_personal_session_meta(session_dir: Path, metadata: dict):
    _personal_session_meta_path(session_dir).write_text(
        json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
        "utf-8",
    )


def _resolve_personal_entry_root(entry: PersonalLibraryEntry) -> Path:
    root_source = entry.mount.source_path if entry.mount else entry.root_directory
    root = _normalize_client_path(root_source)
    absolute = _normalize_client_path(entry.absolute_path)
    if not _client_path_is_within_root(absolute, root):
        raise PermissionDenied("个人文档路径校验失败。")
    return Path(root)


def _normalize_client_path(path_value: str) -> str:
    raw = (path_value or "").strip()
    if not raw:
        return ""
    looks_windows = "\\" in raw or (len(raw) >= 2 and raw[1] == ":")
    if looks_windows:
        normalized = ntpath.normcase(ntpath.normpath(raw))
        return normalized.rstrip("\\") if normalized not in {"\\", ""} else normalized
    normalized = posixpath.normpath(raw)
    return normalized.rstrip("/") if normalized not in {"/", ""} else normalized


def _client_path_is_within_root(absolute_path: str, root_path: str) -> bool:
    if not absolute_path or not root_path:
        return False
    if absolute_path == root_path:
        return True
    separator = "\\" if "\\" in root_path or (len(root_path) >= 2 and root_path[1] == ":") else "/"
    prefix = root_path if root_path.endswith(separator) else f"{root_path}{separator}"
    return absolute_path.startswith(prefix)


def personal_file_type(entry: PersonalLibraryEntry) -> str:
    return detect_file_type(entry.absolute_path)


def list_personal_library(user) -> tuple[list[PersonalLibraryMount], list[PersonalLibraryEntry]]:
    mounts = list(PersonalLibraryMount.objects.filter(owner=user).order_by("created_at", "id"))
    entries = list(
        PersonalLibraryEntry.objects.select_related("mount")
        .filter(owner=user, is_deleted=False)
        .order_by("mount_id", "relative_path", "id")
    )
    return mounts, entries


def create_or_sync_personal_mount(
    user,
    *,
    source_path: str,
    kind: str,
    entries: list[dict] | None = None,
    file_info: dict | None = None,
) -> PersonalLibraryMount:
    normalized_source = str(source_path).strip()
    mount, _created = PersonalLibraryMount.objects.update_or_create(
        owner=user,
        source_path=normalized_source,
        defaults={
            "name": mount_display_name(normalized_source),
            "kind": kind,
        },
    )

    if kind == PersonalLibraryMountKind.FILE:
        info = file_info or {}
        defaults = {
            "mount": mount,
            "root_directory": normalized_source,
            "relative_path": "",
            "is_directory": False,
            "file_size": info.get("file_size", 0),
            "last_modified_at": info.get("last_modified_at"),
            "is_deleted": False,
        }
        PersonalLibraryEntry.objects.update_or_create(
            owner=user,
            absolute_path=normalized_source,
            defaults=defaults,
        )
        mount.entries.exclude(absolute_path=normalized_source).update(is_deleted=True)
        return mount

    existing = {
        item.absolute_path: item
        for item in PersonalLibraryEntry.objects.filter(owner=user, mount=mount)
    }
    incoming_paths = set()
    for entry in entries or []:
        absolute_path = str(Path(entry["absolute_path"]))
        incoming_paths.add(absolute_path)
        defaults = {
            "mount": mount,
            "root_directory": normalized_source,
            "relative_path": entry["relative_path"],
            "is_directory": entry.get("is_directory", False),
            "file_size": entry.get("file_size", 0),
            "last_modified_at": entry.get("last_modified_at"),
            "is_deleted": False,
        }
        PersonalLibraryEntry.objects.update_or_create(
            owner=user,
            absolute_path=absolute_path,
            defaults=defaults,
        )
    for absolute_path, instance in existing.items():
        if absolute_path not in incoming_paths:
            instance.is_deleted = True
            instance.save(update_fields=["is_deleted", "indexed_at"])
    return mount


def sync_personal_mount(mount: PersonalLibraryMount, *, entries: list[dict] | None = None, file_info: dict | None = None):
    return create_or_sync_personal_mount(
        mount.owner,
        source_path=mount.source_path,
        kind=mount.kind,
        entries=entries,
        file_info=file_info,
    )


def create_personal_onlyoffice_session(entry: PersonalLibraryEntry, uploaded_file) -> dict:
    _resolve_personal_entry_root(entry)
    file_type = personal_file_type(entry)
    document_type = EDITOR_TYPES.get(file_type)
    if not document_type:
        raise ValidationError("当前文件类型不支持 OnlyOffice 在线编辑。")

    session_dir = _personal_session_dir(entry.owner_id, entry.pk)
    if session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)

    filename = sanitize_name(entry.relative_path or Path(entry.absolute_path).name)
    stored_path = session_dir / filename
    write_uploaded_file(stored_path, uploaded_file)

    session_id = uuid.uuid4().hex
    now = timezone.now()
    metadata = {
        "session_id": session_id,
        "entry_id": entry.pk,
        "user_id": entry.owner_id,
        "name": filename,
        "file_type": file_type,
        "document_type": document_type,
        "stored_path": str(stored_path),
        "revision": 0,
        "updated_at": now.isoformat(),
    }
    _save_personal_session_meta(session_dir, metadata)
    return metadata


def get_personal_onlyoffice_session(session_id: str) -> tuple[dict, Path]:
    session_roots = settings.DOCMASTER_PERSONAL_SESSION_ROOT.glob("*/*/session.json")
    for meta_path in session_roots:
        metadata = json.loads(meta_path.read_text("utf-8"))
        if metadata.get("session_id") == session_id:
            session_dir = meta_path.parent
            stored_path = Path(metadata["stored_path"])
            if not stored_path.exists():
                raise ValidationError("个人文档编辑会话文件不存在。")
            return metadata, session_dir
    raise ValidationError("个人文档编辑会话不存在。")


def personal_session_download_url(request, session_id: str) -> str:
    token = _encode_personal_session_token(session_id, "download")
    url = reverse("personal-session-download", args=[session_id])
    return request.build_absolute_uri(f"{url}?token={token}")


def personal_session_callback_url(request, session_id: str) -> str:
    token = _encode_personal_session_token(session_id, "callback")
    url = reverse("personal-session-onlyoffice-callback", args=[session_id])
    return request.build_absolute_uri(f"{url}?token={token}")


def build_personal_onlyoffice_payload(request, entry: PersonalLibraryEntry, user, metadata: dict) -> dict:
    if entry.owner_id != user.id:
        raise PermissionDenied("您没有执行该操作的权限。")

    payload = {
        "document": {
            "fileType": Path(metadata["name"]).suffix.lower().lstrip("."),
            "key": metadata["session_id"],
            "title": metadata["name"],
            "url": personal_session_download_url(request, metadata["session_id"]),
            "permissions": {
                "edit": True,
                "download": True,
                "print": True,
            },
        },
        "documentType": metadata["document_type"],
        "editorConfig": {
            "callbackUrl": personal_session_callback_url(request, metadata["session_id"]),
            "lang": "zh-CN",
            "mode": "edit",
            "user": {
                "id": str(user.pk),
                "name": user.username,
            },
            "customization": {
                "autosave": True,
                "forcesave": True,
            },
        },
    }
    if settings.DOCMASTER_ONLYOFFICE_JWT_SECRET:
        payload["token"] = encode_jwt(payload, settings.DOCMASTER_ONLYOFFICE_JWT_SECRET)
    return payload


def verify_personal_session_token(token: str, session_id: str, action: str) -> bool:
    if not token:
        return False
    return _decode_personal_session_token(token, session_id, action)


def verify_document_token(token: str, document_id: int, action: str) -> bool:
    if not token:
        return False
    return _decode_document_token(token, document_id, action)


def save_personal_onlyoffice_callback(session_id: str, payload: dict) -> dict:
    metadata, session_dir = get_personal_onlyoffice_session(session_id)
    status_code = payload.get("status")
    file_url = payload.get("url")
    if status_code not in {2, 6, 7} or not file_url:
        return metadata

    target = Path(metadata["stored_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(fetch_remote_binary(file_url))
    metadata["revision"] = int(metadata.get("revision", 0)) + 1
    metadata["updated_at"] = timezone.now().isoformat()
    _save_personal_session_meta(session_dir, metadata)
    return metadata


def trigger_personal_onlyoffice_forcesave(session_id: str) -> dict:
    metadata, _session_dir = get_personal_onlyoffice_session(session_id)
    base_url = settings.DOCMASTER_ONLYOFFICE_URL.rstrip("/")
    if not base_url:
        raise ValidationError("OnlyOffice 未配置。")

    payload = {
        "c": "forcesave",
        "key": metadata["session_id"],
        "userdata": str(metadata["entry_id"]),
    }
    request_payload = payload
    if settings.DOCMASTER_ONLYOFFICE_JWT_SECRET:
        request_payload = {"token": encode_jwt(payload, settings.DOCMASTER_ONLYOFFICE_JWT_SECRET)}

    body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    shardkey = urllib.parse.quote(str(metadata["session_id"]))
    candidate_urls = [
        f"{base_url}/command?shardkey={shardkey}",
        f"{base_url}/coauthoring/CommandService.ashx?shardkey={shardkey}",
    ]
    headers = {"Content-Type": "application/json"}
    last_error = None

    for target_url in candidate_urls:
        request_obj = urllib.request.Request(target_url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request_obj, context=_ssl_context()) as response:
                payload_text = response.read().decode("utf-8")
                result = json.loads(payload_text or "{}")
                error_code = int(result.get("error", -1))
                if error_code not in {0, 4}:
                    raise ValidationError(f"OnlyOffice 强制保存失败，错误码 {error_code}。")
                return result
        except HTTPError as exc:
            if exc.code == 404:
                last_error = exc
                continue
            detail = exc.read().decode("utf-8", errors="ignore")
            raise ValidationError(f"OnlyOffice 强制保存失败: {detail or exc.reason}") from exc
        except URLError as exc:
            last_error = exc

    raise ValidationError(f"OnlyOffice 强制保存失败: {last_error}") from last_error

def onlyoffice_mode(permission: str) -> str:
    return "edit" if PERMISSION_RANK[permission] >= PERMISSION_RANK["edit"] else "view"


def build_onlyoffice_payload(request, document: Document, user):
    permission = document_permission_level(user, document)
    if permission == "none":
        raise PermissionDenied("您没有执行该操作的权限。")

    ext = document_extension(document)
    document_type = EDITOR_TYPES.get(document.file_type)
    if not document_type:
        raise ValidationError("当前文件类型不支持 OnlyOffice 在线编辑。")

    callback_url = request.build_absolute_uri(reverse("document-onlyoffice-callback", args=[document.pk]))
    editor_key = f"{document.pk}-{int(document.last_edited_at.timestamp())}-{document.file_size}"
    mode = onlyoffice_mode(permission)
    payload = {
        "document": {
            "fileType": ext,
            "key": editor_key,
            "title": document.name,
            "url": document_download_url(request, document),
            "permissions": {
                "edit": mode == "edit",
                "download": True,
                "print": True,
            },
        },
        "documentType": document_type,
        "editorConfig": {
            "callbackUrl": callback_url,
            "lang": "zh-CN",
            "mode": mode,
            "user": {
                "id": str(user.pk),
                "name": user.username,
            },
            "customization": {
                "autosave": True,
                "forcesave": True,
            },
        },
    }
    if settings.DOCMASTER_ONLYOFFICE_JWT_SECRET:
        payload["token"] = encode_jwt(payload, settings.DOCMASTER_ONLYOFFICE_JWT_SECRET)
    return payload


def _ssl_context():
    if settings.DOCMASTER_ONLYOFFICE_VERIFY_SSL:
        return None
    return ssl._create_unverified_context()


def fetch_remote_binary(file_url: str) -> bytes:
    parsed = urlparse(file_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValidationError("OnlyOffice 回调地址无效。")
    with urllib.request.urlopen(file_url, context=_ssl_context()) as source:
        return source.read()


def save_onlyoffice_callback(document: Document, payload: dict):
    status_code = payload.get("status")
    file_url = payload.get("url")
    if status_code not in {2, 6, 7} or not file_url:
        return
    target = Path(document.storage_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(fetch_remote_binary(file_url))
    location = persist_document_to_storage(str(target), document.cos_path or build_document_cos_key("", document.name))
    document.storage_path = location.local_path
    document.cos_path = location.cos_path
    document.file_size = target.stat().st_size if target.exists() else document.file_size
    document.save(update_fields=["storage_path", "cos_path", "file_size", "last_edited_at"])


def verify_onlyoffice_callback(request) -> bool:
    if not settings.DOCMASTER_ONLYOFFICE_JWT_SECRET:
        return True
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token:
        token = request.data.get("token") if hasattr(request, "data") else ""
    if not token:
        return False
    try:
        decode_jwt(token, settings.DOCMASTER_ONLYOFFICE_JWT_SECRET)
    except ValueError:
        return False
    return True


def integration_snapshot():
    return {
        "storage_root": str(settings.DOCMASTER_STORAGE_ROOT),
        "shared_root": str(settings.DOCMASTER_SHARED_ROOT),
        "export_root": str(settings.DOCMASTER_EXPORT_ROOT),
        "cos_enabled": storage_client.enabled,
        "onlyoffice_url": settings.DOCMASTER_ONLYOFFICE_URL,
        "onlyoffice_jwt_enabled": bool(settings.DOCMASTER_ONLYOFFICE_JWT_SECRET),
    }


def append_access_log(document: Document, user, action_type: str):
    AccessLog.objects.create(document=document, visitor=user, action_type=action_type)


def serialize_tree(folders, documents, user):
    children_by_parent: dict[int | None, list[dict]] = {}
    for folder in folders:
        permission = folder_permission_level(user, folder)
        payload = {
            "id": folder.id,
            "kind": "folder",
            "name": folder.name,
            "parent": folder.parent_id,
            "creator_name": folder.creator.username,
            "created_at": folder.created_at,
            "permission": permission,
        }
        children_by_parent.setdefault(folder.parent_id, []).append(payload)

    for document in documents:
        permission = document_permission_level(user, document)
        payload = {
            "id": document.id,
            "kind": "document",
            "name": document.name,
            "parent": document.folder_id,
            "file_type": document.file_type,
            "file_size": document.file_size,
            "last_edited_at": document.last_edited_at,
            "last_edited_by_name": document.last_edited_by.username if document.last_edited_by else "",
            "permission": permission,
        }
        children_by_parent.setdefault(document.folder_id, []).append(payload)

    for items in children_by_parent.values():
        items.sort(key=lambda item: (item["kind"] != "folder", item["name"].lower()))
    return children_by_parent.get(None, []), children_by_parent


def prune_expired_recycle_entries():
    expired_entries = RecycleBinEntry.objects.select_related("document").filter(expire_at__lt=timezone.now())
    for entry in expired_entries:
        purge_recycle_entry(entry, entry.deleted_by)


def prune_expired_logs():
    cutoff = timezone.now() - timedelta(days=365)
    AuditLog.objects.filter(operation_time__lt=cutoff).delete()
    AccessLog.objects.filter(visited_at__lt=cutoff).delete()
    ShareHistory.objects.filter(shared_at__lt=cutoff).delete()


def parse_callback_body(raw_body: bytes) -> dict:
    if not raw_body:
        return {}
    return json.loads(raw_body.decode("utf-8"))


def export_document_to_pdf(request, document: Document, user) -> ExportJob:
    ensure_permission(user, document=document, level="view")
    export_job = ExportJob.objects.create(document=document, requested_by=user, format="pdf")
    source = document_file_path(document)
    target = settings.DOCMASTER_EXPORT_ROOT / f"{document.pk}_{timezone.localtime().strftime('%Y%m%d%H%M%S')}.pdf"

    try:
        if document.file_type in {"pdf", "image"}:
            output_path = copy_to_export(str(source), str(target))
        elif settings.DOCMASTER_ONLYOFFICE_URL:
            output_path = convert_document_via_onlyoffice(request, document, target)
        else:
            raise ValidationError("OnlyOffice 未配置，无法导出 Office 文档为 PDF。")
        cos_key = build_export_cos_key(document.pk, Path(output_path).name)
        location = persist_document_to_storage(output_path, cos_key)
        export_job.output_path = location.local_path
        export_job.cos_path = location.cos_path
        export_job.status = ExportJob.Status.COMPLETED
        export_job.completed_at = timezone.now()
        export_job.save(update_fields=["output_path", "cos_path", "status", "completed_at"])
    except Exception as exc:  # pragma: no cover - integration branch
        export_job.status = ExportJob.Status.FAILED
        export_job.error_message = str(exc)
        export_job.save(update_fields=["status", "error_message"])
        raise

    append_access_log(document, user, "export_pdf")
    return export_job


def convert_document_via_onlyoffice(request, document: Document, output_path: Path) -> str:
    conversion_url = urljoin(settings.DOCMASTER_ONLYOFFICE_URL.rstrip("/") + "/", "ConvertService.ashx")
    payload = {
        "async": False,
        "filetype": document_extension(document),
        "key": f"export-{document.pk}-{int(timezone.now().timestamp())}",
        "outputtype": "pdf",
        "title": document.name,
        "url": document_download_url(request, document),
    }
    request_body = payload
    headers = {"Content-Type": "application/json"}
    if settings.DOCMASTER_ONLYOFFICE_JWT_SECRET:
        token = encode_jwt(payload, settings.DOCMASTER_ONLYOFFICE_JWT_SECRET)
        request_body = {"token": token}
        headers["Authorization"] = f"Bearer {token}"
    raw_request = urllib.request.Request(
        conversion_url,
        data=json.dumps(request_body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(raw_request, context=_ssl_context()) as response_obj:
            result = json.loads(response_obj.read().decode("utf-8"))
    except (HTTPError, URLError) as exc:
        raise ValidationError(f"OnlyOffice PDF 导出失败: {exc}") from exc

    file_url = result.get("fileUrl") or result.get("url")
    if not file_url:
        raise ValidationError("OnlyOffice 未返回可下载的导出文件。")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(fetch_remote_binary(file_url))
    return str(output_path)


def sync_personal_entries(user, root_directory: str, entries: list[dict]):
    mount = create_or_sync_personal_mount(
        user,
        source_path=str(Path(root_directory)),
        kind=PersonalLibraryMountKind.FOLDER,
        entries=entries,
    )
    return mount.entries.filter(is_deleted=False).order_by("relative_path")
