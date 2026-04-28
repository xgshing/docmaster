from pathlib import Path

from django.conf import settings
from django.db.models import Q, Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, parsers, response, status, views
from rest_framework.exceptions import PermissionDenied

from accounts.permissions import IsAdminOrSuperAdmin
from audit.models import AuditLog
from .models import (
    ArchiveEntry,
    Document,
    DocumentLock,
    ExportJob,
    PersonalLibraryEntry,
    PersonalLibraryMount,
    PersonalLibraryMountKind,
    RecycleBinEntry,
    SharedFolder,
    SharedPermission,
)
from .serializers import (
    ArchiveEntrySerializer,
    DocumentLockSerializer,
    DocumentSerializer,
    ExportJobSerializer,
    PersonalLibraryEntrySerializer,
    PersonalLibraryMountSerializer,
    RecycleBinEntrySerializer,
    SharedFolderSerializer,
    SharedPermissionSerializer,
)
from .services import (
    append_access_log,
    build_onlyoffice_payload,
    build_personal_onlyoffice_payload,
    create_archive_entry,
    create_personal_onlyoffice_session,
    create_or_sync_personal_mount,
    create_or_replace_shared_document,
    document_permission_level,
    ensure_permission,
    export_document_to_pdf,
    get_accessible_documents,
    get_accessible_folders,
    get_personal_onlyoffice_session,
    integration_snapshot,
    list_personal_library,
    parse_callback_body,
    personal_file_type,
    ensure_document_cached,
    save_personal_onlyoffice_callback,
    prune_expired_recycle_entries,
    recycle_shared_folder,
    recycle_shared_document,
    restore_archive_entry,
    restore_recycle_entry,
    save_onlyoffice_callback,
    serialize_tree,
    sync_personal_mount,
    sync_personal_entries,
    trigger_personal_onlyoffice_forcesave,
    verify_document_token,
    verify_onlyoffice_callback,
)


class DashboardView(views.APIView):
    def get(self, request):
        documents = get_accessible_documents(request.user)
        folders = get_accessible_folders(request.user)
        recycle_queryset = RecycleBinEntry.objects.select_related("document", "folder")
        if request.user.role != "super_admin":
            recycle_queryset = recycle_queryset.filter(folder__creator=request.user)
        data = {
            "users": request.user.__class__.objects.count(),
            "sharedFolders": folders.count(),
            "sharedDocuments": documents.filter(space_type="shared").count(),
            "lockedDocuments": DocumentLock.objects.count(),
            "archivedEntries": ArchiveEntry.objects.filter(user=request.user, restored_at__isnull=True).count(),
            "recycleSize": recycle_queryset.aggregate(total=Sum("file_size")).get("total") or 0,
            "storage": integration_snapshot(),
        }
        return response.Response(data)


class SharedFolderListCreateView(generics.ListCreateAPIView):
    serializer_class = SharedFolderSerializer

    def get_queryset(self):
        return get_accessible_folders(self.request.user)

    def perform_create(self, serializer):
        parent = serializer.validated_data.get("parent")
        if parent:
            ensure_permission(self.request.user, folder=parent, level="manage")
            storage_path = str(Path(parent.storage_path) / serializer.validated_data["name"])
        else:
            storage_path = str(settings.DOCMASTER_SHARED_ROOT / serializer.validated_data["name"])
        Path(storage_path).mkdir(parents=True, exist_ok=True)
        serializer.save(creator=self.request.user, storage_path=storage_path)


class SharedFolderDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = SharedFolderSerializer

    def get_queryset(self):
        return get_accessible_folders(self.request.user)

    def perform_destroy(self, instance):
        ensure_permission(self.request.user, folder=instance, level="manage")
        instance.delete()


class SharedPermissionListCreateView(generics.ListCreateAPIView):
    serializer_class = SharedPermissionSerializer
    permission_classes = [IsAdminOrSuperAdmin]

    def get_queryset(self):
        queryset = SharedPermission.objects.select_related("folder", "user", "group").all()
        folder_id = self.request.query_params.get("folder")
        if folder_id:
            queryset = queryset.filter(folder_id=folder_id)
        return queryset.order_by("id")

    def perform_create(self, serializer):
        folder = serializer.validated_data["folder"]
        ensure_permission(self.request.user, folder=folder, level="manage")
        serializer.save()


class SharedPermissionDetailView(generics.DestroyAPIView):
    queryset = SharedPermission.objects.select_related("folder", "user", "group").all()
    serializer_class = SharedPermissionSerializer
    permission_classes = [IsAdminOrSuperAdmin]

    def perform_destroy(self, instance):
        ensure_permission(self.request.user, folder=instance.folder, level="manage")
        instance.delete()


