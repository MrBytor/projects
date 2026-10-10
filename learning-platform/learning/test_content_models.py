from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile
from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from .content import ancestors, can_manage_course, content_visible, ensure_course_content, folders_for_move, visible_items
from .content_forms import ContentItemForm, validate_material_upload
from .models import ContentItem, Course, Enrollment, TestAssignment


class ContentModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('content-teacher', is_staff=True)
        cls.other_teacher = User.objects.create_user('other-content-teacher', is_staff=True)
        cls.admin = User.objects.create_user('content-admin', is_superuser=True)
        cls.student = User.objects.create_user('content-student')
        cls.other_student = User.objects.create_user('other-content-student')
        cls.course = Course.objects.create(slug='statistics', title='Statistics', teacher=cls.teacher)
        cls.other_course = Course.objects.create(slug='other-statistics', title='Other statistics', teacher=cls.other_teacher)
        Enrollment.objects.create(student=cls.student, course=cls.course)

    def item(self, kind='folder', **kwargs):
        return ContentItem.objects.create(course=self.course, kind=kind, title='A material', **kwargs)

    def test_cycles_and_cross_course_parenting_are_rejected(self):
        parent = self.item()
        child = self.item(parent=parent)
        parent.parent = child
        with self.assertRaises(ValidationError):
            parent.full_clean()
        parent.parent = parent
        with self.assertRaises(ValidationError):
            parent.full_clean()
        child.parent = ContentItem.objects.create(course=self.other_course, kind='folder', title='Other course')
        with self.assertRaises(ValidationError):
            child.full_clean()
        child.parent = self.item(kind='page')
        with self.assertRaises(ValidationError):
            child.full_clean()

    def test_deep_subtree_cannot_be_moved_beyond_nesting_limit(self):
        root = self.item()
        child = self.item(parent=root)
        parent = self.item()
        for _ in range(ContentItem.MAX_DEPTH - 2):
            parent = self.item(parent=parent)
        root.parent = parent
        with self.assertRaises(ValidationError):
            root.full_clean()

    def test_source_keys_are_per_course_and_empty_normalizes_to_null(self):
        first = self.item(source_key='module:1')
        second = ContentItem(course=self.course, kind='folder', title='Another', source_key='module:1')
        with self.assertRaises(ValidationError):
            second.full_clean()
        second.course = self.other_course
        second.full_clean()
        first.source_key = ''
        first.full_clean()
        self.assertIsNone(first.source_key)

    def test_schedule_and_safe_urls_are_validated(self):
        item = self.item(availability='scheduled')
        with self.assertRaises(ValidationError):
            item.full_clean()
        item.available_from = timezone.now()
        item.available_until = item.available_from - timedelta(minutes=1)
        with self.assertRaises(ValidationError):
            item.full_clean()
        item.available_until = item.available_from + timedelta(days=1)
        item.full_clean()
        for url in ('javascript:alert(1)', 'file:///C:/private.txt', 'ftp://example.com/file'):
            link = ContentItem(course=self.course, kind='link', title='Unsafe', url=url)
            with self.assertRaises(ValidationError):
                link.full_clean()

    def test_test_cannot_belong_to_another_course(self):
        quiz = TestAssignment.objects.create(course=self.other_course, title='Different course test')
        item = ContentItem(course=self.course, kind='test', title='Quiz', test=quiz)
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_manage_access_is_scoped_to_teacher_owner_or_admin(self):
        self.assertTrue(can_manage_course(self.teacher, self.course))
        self.assertTrue(can_manage_course(self.admin, self.course))
        self.assertFalse(can_manage_course(self.other_teacher, self.course))
        self.assertFalse(can_manage_course(self.student, self.course))

    def test_parent_draft_and_dates_are_inherited_and_teacher_can_preview(self):
        parent = self.item(availability='draft')
        child = self.item(kind='page', parent=parent)
        self.assertFalse(content_visible(child, self.student))
        self.assertTrue(content_visible(child, self.teacher))
        self.assertTrue(content_visible(child, self.admin))
        parent.availability = 'scheduled'
        parent.available_from = timezone.now() + timedelta(days=1)
        parent.save()
        child.refresh_from_db()
        self.assertFalse(content_visible(child, self.student))
        parent.available_from = timezone.now() - timedelta(days=1)
        parent.save()
        child.refresh_from_db()
        self.assertTrue(content_visible(child, self.student))
        parent.available_until = timezone.now() - timedelta(minutes=1)
        parent.save()
        child.refresh_from_db()
        self.assertFalse(content_visible(child, self.student))

    def test_materials_require_active_enrollment_even_when_published(self):
        item = self.item(kind='page')
        self.assertTrue(content_visible(item, self.student))
        self.assertFalse(content_visible(item, self.other_student))
        self.assertFalse(content_visible(item, self.other_teacher))
        self.assertFalse(content_visible(item, AnonymousUser()))
        self.student.is_active = False
        self.assertFalse(content_visible(item, self.student))

    def test_visible_list_matches_individual_visibility_without_repeated_ancestor_queries(self):
        parent = self.item(availability='draft')
        child = self.item(kind='page', parent=parent)
        visible = self.item(kind='page')
        with self.assertNumQueries(3):
            result = visible_items(ContentItem.objects.filter(course=self.course), self.student)
        self.assertEqual([item.pk for item in result], [visible.pk])
        self.assertEqual(set(item.pk for item in visible_items(ContentItem.objects.filter(course=self.course), self.teacher)), {parent.pk, child.pk, visible.pk})

    def test_move_destinations_exclude_descendants_but_allow_siblings(self):
        parent = self.item()
        child = self.item(parent=parent)
        grandchild = self.item(parent=child)
        sibling = self.item()
        self.assertEqual([item.pk for item in folders_for_move(self.course, parent)], [sibling.pk])
        self.assertEqual([item.pk for item in ancestors(grandchild)], [parent.pk, child.pk])

    @patch('learning.content.outline')
    def test_seed_is_once_only_and_preserves_teacher_edits_and_removals(self, outline):
        outline.return_value = [{'number': 1, 'title': 'Module 1', 'lessons': [
            {'key': '1-b', 'label': 'Class 1B', 'title': 'Calculations', 'description': 'Work with numbers.',
             'materials': [{'name': 'slides.pptx', 'label': 'Presentation', 'path': 'materials/statistics/slides.pptx'}]},
        ]}]
        quiz = TestAssignment.objects.create(course=self.course, title='Class test', week=1, class_label='Class B')
        self.assertEqual(ensure_course_content(self.course), 4)
        folder = ContentItem.objects.get(course=self.course, source_key='class:1-b')
        test = ContentItem.objects.get(test=quiz)
        self.assertEqual(test.parent_id, folder.pk)
        folder.title = 'Teacher renamed this'
        folder.save()
        ContentItem.objects.get(source_key='material:1-b:0').delete()
        self.assertEqual(ensure_course_content(self.course), 0)
        self.assertEqual(ContentItem.objects.get(pk=folder.pk).title, 'Teacher renamed this')
        self.assertFalse(ContentItem.objects.filter(source_key='material:1-b:0').exists())
        self.course.refresh_from_db()
        self.assertTrue(self.course.content_imported)
        self.assertEqual(outline.call_count, 1)


class ContentUploadTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('upload-teacher', is_staff=True)
        self.course = Course.objects.create(slug='statistics', title='Statistics', teacher=self.teacher)

    def test_upload_rejects_disallowed_extension_wrong_signature_empty_and_oversize(self):
        cases = [SimpleUploadedFile('evil.html', b'<script>alert(1)</script>'),
                 SimpleUploadedFile('not-a-pdf.pdf', b'<script>oops</script>'),
                 SimpleUploadedFile('empty.pdf', b'')]
        oversized = SimpleUploadedFile('large.pdf', b'%PDF-1.4\n')
        oversized.size = 50 * 1024 * 1024 + 1
        cases.append(oversized)
        for upload in cases:
            with self.subTest(name=upload.name), self.assertRaises(ValidationError):
                validate_material_upload(upload)

    def test_office_type_is_checked_and_macro_documents_rejected(self):
        def package(name, main, macro=False):
            data = BytesIO()
            with ZipFile(data, 'w') as file:
                file.writestr('[Content_Types].xml', '<Types/>')
                file.writestr(main, '<document/>')
                if macro:
                    file.writestr('ppt/vbaProject.bin', b'macro')
            return SimpleUploadedFile(name, data.getvalue())
        validate_material_upload(package('slides.pptx', 'ppt/presentation.xml'))
        with self.assertRaises(ValidationError):
            validate_material_upload(package('slides.pptx', 'word/document.xml'))
        with self.assertRaises(ValidationError):
            validate_material_upload(package('slides.pptx', 'ppt/presentation.xml', macro=True))

    def test_form_requires_file_for_new_material_and_preserves_original_filename(self):
        data = {'title': 'Handout', 'availability': 'published'}
        form = ContentItemForm(data, course=self.course, kind='file')
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)
        with TemporaryDirectory() as directory, override_settings(DATA_DIR=Path(directory)):
            form = ContentItemForm(data, {'file': SimpleUploadedFile('handout.pdf', b'%PDF-1.4\n%%EOF')}, course=self.course, kind='file')
            self.assertTrue(form.is_valid(), form.errors)
            item = form.save()
            self.assertEqual(item.original_name, 'handout.pdf')
            self.assertTrue(Path(item.file.path).is_relative_to(Path(directory) / 'content-files'))
            self.assertTrue(Path(item.file.path).exists())
            self.assertNotIn('handout', item.file.name)

    def test_edit_source_file_does_not_require_reupload(self):
        item = ContentItem.objects.create(course=self.course, kind='file', title='Presentation', source_path='materials/statistics/slides.pptx')
        form = ContentItemForm({'title': 'Updated presentation', 'availability': 'published'}, course=self.course, kind='file', instance=item)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().source_path, 'materials/statistics/slides.pptx')

    def test_existing_test_choices_exclude_other_courses_and_already_placed_tests(self):
        available = TestAssignment.objects.create(course=self.course, title='Available quiz')
        placed = TestAssignment.objects.create(course=self.course, title='Placed quiz')
        item = ContentItem.objects.create(course=self.course, kind='test', title=placed.title, test=placed)
        form = ContentItemForm(course=self.course, kind='test')
        self.assertEqual(list(form.fields['test'].queryset), [available])
        edit = ContentItemForm(course=self.course, kind='test', instance=item)
        self.assertEqual(set(edit.fields['test'].queryset), {available, placed})

    def test_invalid_parent_produces_dialog_errors_instead_of_exception(self):
        other = Course.objects.create(slug='another-course', title='Another course', teacher=self.teacher)
        parent = ContentItem.objects.create(course=other, kind='folder', title='Other parent')
        data = {'title': 'New folder', 'availability': 'published', 'color': 'blue'}
        form = ContentItemForm(data, course=self.course, kind='folder', parent=parent)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())
        parent = None
        for _ in range(ContentItem.MAX_DEPTH):
            parent = ContentItem.objects.create(course=self.course, kind='folder', title='Nested', parent=parent)
        form = ContentItemForm(data, course=self.course, kind='folder', parent=parent)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())
