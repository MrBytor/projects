"""Video authoring, browser playback, and private byte-range delivery."""
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import ContentItem, Course, Enrollment


def mp4_bytes(frames=None):
    # Container signature fixture: delivery tests compare bytes, not media decoding.
    def box(kind, payload):
        return (len(payload) + 8).to_bytes(4, 'big') + kind + payload
    return (box(b'ftyp', b'isom\x00\x00\x02\x00isommp42')
            + box(b'moov', box(b'trak', b'fixture-track'))
            + box(b'mdat', bytes(range(256)) if frames is None else frames))


class VideoViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('video-teacher', is_staff=True)
        cls.foreign_teacher = User.objects.create_user('other-video-teacher', is_staff=True)
        cls.admin = User.objects.create_user('video-admin', is_staff=True, is_superuser=True)
        cls.student = User.objects.create_user('video-student')
        cls.outsider = User.objects.create_user('video-outsider')
        cls.course = Course.objects.create(slug='statistics', title='Statistics', teacher=cls.teacher, content_imported=True)
        cls.other_course = Course.objects.create(slug='corporate-finance', title='Corporate Finance', teacher=cls.foreign_teacher, content_imported=True)
        Enrollment.objects.create(course=cls.course, student=cls.student)
        cls.folder = ContentItem.objects.create(course=cls.course, kind='folder', title='Module one')
        cls.child = ContentItem.objects.create(course=cls.course, parent=cls.folder, kind='folder', title='Class one')

    def setUp(self):
        private = TemporaryDirectory()
        self.addCleanup(private.cleanup)
        self.private_dir = Path(private.name)
        setting = override_settings(DATA_DIR=self.private_dir, MEDIA_ROOT=self.private_dir)
        setting.enable()
        self.addCleanup(setting.disable)
        self.payload = mp4_bytes()
        self.video = ContentItem.objects.create(
            course=self.course, parent=self.child, kind='video', title='Worked example video',
            original_name='worked-example.mp4',
            file=SimpleUploadedFile('worked-example.mp4', self.payload, content_type='video/mp4'))
        self.client.force_login(self.teacher)

    def url(self, name, item=None, course=None):
        return reverse(name, args=[(course or self.course).slug, (item or self.video).pk])

    def create_url(self):
        return reverse('content_create', args=[self.course.slug]) + f'?kind=video&parent={self.child.pk}'

    def data(self, actor=None, **changes):
        data = {'title': 'Another video', 'description': 'Watch this worked example.',
                'availability': 'published', 'video_source': 'upload',
                'account_id': str((actor or self.teacher).pk)}
        data.update(changes)
        return data

    def body(self, response):
        try:
            return b''.join(response.streaming_content) if response.streaming else response.content
        finally:
            response.close()

    def test_teacher_upload_creates_private_material_with_embedded_player(self):
        response = self.client.post(self.create_url(), self.data(
            file=SimpleUploadedFile('lecture.mp4', self.payload, content_type='video/mp4')))
        self.assertEqual(response.status_code, 302)
        item = ContentItem.objects.get(title='Another video')
        self.assertEqual(item.parent, self.child)
        self.assertEqual(item.kind, 'video')
        self.assertEqual(item.original_name, 'lecture.mp4')
        self.assertEqual(item.url, '')
        path = Path(item.file.path).resolve()
        self.assertTrue(path.is_relative_to((self.private_dir / 'content-files').resolve()))
        self.assertEqual(path.read_bytes(), self.payload)
        self.client.force_login(self.student)
        player = self.client.get(self.url('content_detail', item))
        self.assertContains(player, '<video')
        self.assertContains(player, 'controls')
        self.assertContains(player, self.url('content_video', item))
        self.assertNotContains(player, str(path))
        self.assertNotContains(player, item.file.name)

    def test_student_and_other_teacher_cannot_upload_video(self):
        count = ContentItem.objects.count()
        for actor in (self.student, self.outsider, self.foreign_teacher):
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)
                self.assertIn(self.client.get(self.create_url()).status_code, (403, 404))
                response = self.client.post(self.create_url(), self.data(actor=actor,
                    file=SimpleUploadedFile('forbidden.mp4', self.payload, content_type='video/mp4')))
                self.assertIn(response.status_code, (403, 404))
        self.assertEqual(ContentItem.objects.count(), count)

    def test_large_multipart_video_uses_temporary_upload_and_preserves_all_bytes(self):
        # Larger than both the 1 MB form-data cap and Django's 2.5 MB memory
        # threshold: the multipart file must pass through the disk handler.
        from django.core.files.uploadedfile import TemporaryUploadedFile
        from . import content_forms

        payload = mp4_bytes(bytes(range(256)) * (3 * 1024 * 1024 // 256))
        received_types = []
        validate = content_forms.validate_video_upload

        def tracked_validation(upload):
            received_types.append(type(upload))
            return validate(upload)

        with patch.object(content_forms, 'validate_video_upload', tracked_validation):
            response = self.client.post(self.create_url(), self.data(
                title='Large lecture video',
                file=SimpleUploadedFile('large-lecture.mp4', payload, content_type='video/mp4')))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(received_types, [TemporaryUploadedFile])
        item = ContentItem.objects.get(title='Large lecture video')
        self.assertEqual(Path(item.file.path).read_bytes(), payload)

    def test_video_link_can_be_added_and_youtube_uses_a_known_embed_host(self):
        response = self.client.post(self.create_url(), self.data(video_source='link',
            url='https://www.youtube.com/watch?v=dQw4w9WgXcQ'))
        self.assertEqual(response.status_code, 302)
        item = ContentItem.objects.get(title='Another video')
        self.assertFalse(item.file)
        self.client.force_login(self.student)
        player = self.client.get(self.url('content_detail', item))
        self.assertContains(player, '<iframe')
        self.assertContains(player, 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ')

    def test_unknown_video_host_is_an_external_link_not_an_arbitrary_iframe(self):
        item = ContentItem.objects.create(course=self.course, kind='video', title='External video',
                                          url='https://example.com/watch?id=123')
        self.client.force_login(self.student)
        response = self.client.get(self.url('content_detail', item))
        self.assertContains(response, 'href="https://example.com/watch?id=123"')
        self.assertContains(response, 'rel="noopener noreferrer"')
        self.assertNotContains(response, '<iframe')
        self.assertNotContains(response, '<video')
        self.assertEqual(self.client.get(self.url('content_video', item)).status_code, 404)

    def test_authorized_video_delivery_supports_full_get_head_and_download(self):
        self.client.force_login(self.student)
        stream = self.client.get(self.url('content_video'))
        self.assertEqual(stream.status_code, 200)
        self.assertEqual(stream['Content-Type'], 'video/mp4')
        self.assertEqual(stream['Accept-Ranges'], 'bytes')
        self.assertEqual(int(stream['Content-Length']), len(self.payload))
        self.assertIn('private', stream['Cache-Control'])
        self.assertIn('no-store', stream['Cache-Control'])
        self.assertEqual(stream['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.body(stream), self.payload)
        head = self.client.head(self.url('content_video'))
        self.assertEqual(head.status_code, 200)
        self.assertEqual(int(head['Content-Length']), len(self.payload))
        self.assertEqual(head['Accept-Ranges'], 'bytes')
        self.assertEqual(self.body(head), b'')
        download = self.client.get(self.url('content_download') + '?inline=1')
        self.assertEqual(download.status_code, 200)
        self.assertIn('attachment;', download['Content-Disposition'])
        self.assertEqual(self.body(download), self.payload)

    def test_range_delivery_returns_exact_bounded_suffix_and_open_ended_bytes(self):
        self.client.force_login(self.student)
        size = len(self.payload)
        for header, start, end in (
            ('bytes=8-23', 8, 23), ('bytes=-12', size - 12, size - 1),
            ('bytes=24-', 24, size - 1), ('bytes=10-99999', 10, size - 1),
        ):
            with self.subTest(range=header):
                response = self.client.get(self.url('content_video'), HTTP_RANGE=header)
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response['Content-Range'], f'bytes {start}-{end}/{size}')
                self.assertEqual(int(response['Content-Length']), end - start + 1)
                self.assertEqual(response['Accept-Ranges'], 'bytes')
                self.assertEqual(self.body(response), self.payload[start:end + 1])

    def test_unsatisfiable_ranges_do_not_send_file_contents(self):
        self.client.force_login(self.student)
        size = len(self.payload)
        for header in (f'bytes={size}-', f'bytes={size + 20}-{size + 30}', 'bytes=-0'):
            with self.subTest(range=header):
                response = self.client.get(self.url('content_video'), HTTP_RANGE=header)
                self.assertEqual(response.status_code, 416)
                self.assertEqual(response['Content-Range'], f'bytes */{size}')
                self.assertNotIn(self.payload, self.body(response))

    def test_malformed_and_multiple_ranges_fall_back_to_full_delivery(self):
        self.client.force_login(self.student)
        for header in ('bytes=oops', 'items=0-2', 'bytes=0-1,4-5'):
            with self.subTest(range=header):
                response = self.client.get(self.url('content_video'), HTTP_RANGE=header)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('Content-Range', response)
                self.assertEqual(self.body(response), self.payload)

    def test_if_range_only_resumes_the_current_version_of_the_video(self):
        self.client.force_login(self.student)
        head = self.client.head(self.url('content_video'))
        etag = head['ETag']
        self.body(head)
        matching = self.client.get(self.url('content_video'), HTTP_RANGE='bytes=8-15', HTTP_IF_RANGE=etag)
        self.assertEqual(matching.status_code, 206)
        self.assertEqual(self.body(matching), self.payload[8:16])
        stale = self.client.get(self.url('content_video'), HTTP_RANGE='bytes=8-15', HTTP_IF_RANGE='"old-video"')
        self.assertEqual(stale.status_code, 200)
        self.assertNotIn('Content-Range', stale)
        self.assertEqual(self.body(stale), self.payload)

    def test_head_never_opens_media_and_interrupted_stream_releases_its_file(self):
        self.client.force_login(self.student)
        target = Path(self.video.file.path).resolve()
        opened = []
        original_open = Path.open

        def tracked_open(path, *args, **kwargs):
            handle = original_open(path, *args, **kwargs)
            if path.resolve() == target:
                opened.append(handle)
            return handle

        with patch.object(Path, 'open', tracked_open):
            self.body(self.client.head(self.url('content_video')))
            self.assertEqual(opened, [])
            response = self.client.get(self.url('content_video'))
            self.assertEqual(opened, [])
            next(response.streaming_content)
            self.assertEqual(len(opened), 1)
            self.assertFalse(opened[0].closed)
            response.close()
            self.assertTrue(opened[0].closed)

    def test_every_range_request_rechecks_enrollment_and_folder_visibility(self):
        self.client.force_login(self.student)
        first = self.client.get(self.url('content_video'), HTTP_RANGE='bytes=0-7')
        self.assertEqual(first.status_code, 206)
        self.assertEqual(self.body(first), self.payload[:8])
        self.folder.availability = 'draft'
        self.folder.save(update_fields=['availability'])
        for name in ('content_detail', 'content_video', 'content_download'):
            response = self.client.get(self.url(name), HTTP_RANGE='bytes=8-15')
            self.assertEqual(response.status_code, 404)
            self.assertNotIn('Content-Range', response)
            self.assertNotIn(self.payload, self.body(response))
        self.folder.availability = 'scheduled'
        self.folder.available_from = timezone.now() + timedelta(days=1)
        self.folder.save(update_fields=['availability', 'available_from'])
        self.assertEqual(self.client.get(self.url('content_video'), HTTP_RANGE='bytes=0-7').status_code, 404)
        self.folder.availability = 'published'
        self.folder.available_from = None
        self.folder.save(update_fields=['availability', 'available_from'])
        Enrollment.objects.filter(course=self.course, student=self.student).delete()
        self.assertEqual(self.client.get(self.url('content_video'), HTTP_RANGE='bytes=0-7').status_code, 404)

    def test_video_endpoints_reject_unenrolled_signed_out_and_wrong_course_requests(self):
        for name in ('content_detail', 'content_video', 'content_download'):
            for actor in (self.outsider, self.foreign_teacher):
                with self.subTest(route=name, actor=actor.username):
                    self.client.force_login(actor)
                    self.assertEqual(self.client.get(self.url(name), HTTP_RANGE='bytes=0-7').status_code, 404)
            self.client.logout()
            self.assertEqual(self.client.get(self.url(name), HTTP_RANGE='bytes=0-7').status_code, 302)
            self.client.force_login(self.admin)
            self.assertEqual(self.client.get(self.url(name, course=self.other_course), HTTP_RANGE='bytes=0-7').status_code, 404)

    def test_owner_and_administrator_can_preview_a_hidden_video(self):
        self.child.availability = 'draft'
        self.child.save(update_fields=['availability'])
        for actor in (self.teacher, self.admin):
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)
                response = self.client.get(self.url('content_video'), HTTP_RANGE='bytes=0-7')
                self.assertEqual(response.status_code, 206)
                self.assertEqual(self.body(response), self.payload[:8])

    def test_missing_private_file_returns_404_and_streaming_route_rejects_non_video(self):
        Path(self.video.file.path).unlink()
        self.assertEqual(self.client.get(self.url('content_video')).status_code, 404)
        page = ContentItem.objects.create(course=self.course, kind='page', title='Ordinary page')
        self.assertEqual(self.client.get(self.url('content_video', page)).status_code, 404)
