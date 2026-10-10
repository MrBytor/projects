from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from .content_forms import ContentItemForm, MAX_VIDEO_UPLOAD_SIZE, validate_material_upload, validate_video_upload
from .models import ContentItem, Course
from .video import video_embed


def mp4_bytes():
    def box(kind, payload):
        return (len(payload) + 8).to_bytes(4, 'big') + kind + payload
    return (box(b'ftyp', b'isom' + b'\0' * 4 + b'isommp42')
            + box(b'moov', box(b'trak', b'track-data')) + box(b'mdat', b'frame-data'))


def webm_bytes():
    header = b'\x1a\x45\xdf\xa3\x87\x42\x82\x84webm'
    tracks = b'\x16\x54\xae\x6b\x81\0'
    cluster = b'\x1f\x43\xb6\x75\x81\0'
    return header + b'\x18\x53\x80\x67\xff' + tracks + cluster


class VideoValidationTests(SimpleTestCase):
    def test_valid_mp4_and_webm_containers_reset_file_position(self):
        for name, content in [('lesson.MP4', mp4_bytes()), ('lesson.webm', webm_bytes())]:
            with self.subTest(name=name):
                upload = SimpleUploadedFile(name, content)
                self.assertIs(validate_video_upload(upload), upload)
                self.assertEqual(upload.tell(), 0)

    def test_only_video_uploads_have_the_100_mb_limit(self):
        upload = SimpleUploadedFile('lesson.mp4', mp4_bytes())
        upload.size = MAX_VIDEO_UPLOAD_SIZE
        validate_video_upload(upload)
        upload.size += 1
        with self.assertRaisesMessage(ValidationError, '100 MB'):
            validate_video_upload(upload)
        with self.assertRaises(ValidationError):
            validate_material_upload(SimpleUploadedFile('lesson.mp4', mp4_bytes()))
        ordinary = SimpleUploadedFile('handout.pdf', b'%PDF-1.4')
        ordinary.size = 50 * 1024 * 1024 + 1
        with self.assertRaisesMessage(ValidationError, '50 MB'):
            validate_material_upload(ordinary)

    def test_extension_content_and_truncated_containers_are_rejected(self):
        invalid = [('lesson.mov', mp4_bytes()), ('lesson.mp4', b''), ('lesson.mp4', b'<script>video</script>'),
                   ('lesson.mp4', mp4_bytes()[:-1]), ('lesson.mp4', mp4_bytes()[:24]),
                   ('lesson.mp4', mp4_bytes().replace(b'isom', b'fake').replace(b'mp42', b'fake')),
                   ('lesson.webm', b'\x1a\x45\xdf\xa3fake'), ('lesson.webm', webm_bytes().replace(b'webm', b'mkv ')),
                   ('lesson.webm', webm_bytes()[:-1]), ('lesson.webm', mp4_bytes())]
        for name, content in invalid:
            with self.subTest(name=name, content=content), self.assertRaises(ValidationError):
                validate_video_upload(SimpleUploadedFile(name, content))

    def test_safe_provider_urls_are_canonicalized_without_fetching(self):
        for url in ['https://youtu.be/abcdefghijk?t=2', 'https://www.youtube.com/watch?v=abcdefghijk&list=any',
                    'https://youtube.com/shorts/abcdefghijk', 'https://www.youtube-nocookie.com/embed/abcdefghijk']:
            player = video_embed(url)
            self.assertEqual(player['kind'], 'embed')
            self.assertEqual(player['url'], 'https://www.youtube-nocookie.com/embed/abcdefghijk')
        self.assertEqual(video_embed('https://vimeo.com/123456789')['url'], 'https://player.vimeo.com/video/123456789')
        direct = video_embed('https://cdn.example.com/lesson.MP4?token=abc')
        self.assertEqual(direct['kind'], 'direct')
        self.assertEqual(direct['mime_type'], 'video/mp4')
        self.assertEqual(direct['url'], 'https://cdn.example.com/lesson.MP4?token=abc')

    def test_unknown_or_deceptive_providers_never_become_iframes(self):
        for url in ['https://youtube.com.evil.example/watch?v=abcdefghijk', 'https://vimeo.com/abc',
                    'https://youtube.com/watch?v=invalid', 'https://example.com/watch?id=123']:
            self.assertEqual(video_embed(url)['kind'], 'external')
        for url in ['javascript:alert(1)', 'file:///video.mp4', 'https://youtube.com@evil.example/watch?v=abcdefghijk',
                    'https://[broken/video.mp4']:
            self.assertEqual(video_embed(url)['url'], '')


class VideoFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        teacher = User.objects.create_user('video-form-teacher', is_staff=True)
        cls.course = Course.objects.create(slug='video-course', title='Video course', teacher=teacher)

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        settings = override_settings(DATA_DIR=Path(self.directory.name))
        settings.enable()
        self.addCleanup(settings.disable)

    def form(self, data=None, files=None, instance=None):
        return ContentItemForm(data, files, course=self.course, kind='video', instance=instance)

    def test_form_exposes_source_choice_and_validates_each_source(self):
        empty = self.form()
        self.assertEqual(empty.fields['video_source'].initial, 'upload')
        self.assertIn('video/mp4', empty.fields['file'].widget.attrs['accept'])
        for source, field in [('upload', 'file'), ('link', 'url')]:
            form = self.form({'title': 'Video', 'availability': 'published', 'video_source': source})
            self.assertFalse(form.is_valid())
            self.assertIn(field, form.errors)
        form = self.form({'title': 'Video', 'availability': 'published', 'video_source': 'other'})
        self.assertFalse(form.is_valid())
        self.assertIn('video_source', form.errors)

    def test_uploaded_video_is_saved_privately_with_original_name(self):
        form = self.form({'title': 'Lecture', 'availability': 'published', 'video_source': 'upload'},
                         {'file': SimpleUploadedFile('Lecture.mp4', mp4_bytes())})
        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()
        self.assertEqual(item.original_name, 'Lecture.mp4')
        self.assertEqual(item.url, '')
        self.assertTrue(Path(item.file.path).is_relative_to(Path(self.directory.name) / 'content-files'))
        self.assertEqual(Path(item.file.path).read_bytes(), mp4_bytes())

    def test_switching_upload_to_link_clears_metadata_without_deleting_file(self):
        form = self.form({'title': 'Lecture', 'availability': 'published', 'video_source': 'upload'},
                         {'file': SimpleUploadedFile('Lecture.mp4', mp4_bytes())})
        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()
        stored_path = Path(item.file.path)
        edit = self.form({'title': 'Linked lecture', 'availability': 'published', 'video_source': 'link',
                          'url': 'https://youtu.be/abcdefghijk'}, instance=item)
        self.assertTrue(edit.is_valid(), edit.errors)
        edited = edit.save()
        edited.refresh_from_db()
        self.assertFalse(edited.file)
        self.assertEqual(edited.original_name, '')
        self.assertEqual(edited.source_path, '')
        self.assertEqual(edited.url, 'https://youtu.be/abcdefghijk')
        self.assertTrue(stored_path.exists())
        self.assertEqual(self.form(instance=edited).fields['video_source'].initial, 'link')

    def test_switching_link_to_upload_requires_file_and_clears_old_url(self):
        item = ContentItem.objects.create(course=self.course, kind='video', title='Link', url='https://vimeo.com/123456')
        data = {'title': 'Uploaded lecture', 'availability': 'published', 'video_source': 'upload', 'url': item.url}
        missing = self.form(data, instance=item)
        self.assertFalse(missing.is_valid())
        self.assertIn('file', missing.errors)
        item.refresh_from_db()
        edit = self.form(data, {'file': SimpleUploadedFile('Lecture.webm', webm_bytes())}, instance=item)
        self.assertTrue(edit.is_valid(), edit.errors)
        edited = edit.save()
        self.assertEqual(edited.url, '')
        self.assertEqual(edited.original_name, 'Lecture.webm')

    def test_title_edit_preserves_existing_upload_without_reupload(self):
        form = self.form({'title': 'Lecture', 'availability': 'published', 'video_source': 'upload'},
                         {'file': SimpleUploadedFile('Lecture.mp4', mp4_bytes())})
        self.assertTrue(form.is_valid(), form.errors)
        item = form.save()
        name = item.file.name
        edit = self.form({'title': 'Renamed lecture', 'availability': 'published', 'video_source': 'upload'}, instance=item)
        self.assertTrue(edit.is_valid(), edit.errors)
        edited = edit.save()
        self.assertEqual(edited.file.name, name)
        self.assertEqual(edited.original_name, 'Lecture.mp4')

    def test_link_source_does_not_silently_discard_new_upload(self):
        form = self.form({'title': 'Lecture', 'availability': 'published', 'video_source': 'link',
                          'url': 'https://vimeo.com/123456'}, {'file': SimpleUploadedFile('Lecture.mp4', mp4_bytes())})
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)

    def test_model_requires_exactly_one_source_and_disallows_legacy_paths(self):
        item = ContentItem(course=self.course, title='Video', kind='video')
        with self.assertRaises(ValidationError):
            item.full_clean()
        item.url = 'https://youtu.be/abcdefghijk'
        item.full_clean()
        item.file = 'private/lecture.mp4'
        with self.assertRaises(ValidationError):
            item.full_clean()
        item.url = ''
        item.full_clean()
        item.source_path = 'materials/course/lecture.mp4'
        with self.assertRaises(ValidationError):
            item.full_clean()