class DocumentListCreateView(generics.ListCreateAPIView):
    serializer_class = DocumentSerializer

    def get_queryset(self):
        return get_accessible_documents(self.request.user).order_by("-last_edited_at")


class PersonalLibraryListView(views.APIView):
    def get(self, request):
        mounts, entries = list_personal_library(request.user)
        return response.Response(
            {
                "mounts": PersonalLibraryMountSerializer(mounts, many=True).data,
                "entries": PersonalLibraryEntrySerializer(entries, many=True).data,
            }
        )


class PersonalLibraryMountListCreateView(views.APIView):
    def post(self, request):
        items = request.data.get("items")
        if items is None:
            items = [request.data]
        created = []
        for item in items:
            kind = item.get("kind")
            source_path = str(item.get("source_path", "")).strip()
            if kind not in {PersonalLibraryMountKind.FOLDER, PersonalLibraryMountKind.FILE} or not source_path:
                return response.Response({"detail": "个人文档库挂载参数无效。"}, status=status.HTTP_400_BAD_REQUEST)
            mount = create_or_sync_personal_mount(
                request.user,
                source_path=source_path,
                kind=kind,
                entries=item.get("entries", []),
                file_info=item.get("file_info"),
            )
            created.append(mount)
        mounts, entries = list_personal_library(request.user)
        return response.Response(
            {
                "created": PersonalLibraryMountSerializer(created, many=True).data,
                "mounts": PersonalLibraryMountSerializer(mounts, many=True).data,
                "entries": PersonalLibraryEntrySerializer(entries, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )


class PersonalLibraryMountDetailView(generics.DestroyAPIView):
    serializer_class = PersonalLibraryMountSerializer

    def get_queryset(self):
        return PersonalLibraryMount.objects.filter(owner=self.request.user)


class PersonalLibraryMountSyncView(views.APIView):
    def post(self, request, pk: int):
        mount = get_object_or_404(PersonalLibraryMount, pk=pk, owner=request.user)
        sync_personal_mount(mount, entries=request.data.get("entries"), file_info=request.data.get("file_info"))
        mounts, entries = list_personal_library(request.user)
        return response.Response(
            {
                "mounts": PersonalLibraryMountSerializer(mounts, many=True).data,
                "entries": PersonalLibraryEntrySerializer(entries, many=True).data,
            }
        )


class PersonalLibrarySyncView(views.APIView):
    def post(self, request):
        root_directory = request.data.get("root_directory", "").strip()
        entries = request.data.get("entries", [])
        if not root_directory:
            return response.Response({"detail": "缺少个人文档库根目录。"}, status=status.HTTP_400_BAD_REQUEST)
        synced = sync_personal_entries(request.user, root_directory, entries)
        request.user.personal_root = root_directory
        request.user.save(update_fields=["personal_root"])
        return response.Response(PersonalLibraryEntrySerializer(synced, many=True).data)


class PersonalLibraryOnlyOfficeConfigView(views.APIView):
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request, pk: int):
        entry = get_object_or_404(
            PersonalLibraryEntry.objects.filter(owner=request.user, is_deleted=False),
            pk=pk,
            is_directory=False,
        )
        upload = request.FILES.get("file")
        if not upload:
            return response.Response({"detail": "未提供上传文件。"}, status=status.HTTP_400_BAD_REQUEST)
        metadata = create_personal_onlyoffice_session(entry, upload)
        payload = build_personal_onlyoffice_payload(request, entry, request.user, metadata)
        return response.Response(
            {
                "config": payload,
                "session": {
                    "id": metadata["session_id"],
                    "revision": metadata["revision"],
                    "file_type": personal_file_type(entry),
                },
            }
        )


class PersonalLibrarySessionStatusView(views.APIView):
    def get(self, request, session_id: str):
        metadata, _session_dir = get_personal_onlyoffice_session(session_id)
        if metadata["user_id"] != request.user.id:
            raise PermissionDenied("您没有执行该操作的权限。")
        return response.Response(
            {
                "id": metadata["session_id"],
                "entry_id": metadata["entry_id"],
                "revision": metadata["revision"],
                "updated_at": metadata["updated_at"],
            }
        )


class PersonalLibrarySessionDownloadView(views.APIView):
    permission_classes = []

    def get(self, request, session_id: str):
        metadata, _session_dir = get_personal_onlyoffice_session(session_id)
        token = request.query_params.get("token", "")
        is_owner = request.user.is_authenticated and metadata["user_id"] == request.user.id
        from .services import verify_personal_session_token

        if not is_owner and not verify_personal_session_token(token, session_id, "download"):
            raise PermissionDenied("您没有执行该操作的权限。")
        file_handle = Path(metadata["stored_path"]).open("rb")
        return FileResponse(file_handle, filename=metadata["name"], as_attachment=False)


class PersonalLibrarySessionForceSaveView(views.APIView):
    def post(self, request, session_id: str):
        metadata, _session_dir = get_personal_onlyoffice_session(session_id)
        if metadata["user_id"] != request.user.id:
            raise PermissionDenied("您没有执行该操作的权限。")
        result = trigger_personal_onlyoffice_forcesave(session_id)
        return response.Response(
            {
                "error": int(result.get("error", -1)),
                "revision": metadata["revision"],
            }
        )


class PersonalLibrarySessionOnlyOfficeCallbackView(views.APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, session_id: str):
        from .services import verify_personal_session_token

        token = request.query_params.get("token", "")
        if not verify_personal_session_token(token, session_id, "callback"):
            raise PermissionDenied("个人文档回调签名无效。")
        payload = request.data if request.data else parse_callback_body(request.body)
        save_personal_onlyoffice_callback(session_id, payload)
        return response.Response({"error": 0})


class SharedTreeView(views.APIView):
    def get(self, request):
        folders = list(get_accessible_folders(request.user))
        documents = list(get_accessible_documents(request.user).filter(space_type="shared"))
        roots, children = serialize_tree(folders, documents, request.user)
        return response.Response({"roots": roots, "children": children})


class DocumentUploadView(views.APIView):
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return response.Response({"detail": "未提供上传文件。"}, status=status.HTTP_400_BAD_REQUEST)

        folder = None
        folder_id = request.data.get("folder")
        if folder_id:
            folder = get_object_or_404(SharedFolder, pk=folder_id)
            ensure_permission(request.user, folder=folder, level="edit")

        conflict_strategy = request.data.get("conflict_strategy", "cancel")
        document = create_or_replace_shared_document(
            uploaded_file=upload,
            owner=request.user,
            folder=folder,
            filename=request.data.get("name") or upload.name,
            conflict_strategy=conflict_strategy,
        )
        return response.Response(DocumentSerializer(document, context={"request": request}).data, status=201)


class DocumentDetailView(generics.RetrieveAPIView):
    serializer_class = DocumentSerializer

    def get_queryset(self):
        return get_accessible_documents(self.request.user)


class DocumentDownloadView(views.APIView):
    def get(self, request, pk: int):
        document = get_object_or_404(Document.objects.select_related("folder", "owner"), pk=pk)
        token = request.query_params.get("token", "")
        has_document_token = verify_document_token(token, pk, "download")
        if not has_document_token:
            ensure_permission(request.user, document=document, level="view")
            append_access_log(document, request.user, "download")
        file_handle = ensure_document_cached(document).open("rb")
        return FileResponse(file_handle, filename=document.name, as_attachment=False)


class DocumentOnlyOfficeConfigView(views.APIView):
    def get(self, request, pk: int):
        document = get_object_or_404(Document.objects.select_related("folder", "owner"), pk=pk, is_deleted=False)
        config = build_onlyoffice_payload(request, document, request.user)
        append_access_log(document, request.user, "open_onlyoffice")
        return response.Response(config)


class DocumentOnlyOfficeCallbackView(views.APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, pk: int):
        document = get_object_or_404(Document, pk=pk)
        if not verify_onlyoffice_callback(request):
            raise PermissionDenied("OnlyOffice 回调签名无效。")
        payload = request.data if request.data else parse_callback_body(request.body)
        save_onlyoffice_callback(document, payload)
        return response.Response({"error": 0})


class DocumentExportPdfView(views.APIView):
    def post(self, request, pk: int):
        document = get_object_or_404(Document.objects.select_related("folder", "owner"), pk=pk, is_deleted=False)
        export_job = export_document_to_pdf(request, document, request.user)
        return response.Response(ExportJobSerializer(export_job).data, status=status.HTTP_201_CREATED)


class ExportJobDownloadView(views.APIView):
    def get(self, request, pk: int):
        export_job = get_object_or_404(ExportJob.objects.select_related("document", "requested_by"), pk=pk)
        ensure_permission(request.user, document=export_job.document, level="view")
        file_handle = Path(export_job.output_path).open("rb")
        return FileResponse(file_handle, filename=Path(export_job.output_path).name, as_attachment=False)


class LockDocumentView(views.APIView):
    def post(self, request, pk: int):
        document = get_object_or_404(Document.objects.select_related("folder"), pk=pk, is_deleted=False)
        ensure_permission(request.user, document=document, level="edit")
        lock, created = DocumentLock.objects.get_or_create(
            document=document,
            defaults={"locked_by": request.user, "session_key": request.session.session_key or ""},
        )
        if not created and lock.locked_by != request.user:
            return response.Response(
                {"detail": f"文档已被 {lock.locked_by.username} 锁定，当前仅可只读打开。"},
                status=status.HTTP_409_CONFLICT,
            )
        append_access_log(document, request.user, "lock")
        return response.Response(DocumentLockSerializer(lock).data)


class ForceUnlockDocumentView(views.APIView):
    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request, pk: int):
        document = get_object_or_404(Document.objects.select_related("folder"), pk=pk)
        ensure_permission(request.user, document=document, level="manage")
        lock = get_object_or_404(DocumentLock, document_id=pk)
        lock.delete()
        AuditLog.objects.create(
            actor=request.user.username,
            action_type="force_unlock",
            content=f"强制解锁文档 {document.name}",
            ip_address=request.META.get("REMOTE_ADDR", ""),
        )
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class DeleteSharedDocumentView(views.APIView):
    def post(self, request, pk: int):
        document = get_object_or_404(Document.objects.select_related("folder"), pk=pk, space_type="shared")
        ensure_permission(request.user, document=document, level="manage")
        recycle_shared_document(document, request.user)
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class DeleteSharedFolderView(views.APIView):
    def post(self, request, pk: int):
        folder = get_object_or_404(
            SharedFolder.objects.select_related("parent", "creator").prefetch_related("children"),
            pk=pk,
        )
        ensure_permission(request.user, folder=folder, level="manage")
        recycle_shared_folder(folder, request.user)
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class RecycleBinListView(generics.ListAPIView):
    serializer_class = RecycleBinEntrySerializer

    def get_queryset(self):
        prune_expired_recycle_entries()
        queryset = RecycleBinEntry.objects.select_related("document", "deleted_by", "folder").order_by("-deleted_at")
        if self.request.user.role == "super_admin":
            return queryset
        return queryset.filter(Q(folder__creator=self.request.user) | Q(deleted_by=self.request.user)).distinct()


