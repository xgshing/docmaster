from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0004_personallibrarymount_and_entry_mount"),
    ]

    operations = [
        migrations.AddField(
            model_name="sharedfolder",
            name="space_type",
            field=models.CharField(
                choices=[("personal", "个人文档库"), ("shared", "共享空间")],
                default="shared",
                max_length=16,
            ),
        ),
        migrations.AlterUniqueTogether(
            name="sharedfolder",
            unique_together={("parent", "name", "space_type")},
        ),
    ]
