from django.db import migrations, models
import django.db.models.deletion


def backfill_personal_mounts(apps, schema_editor):
    PersonalLibraryEntry = apps.get_model("documents", "PersonalLibraryEntry")
    PersonalLibraryMount = apps.get_model("documents", "PersonalLibraryMount")

    roots = (
        PersonalLibraryEntry.objects.exclude(root_directory="")
        .values_list("owner_id", "root_directory")
        .distinct()
    )
    mount_map = {}
    for owner_id, root_directory in roots:
        normalized = str(root_directory).strip()
        cleaned = normalized.replace("\\", "/").rstrip("/")
        name = cleaned.split("/")[-1] if cleaned else normalized
        mount, _created = PersonalLibraryMount.objects.get_or_create(
            owner_id=owner_id,
            source_path=normalized,
            defaults={
                "name": name or normalized,
                "kind": "folder",
            },
        )
        mount_map[(owner_id, normalized)] = mount.id

    for entry in PersonalLibraryEntry.objects.exclude(root_directory="").iterator():
        entry.mount_id = mount_map.get((entry.owner_id, str(entry.root_directory).strip()))
        entry.save(update_fields=["mount"])


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0003_exportjob_cos_path_exportjob_error_message_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="PersonalLibraryMount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("source_path", models.CharField(max_length=512)),
                ("kind", models.CharField(choices=[("folder", "文件夹"), ("file", "文件")], max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="personal_mounts", to="accounts.user")),
            ],
            options={
                "unique_together": {("owner", "source_path")},
            },
        ),
        migrations.AddField(
            model_name="personallibraryentry",
            name="mount",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="entries", to="documents.personallibrarymount"),
        ),
        migrations.RunPython(backfill_personal_mounts, migrations.RunPython.noop),
    ]
