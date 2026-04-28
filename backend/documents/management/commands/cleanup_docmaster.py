from django.core.management.base import BaseCommand

from documents.services import prune_expired_logs, prune_expired_recycle_entries


class Command(BaseCommand):
    help = "清理过期回收站和超过 1 年的日志。"

    def handle(self, *args, **options):
        prune_expired_recycle_entries()
        prune_expired_logs()
        self.stdout.write(self.style.SUCCESS("清理完成。"))
