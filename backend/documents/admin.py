from django.contrib import admin

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


admin.site.register(SharedFolder)
admin.site.register(SharedPermission)
admin.site.register(PersonalLibraryMount)
admin.site.register(PersonalLibraryEntry)
admin.site.register(Document)
admin.site.register(RecycleBinEntry)
admin.site.register(DocumentLock)
admin.site.register(ArchiveEntry)
admin.site.register(ExportJob)

# Register your models here.