def ensure_recycle_entry_permission(user, entry: RecycleBinEntry):
    if user.role == "super_admin":
        return
    if entry.folder_id:
        ensure_permission(user, folder=entry.folder, level="manage")
        return
    if entry.deleted_by_id == user.id:
        return
    raise PermissionDenied("您没有执行该操作的权限。")


class RestoreRecycleEntryView(views.APIView):
    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request, pk: int):
        entry = get_object_or_404(RecycleBinEntry.objects.select_related("document", "folder"), pk=pk)
        ensure_recycle_entry_permission(request.user, entry)
        restore_recycle_entry(entry, request.user)
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class PurgeRecycleEntryView(views.APIView):
    permission_classes = [IsAdminOrSuperAdmin]

    def post(self, request, pk: int):
        entry = get_object_or_404(RecycleBinEntry.objects.select_related("document", "folder"), pk=pk)
        ensure_recycle_entry_permission(request.user, entry)
        from .services import purge_recycle_entry

        purge_recycle_entry(entry, request.user)
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class ArchiveListCreateView(generics.ListCreateAPIView):
    serializer_class = ArchiveEntrySerializer

    def get_queryset(self):
        return ArchiveEntry.objects.filter(user=self.request.user, restored_at__isnull=True).order_by("-archived_at")

    def perform_create(self, serializer):
        document = serializer.validated_data.get("document")
        folder = serializer.validated_data.get("folder")
        if document:
            ensure_permission(self.request.user, document=document, level="view")
        if folder:
            ensure_permission(self.request.user, folder=folder, level="view")
        serializer.save(user=self.request.user)


class RestoreArchiveEntryView(views.APIView):
    def post(self, request, pk: int):
        entry = get_object_or_404(ArchiveEntry, pk=pk, user=request.user)
        restore_archive_entry(entry)
        return response.Response(status=status.HTTP_204_NO_CONTENT)


class DocumentActionSummaryView(views.APIView):
    def get(self, request, pk: int):
        document = get_object_or_404(Document.objects.select_related("folder", "owner", "last_edited_by"), pk=pk)
        permission = document_permission_level(request.user, document)
        return response.Response(
            {
                "document": DocumentSerializer(document, context={"request": request}).data,
                "permission": permission,
                "lock": DocumentLockSerializer(getattr(document, "lock", None)).data if hasattr(document, "lock") else None,
            }
        )
