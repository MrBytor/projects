import hashlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from .models import ContentItem, Course
from .presentation_jobs import queue_presentation_preview


class PresentationJobTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings_override = override_settings(DATA_DIR=self.root, SITE_DIR=self.root / 'site')
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.teacher = User.objects.create_user('presentation-teacher', is_staff=True)
        self.course = Course.objects.create(slug='statistics', title='Statistics', teacher=self.teacher)

    def upload(self, name='slides.pptx', data=b'private presentation bytes'):
        item = ContentItem(course=self.course, kind='file', title='Uploaded slides', original_name=name)
        item.file.save(name, ContentFile(data))
        return item

    def mark_current(self, item):
        fingerprint = hashlib.sha256(Path(item.file.path).read_bytes()).hexdigest()
        folder = self.root / 'slide-previews' / fingerprint
        folder.mkdir(parents=True)
        (folder / 'Slide1.PNG').write_bytes(b'preview')
        (folder / 'manifest.json').write_text(json.dumps({'count': 1, 'fingerprint': fingerprint}), encoding='utf8')

    @patch('learning.presentation_jobs.subprocess.Popen')
    @patch('learning.presentation_jobs.sys.platform', 'win32')
    def test_background_dispatch_uses_hidden_argument_array_and_private_log(self, popen):
        item = self.upload('slides; unexpected command.pptx')
        self.assertTrue(queue_presentation_preview(item))
        args, kwargs = popen.call_args
        self.assertIsInstance(args[0], list)
        self.assertIn('-NonInteractive', args[0])
        self.assertIn('-File', args[0])
        self.assertNotIn(item.original_name, ' '.join(args[0]))
        self.assertFalse(kwargs['shell'])
        self.assertEqual(kwargs['creationflags'], 0x08000000)
        self.assertEqual(kwargs['env']['TEACHING_DATA_DIR'], str(self.root))
        self.assertEqual(Path(kwargs['stdout'].name), self.root / 'slide-preview-jobs.log')

    @patch('learning.presentation_jobs.subprocess.Popen')
    @patch('learning.presentation_jobs.sys.platform', 'win32')
    def test_current_preview_and_other_file_types_do_not_spawn(self, popen):
        item = self.upload()
        self.mark_current(item)
        self.assertFalse(queue_presentation_preview(item))
        self.assertFalse(queue_presentation_preview(self.upload('handout.pdf')))
        self.assertFalse(queue_presentation_preview(ContentItem(course=self.course, kind='folder', title='Folder')))
        popen.assert_not_called()

    @patch('learning.presentation_jobs.subprocess.Popen')
    @patch('learning.presentation_jobs.sys.platform', 'linux')
    def test_non_windows_does_not_spawn(self, popen):
        self.assertFalse(queue_presentation_preview(self.upload()))
        popen.assert_not_called()

    @patch('learning.presentation_jobs.subprocess.Popen', side_effect=OSError('PowerShell unavailable'))
    @patch('learning.presentation_jobs.sys.platform', 'win32')
    def test_launch_failure_does_not_lose_material_or_raise(self, popen):
        item = self.upload()
        self.assertFalse(queue_presentation_preview(item))
        self.assertTrue(ContentItem.objects.filter(pk=item.pk).exists())
        self.assertTrue(Path(item.file.path).exists())

    @patch('learning.management.commands.slide_manifest.outline', return_value=[])
    def test_manifest_includes_private_uploads_deduplicates_and_ignores_current(self, outline):
        item = self.upload()
        ContentItem.objects.create(course=self.course, kind='file', title='Same file', file=item.file.name)
        self.upload('document.pdf')
        stdout = StringIO()
        call_command('slide_manifest', stdout=stdout)
        entries = json.loads(stdout.getvalue())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['source'], str(Path(item.file.path).resolve()))
        self.assertTrue(Path(entries[0]['destination']).is_relative_to(self.root))
        folder = Path(entries[0]['destination'])
        (folder / 'Slide1.PNG').write_bytes(b'preview')
        (folder / 'manifest.json').write_text(json.dumps({'count': 1, 'fingerprint': entries[0]['fingerprint']}), encoding='utf8')
        stdout = StringIO()
        call_command('slide_manifest', stdout=stdout)
        self.assertEqual(json.loads(stdout.getvalue()), [])

    @patch('learning.management.commands.slide_manifest.outline', return_value=[])
    def test_manifest_includes_trusted_source_and_rejects_escaped_paths(self, outline):
        materials = self.root / 'site' / 'materials'
        materials.mkdir(parents=True)
        (materials / 'source.pptx').write_bytes(b'existing source')
        ContentItem.objects.create(course=self.course, kind='file', title='Existing slides', source_path='materials/source.pptx')
        # A corrupt path inserted without model validation must never reach COM.
        outside = self.root / 'outside.pptx'
        outside.write_bytes(b'outside')
        ContentItem.objects.create(course=self.course, kind='file', title='Invalid source', source_path='../outside.pptx')
        ContentItem.objects.create(course=self.course, kind='file', title='Invalid upload', file=str(outside))
        stdout = StringIO()
        call_command('slide_manifest', stdout=stdout)
        entries = json.loads(stdout.getvalue())
        self.assertEqual([entry['source'] for entry in entries], [str((materials / 'source.pptx').resolve())])
