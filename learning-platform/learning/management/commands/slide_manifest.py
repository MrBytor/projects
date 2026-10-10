"""Trusted local input list for the read-only PowerPoint preview exporter."""
import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.exceptions import SuspiciousFileOperation
from learning.curriculum import cached_fingerprint, cached_preview, outline, trusted_material
from learning.models import ContentItem


class Command(BaseCommand):
    help = 'List existing presentations that need browser previews.'

    def handle(self, *args, **options):
        items, sources, seen = [], [], set()
        for slug in ('statistics', 'corporate-finance', 'project-management'):
            for module in outline(slug):
                for lesson in module['lessons']:
                    for material in lesson['materials']:
                        if material['kind'] == 'PPTX':
                            trusted = trusted_material(material['path'])
                            if trusted:
                                sources.append(settings.SITE_DIR / trusted['path'])
        private_root = (settings.DATA_DIR / 'content-files').resolve()
        for item in ContentItem.objects.filter(kind='file').exclude(file='', source_path='').iterator():
            if item.file:
                try:
                    path = Path(item.file.path).resolve()
                except (SuspiciousFileOperation, OSError, ValueError):
                    continue
                if path.is_relative_to(private_root):
                    sources.append(path)
            elif item.source_path:
                material = trusted_material(item.source_path)
                if material:
                    sources.append(settings.SITE_DIR / material['path'])
        for source in sources:
            source = source.resolve()
            path_key = str(source).casefold()
            if source.suffix.lower() != '.pptx' or path_key in seen or not source.is_file():
                continue
            seen.add(path_key)
            stat = source.stat()
            fingerprint = cached_fingerprint(source, stat.st_mtime_ns, stat.st_size)
            folder = settings.DATA_DIR / 'slide-previews' / fingerprint
            try:
                stat = (folder / 'manifest.json').stat()
                if cached_preview(folder, stat.st_mtime_ns, stat.st_size):
                    continue
            except (OSError, ValueError, KeyError, TypeError):
                pass
            folder.mkdir(parents=True, exist_ok=True)
            items.append({'source': str(source), 'destination': str(folder), 'fingerprint': fingerprint})
        self.stdout.write(json.dumps(items))
