from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import mimetypes
import shutil

from django.conf import settings

try:
    from qcloud_cos import CosConfig, CosS3Client
except ImportError:  # pragma: no cover - optional dependency in local sandbox
    CosConfig = None
    CosS3Client = None


@dataclass
class StorageLocation:
    local_path: str
    cos_path: str


class StorageClient:
    def __init__(self):
        self._client = None
        if settings.DOCMASTER_COS_ENABLED and CosConfig and CosS3Client:
            config = CosConfig(
                Region=settings.DOCMASTER_COS_REGION,
                SecretId=settings.DOCMASTER_TENCENT_SECRET_ID,
                SecretKey=settings.DOCMASTER_TENCENT_SECRET_KEY,
                Scheme="https",
            )
            self._client = CosS3Client(config)

    @property
    def enabled(self) -> bool:
        return bool(settings.DOCMASTER_COS_ENABLED and self._client)

    def upload_file(self, source: Path, cos_key: str):
        if not self.enabled:
            return
        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        with source.open("rb") as file_obj:
            self._client.put_object(
                Bucket=settings.DOCMASTER_COS_BUCKET,
                Body=file_obj,
                Key=cos_key,
                ContentType=content_type,
            )

    def download_file(self, cos_key: str, target: Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        if not self.enabled:
            return target
        response = self._client.get_object(Bucket=settings.DOCMASTER_COS_BUCKET, Key=cos_key)
        with target.open("wb") as file_obj:
            file_obj.write(response["Body"].get_raw_stream().read())
        return target

    def delete_file(self, cos_key: str):
        if not self.enabled or not cos_key:
            return
        self._client.delete_object(Bucket=settings.DOCMASTER_COS_BUCKET, Key=cos_key)


storage_client = StorageClient()


def normalize_relative_key(path_like: str) -> str:
    return str(path_like).replace("\\", "/").strip("/")


def build_document_cos_key(folder_path: str, filename: str) -> str:
    folder_key = normalize_relative_key(folder_path)
    if folder_key:
        return f"shared/{folder_key}/{filename}"
    return f"shared/{filename}"


def build_export_cos_key(document_id: int, filename: str) -> str:
    return f"exports/{document_id}/{filename}"


def cache_document_from_cos(cos_key: str, local_path: str) -> str:
    target = Path(local_path)
    if target.exists():
        return str(target)
    return str(storage_client.download_file(cos_key, target))


def persist_document_to_storage(local_path: str, cos_key: str) -> StorageLocation:
    source = Path(local_path)
    source.parent.mkdir(parents=True, exist_ok=True)
    storage_client.upload_file(source, cos_key)
    return StorageLocation(local_path=str(source), cos_path=cos_key)


def remove_local_file(path_like: str):
    target = Path(path_like)
    if target.exists():
        target.unlink()


def copy_to_export(source_path: str, target_path: str):
    source = Path(source_path)
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return str(target)
