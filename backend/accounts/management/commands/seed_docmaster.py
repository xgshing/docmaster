from django.conf import settings
from django.core.management.base import BaseCommand

from accounts.models import Role, User


class Command(BaseCommand):
    help = "初始化 DocMaster 超级管理员账号。"

    def handle(self, *args, **options):
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "role": Role.SUPER_ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "is_enabled": True,
            },
        )
        if created or not admin.has_usable_password():
            admin.set_password(settings.DOCMASTER_DEFAULT_ADMIN_PASSWORD)
            admin.save(update_fields=["password"])
        self.stdout.write(
            self.style.SUCCESS(
                f"admin 初始化完成，默认密码: {settings.DOCMASTER_DEFAULT_ADMIN_PASSWORD}"
            )
        )
