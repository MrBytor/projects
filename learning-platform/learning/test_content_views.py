"""Teacher authoring and student access across nested course materials."""
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import ContentItem, Course, Enrollment, TestAssignment, TestAttempt
from .scoring import questions


class ContentViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('content-teacher', is_staff=True)
        cls.foreign = User.objects.create_user('foreign-content-teacher', is_staff=True)
        cls.admin = User.objects.create_user('content-administrator', is_staff=True, is_superuser=True)
        cls.student = User.objects.create_user('content-student')
        cls.outsider = User.objects.create_user('unenrolled-content-student')
        cls.course = Course.objects.create(slug='statistics', title='Statistics', teacher=cls.teacher, content_imported=True)
        cls.other_course = Course.objects.create(slug='corporate-finance', title='Corporate Finance', teacher=cls.foreign, content_imported=True)
        Enrollment.objects.create(student=cls.student, course=cls.course)
        cls.folder = ContentItem.objects.create(course=cls.course, kind='folder', title='Unit one', availability='published', position=10)
        cls.child = ContentItem.objects.create(course=cls.course, parent=cls.folder, kind='folder', title='Class A', availability='published', position=10)
        cls.page = ContentItem.objects.create(course=cls.course, parent=cls.child, kind='page', title='A short explanation', description='Worked examples for our class.', availability='published', position=10)
        cls.foreign_folder = ContentItem.objects.create(course=cls.other_course, kind='folder', title='Foreign course folder', availability='published')

    def setUp(self):
        private = TemporaryDirectory()
        self.addCleanup(private.cleanup)
        self.private_dir = Path(private.name)
        setting = override_settings(DATA_DIR=self.private_dir, MEDIA_ROOT=self.private_dir)
        setting.enable()
        self.addCleanup(setting.disable)
        self.client.force_login(self.teacher)

    def url(self, name, item=None, slug=None):
        args = [slug or self.course.slug]
        if item is not None:
            args.append(item.pk)
        return reverse(name, args=args)

    def data(self, title='New content', **changes):
        payload = {'title': title, 'description': 'Helpful class notes.', 'color': 'blue',
                   'availability': 'published', 'account_id': str(self.teacher.pk)}
        payload.update(changes)
        return payload

    def create(self, kind, parent=None, **changes):
        url = self.url('content_create') + '?kind=' + kind
        if parent is not None:
            url += '&parent=' + str(parent.pk)
        return self.client.post(url, self.data(**changes))

    def assertDenied(self, response):
        self.assertIn(response.status_code, (403, 404))

    def test_course_browser_contains_nested_folders_and_materials_in_place(self):
        sibling = ContentItem.objects.create(course=self.course, parent=self.folder, kind='folder',
                                              title='Class B', availability='published', position=20)
        response = self.client.get(self.url('course_workspace'))
        self.assertEqual(response.status_code, 200)
        root = response.context['items'][0]
        self.assertEqual(root.pk, self.folder.pk)
        self.assertEqual([child.pk for child in root.tree_children], [self.child.pk, sibling.pk])
        self.assertEqual(root.child_count, 2)
        self.assertEqual([child.pk for child in root.tree_children[0].tree_children], [self.page.pk])
        for folder in (self.folder, self.child, sibling):
            self.assertContains(response, f'data-content-folder="{folder.pk}"')
            self.assertContains(response, f'id="folder-{folder.pk}"')
            self.assertNotContains(response, f'href="{self.url("content_folder", folder)}"')
            self.assertContains(response, f'?kind=folder&amp;parent={folder.pk}')
        self.assertContains(response, self.page.title)
        self.assertContains(response, f'href="{self.url("content_detail", self.page)}"')

    def test_student_inline_tree_omits_hidden_ancestors_and_authoring_controls(self):
        hidden = ContentItem.objects.create(course=self.course, parent=self.folder, kind='folder',
                                            title='Unreleased revision', availability='draft', position=20)
        descendant = ContentItem.objects.create(course=self.course, parent=hidden, kind='page',
                                                title='Private worked answer', availability='published')
        self.client.force_login(self.student)
        response = self.client.get(self.url('course_workspace'))
        self.assertContains(response, self.child.title)
        self.assertContains(response, self.page.title)
        self.assertNotContains(response, hidden.title)
        self.assertNotContains(response, descendant.title)
        self.assertNotContains(response, 'Add materials')
        self.assertNotContains(response, 'data-content-dialog')
        self.assertNotContains(response, 'data-content-menu')
        self.assertEqual(response.context['items'][0].child_count, 1)
        self.assertEqual(self.client.get(self.url('content_detail', descendant)).status_code, 404)
        self.folder.availability = 'draft'
        self.folder.save(update_fields=['availability'])
        response = self.client.get(self.url('course_workspace'))
        for item in (self.folder, self.child, self.page, hidden, descendant):
            self.assertNotContains(response, item.title)

    def test_material_mutations_return_to_inline_parent_in_course(self):
        expected = self.url('course_workspace') + f'#folder-{self.child.pk}'
        created = self.create('page', self.child, title='Inline addition')
        self.assertEqual(created['Location'], expected)
        edited = self.client.post(self.url('content_edit', self.page), self.data(title='Inline explanation'))
        self.assertEqual(edited['Location'], expected)
        reordered = self.client.post(self.url('content_reorder', self.page), self.data(direction='down'))
        self.assertEqual(reordered['Location'], expected)
        hidden = self.client.post(self.url('content_visibility', self.page), self.data(availability='draft'))
        self.assertEqual(hidden['Location'], expected)
        moved = self.client.post(self.url('content_move', self.page), self.data(parent=self.folder.pk))
        self.assertEqual(moved['Location'], self.url('course_workspace') + f'#folder-{self.folder.pk}')
        root = self.client.post(self.url('content_move', self.page), self.data(parent=''))
        self.assertEqual(root['Location'], self.url('course_workspace'))

    def test_nested_folders_pages_and_links_are_created_in_current_location(self):
        for kind, title, extra in (
            ('folder', 'Extra resources', {}),
            ('page', 'Read this first', {'description': 'A useful explanation.'}),
            ('link', 'Reference website', {'url': 'https://example.com/lesson'}),
        ):
            with self.subTest(kind=kind):
                response = self.create(kind, self.child, title=title, **extra)
                self.assertEqual(response.status_code, 302)
                item = ContentItem.objects.get(title=title)
                self.assertEqual(item.parent, self.child)
                self.assertEqual(item.course, self.course)
                self.assertEqual(item.kind, kind)
        self.client.force_login(self.student)
        listing = self.client.get(self.url('content_folder', self.child))
        self.assertContains(listing, 'Extra resources')
        self.assertContains(listing, 'Read this first')
        self.assertContains(listing, 'Reference website')
        self.assertContains(self.client.get(self.url('content_detail', self.page)), 'Worked examples for our class.')

    def test_dialog_creation_returns_navigation_and_invalid_form_does_not_create(self):
        url = self.url('content_create') + f'?kind=folder&parent={self.child.pk}'
        dialog = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(dialog, 'csrfmiddlewaretoken')
        self.assertContains(dialog, 'account_id')
        invalid = self.client.post(url, self.data(title=''), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(invalid.status_code, 200)
        self.assertFalse(ContentItem.objects.filter(title='').exists())
        response = self.client.post(url, self.data(title='Created in dialog'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['redirect'], self.url('course_workspace') + f'#folder-{self.child.pk}')
        self.assertEqual(ContentItem.objects.get(title='Created in dialog').parent, self.child)

    def test_edit_move_reorder_and_publish_preserve_hierarchy(self):
        response = self.client.post(self.url('content_edit', self.page), self.data(title='Updated explanation'))
        self.assertEqual(response.status_code, 302)
        self.page.refresh_from_db()
        self.assertEqual(self.page.title, 'Updated explanation')
        self.assertEqual(self.page.parent, self.child)
        sibling = ContentItem.objects.create(course=self.course, parent=self.child, kind='page', title='Second page', availability='published', position=20)
        self.assertEqual(self.client.post(self.url('content_reorder', sibling), self.data(direction='up')).status_code, 302)
        self.assertEqual(list(ContentItem.objects.filter(parent=self.child).order_by('position', 'pk').values_list('pk', flat=True)), [sibling.pk, self.page.pk])
        self.assertEqual(self.client.post(self.url('content_move', self.page), self.data(parent=str(self.folder.pk))).status_code, 302)
        self.page.refresh_from_db()
        self.assertEqual(self.page.parent, self.folder)
        self.assertEqual(self.client.post(self.url('content_visibility', self.page), self.data(availability='draft')).status_code, 302)
        self.page.refresh_from_db()
        self.assertEqual(self.page.availability, 'draft')
        self.assertEqual(self.client.post(self.url('content_visibility', self.page), self.data(availability='published')).status_code, 302)
        self.assertEqual(self.client.post(self.url('content_move', self.page), self.data(parent='')).status_code, 302)
        self.page.refresh_from_db()
        self.assertIsNone(self.page.parent)

    def test_parent_must_be_same_course_folder_and_cannot_form_cycle(self):
        initial = ContentItem.objects.count()
        for parent in (self.foreign_folder, self.page):
            with self.subTest(parent=parent.pk):
                response = self.create('page', parent, title='Invalid placement')
                self.assertNotEqual(response.status_code, 302)
                self.assertEqual(ContentItem.objects.count(), initial)
        for item, parent in ((self.folder, self.child), (self.folder, self.folder), (self.page, self.foreign_folder), (self.child, self.page)):
            with self.subTest(item=item.pk, parent=parent.pk):
                before = ContentItem.objects.get(pk=item.pk).parent_id
                response = self.client.post(self.url('content_move', item), self.data(parent=str(parent.pk)))
                self.assertNotEqual(response.status_code, 302)
                self.assertEqual(ContentItem.objects.get(pk=item.pk).parent_id, before)

    def test_only_owner_or_administrator_can_author_materials(self):
        for actor in (self.foreign, self.student, self.outsider):
            self.client.force_login(actor)
            with self.subTest(actor=actor.username):
                self.assertDenied(self.client.get(self.url('content_create') + '?kind=folder'))
                self.assertDenied(self.client.post(self.url('content_create') + '?kind=folder', self.data(title='Forbidden addition', account_id=str(actor.pk))))
                for name, extra in (('content_edit', {}), ('content_move', {'parent': ''}), ('content_reorder', {'direction': 'up'}), ('content_visibility', {'availability': 'draft'})):
                    self.assertDenied(self.client.post(self.url(name, self.page), self.data(title='Forbidden change', account_id=str(actor.pk), **extra)))
        self.page.refresh_from_db()
        self.assertEqual(self.page.title, 'A short explanation')
        self.assertEqual(self.page.availability, 'published')
        self.assertFalse(ContentItem.objects.filter(title='Forbidden addition').exists())
        self.client.force_login(self.admin)
        response = self.client.post(self.url('content_edit', self.page), self.data(title='Administrator edit', account_id=str(self.admin.pk)))
        self.assertEqual(response.status_code, 302)
        self.page.refresh_from_db()
        self.assertEqual(self.page.title, 'Administrator edit')

    def test_mutation_requires_matching_account_and_csrf(self):
        targets = [('content_create', None, {}), ('content_edit', self.page, {}),
                   ('content_move', self.page, {'parent': ''}), ('content_reorder', self.page, {'direction': 'up'}),
                   ('content_visibility', self.page, {'availability': 'draft'})]
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.teacher)
        for name, item, extra in targets:
            url = self.url(name, item)
            if item is None:
                url += '?kind=folder'
            for stale in ('', str(self.foreign.pk)):
                with self.subTest(route=name, account=stale):
                    self.assertEqual(self.client.post(url, self.data(account_id=stale, **extra)).status_code, 403)
            self.assertEqual(protected.post(url, self.data(**extra)).status_code, 403)
        self.page.refresh_from_db()
        self.assertEqual(self.page.title, 'A short explanation')
        self.assertEqual(self.page.parent, self.child)
        self.assertEqual(self.page.availability, 'published')

    def test_unenrolled_and_signed_out_visitors_cannot_read_private_materials(self):
        for name, item in (('content_folder', self.folder), ('content_detail', self.page)):
            self.client.force_login(self.outsider)
            self.assertEqual(self.client.get(self.url(name, item)).status_code, 404)
            self.client.logout()
            self.assertEqual(self.client.get(self.url(name, item)).status_code, 302)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url('content_detail', self.page, slug=self.other_course.slug)).status_code, 404)

    def test_hidden_ancestor_blocks_listing_and_direct_child_urls(self):
        self.folder.availability = 'draft'
        self.folder.save(update_fields=['availability'])
        self.client.force_login(self.student)
        self.assertNotContains(self.client.get(self.url('course_workspace')), 'Unit one')
        self.assertEqual(self.client.get(self.url('content_folder', self.child)).status_code, 404)
        self.assertEqual(self.client.get(self.url('content_detail', self.page)).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(self.url('content_folder', self.child)), 'A short explanation')

    def test_scheduled_content_obeys_start_and_end_dates(self):
        now = timezone.now()
        self.page.availability = 'scheduled'
        self.page.available_from = now + timedelta(days=1)
        self.page.available_until = now + timedelta(days=2)
        self.page.save()
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url('content_detail', self.page)).status_code, 404)
        self.page.available_from = now - timedelta(days=1)
        self.page.save()
        self.assertEqual(self.client.get(self.url('content_detail', self.page)).status_code, 200)
        self.page.available_until = now - timedelta(hours=1)
        self.page.save()
        self.assertEqual(self.client.get(self.url('content_detail', self.page)).status_code, 404)

    def test_private_file_download_is_protected_by_ancestors_and_enrollment(self):
        payload = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n'
        upload = SimpleUploadedFile('class-notes.pdf', payload, content_type='application/pdf')
        response = self.create('file', self.child, title='Class handout', file=upload)
        self.assertEqual(response.status_code, 302)
        item = ContentItem.objects.get(title='Class handout')
        self.assertTrue(Path(item.file.path).resolve().is_relative_to(self.private_dir.resolve()))
        self.client.force_login(self.student)
        url = self.url('content_download', item)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), payload)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('class-notes.pdf', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        response.close()
        self.assertContains(self.client.get(self.url('content_detail', item)), f'<iframe src="{url}?inline=1"')
        preview = self.client.get(url + '?inline=1')
        self.assertEqual(preview.status_code, 200)
        self.assertIn('inline', preview['Content-Disposition'])
        self.assertEqual(preview['X-Frame-Options'], 'SAMEORIGIN')
        self.assertEqual(preview['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(preview['Content-Type'], 'application/pdf')
        preview.close()
        self.folder.availability = 'draft'
        self.folder.save(update_fields=['availability'])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.folder.availability = 'published'
        self.folder.save(update_fields=['availability'])
        Enrollment.objects.filter(course=self.course, student=self.student).delete()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_unsafe_links_uploads_and_source_paths_are_rejected(self):
        for url in ('javascript:alert(1)', 'data:text/html,hello', 'file:///C:/private.txt'):
            with self.subTest(url=url):
                self.assertEqual(self.create('link', self.child, title='Unsafe link', url=url).status_code, 200)
                self.assertFalse(ContentItem.objects.filter(title='Unsafe link').exists())
        response = self.create('file', self.child, title='Unsafe upload', file=SimpleUploadedFile('script.html', b'<script>alert(1)</script>', content_type='text/html'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ContentItem.objects.filter(title='Unsafe upload').exists())
        escaped = self.private_dir / 'private-note.txt'
        escaped.write_text('must not leak', encoding='utf8')
        item = ContentItem.objects.create(course=self.course, parent=self.child, kind='file', title='Invalid source', availability='published', source_path=str(escaped))
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url('content_download', item)).status_code, 404)
        item.source_path = '../learning-platform/manage.py'
        item.save(update_fields=['source_path'])
        self.assertEqual(self.client.get(self.url('content_download', item)).status_code, 404)

    def test_bank_quiz_creation_hidden_parent_and_direct_attempt_access(self):
        selected = list(questions())[:2]
        response = self.create('test', self.child, title='Lesson check', question_ids=selected,
                               due_at=(timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'))
        self.assertEqual(response.status_code, 302)
        item = ContentItem.objects.get(title='Lesson check')
        self.assertIsNotNone(item.test_id)
        self.assertEqual(item.test.course, self.course)
        self.assertEqual([q['id'] for q in item.test.question_snapshot], selected)
        self.client.force_login(self.student)
        test_url = reverse('take_test', args=[item.test_id])
        self.assertEqual(self.client.get(test_url).status_code, 200)
        self.assertContains(self.client.get(reverse('assigned_tests')), 'Lesson check')
        self.assertContains(self.client.get(reverse('student_calendar')), 'Lesson check')
        self.folder.availability = 'draft'
        self.folder.save(update_fields=['availability'])
        self.assertNotContains(self.client.get(reverse('assigned_tests')), 'Lesson check')
        self.assertNotContains(self.client.get(reverse('student_calendar')), 'Lesson check')
        self.assertEqual(self.client.get(test_url).status_code, 404)
        self.assertEqual(self.client.post(test_url, {'action': 'start'}).status_code, 404)
        self.assertFalse(TestAttempt.objects.filter(assignment=item.test).exists())

    def test_invalid_quiz_selection_never_creates_orphan_assignment(self):
        initial = TestAssignment.objects.count()
        for selected in ([], ['invented-question-id'], list(questions())[:51]):
            with self.subTest(count=len(selected)):
                response = self.create('test', self.child, title='Invalid quiz', question_ids=selected)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(TestAssignment.objects.count(), initial)
                self.assertFalse(ContentItem.objects.filter(title='Invalid quiz').exists())

    def test_administrator_can_open_quiz_roster_from_material(self):
        assignment = TestAssignment.objects.create(course=self.course, title='Managed quiz', question_snapshot=[next(iter(questions().values()))])
        item = ContentItem.objects.create(course=self.course, parent=self.child, kind='test', title='Managed quiz', test=assignment, availability='draft')
        self.client.force_login(self.admin)
        response = self.client.get(self.url('content_detail', item), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [(reverse('test_roster', args=[assignment.pk]), 302)])
        self.assertContains(response, self.student.username)
        self.client.force_login(self.foreign)
        self.assertEqual(self.client.get(reverse('test_roster', args=[assignment.pk])).status_code, 404)

    def test_quiz_edit_cannot_replace_linked_test_or_change_existing_attempts(self):
        snapshot = [next(iter(questions().values()))]
        original = TestAssignment.objects.create(course=self.course, title='Original draft quiz', question_snapshot=snapshot)
        replacement = TestAssignment.objects.create(course=self.course, title='Different quiz', question_snapshot=list(questions().values())[:2])
        item = ContentItem.objects.create(course=self.course, parent=self.child, kind='test', title=original.title,
                                          test=original, availability='draft')
        attempt = TestAttempt.objects.create(assignment=original, student=self.student, correct_count=1,
                                             answers={'kept': 'answer'}, submitted_at=timezone.now())
        submitted_at = attempt.submitted_at
        response = self.client.post(self.url('content_edit', item), self.data(title='Renamed draft quiz',
                                    availability='draft', test=str(replacement.pk), question_ids=list(questions())[:2]))
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        original.refresh_from_db()
        replacement.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(item.test_id, original.pk)
        self.assertEqual(original.question_snapshot, snapshot)
        self.assertEqual(original.title, 'Renamed draft quiz')
        self.assertEqual(replacement.title, 'Different quiz')
        self.assertEqual(attempt.assignment_id, original.pk)
        self.assertEqual(attempt.answers, {'kept': 'answer'})
        self.assertEqual(attempt.correct_count, 1)
        self.assertEqual(attempt.submitted_at, submitted_at)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('take_test', args=[original.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('assigned_tests')), 'Renamed draft quiz')

    def test_missing_slide_file_returns_404_and_existing_slide_stays_protected(self):
        item = ContentItem.objects.create(course=self.course, parent=self.child, kind='file', title='Presentation', availability='published')
        url = reverse('content_slide', args=[self.course.slug, item.pk, 1])
        self.client.force_login(self.student)
        with patch('learning.material_views.file_preview', return_value={'folder': self.private_dir, 'count': 1}):
            self.assertEqual(self.client.get(url).status_code, 404)
            (self.private_dir / 'Slide1.PNG').write_bytes(b'preview pixels')
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), b'preview pixels')
            self.assertIn('no-store', response['Cache-Control'])
            response.close()
            self.assertEqual(self.client.get(reverse('content_slide', args=[self.course.slug, item.pk, 2])).status_code, 404)
            self.folder.availability = 'draft'
            self.folder.save(update_fields=['availability'])
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_imported_lesson_and_slide_downloads_respect_folder_visibility(self):
        self.course.content_imported = False
        self.course.save(update_fields=['content_imported'])
        self.assertEqual(self.client.get(self.url('course_workspace')).status_code, 200)
        lesson_folder = ContentItem.objects.get(course=self.course, kind='folder', lesson_key='1-b')
        before = ContentItem.objects.filter(course=self.course).count()
        self.client.get(self.url('course_workspace'))
        self.assertEqual(ContentItem.objects.filter(course=self.course).count(), before)
        urls = [reverse('course_lesson', args=['statistics', '1-b']),
                reverse('lesson_material', args=['statistics', '1-b', 0]),
                reverse('lesson_slide', args=['statistics', '1-b', 0, 1])]
        (self.private_dir / 'Slide1.PNG').write_bytes(b'fake preview fixture')
        with patch('learning.workspace_views.presentation_preview', return_value={'folder': self.private_dir, 'count': 1}):
            self.client.force_login(self.student)
            for url in urls:
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)
                response.close()
            lesson_folder.availability = 'draft'
            lesson_folder.save(update_fields=['availability'])
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 404, url)
            lesson_folder.availability = 'published'
            lesson_folder.save(update_fields=['availability'])
            presentation = ContentItem.objects.get(course=self.course, source_key='material:1-b:0')
            presentation.availability = 'draft'
            presentation.save(update_fields=['availability'])
            for url in urls[1:]:
                self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.get('/site/statistics.html').status_code, 200)
