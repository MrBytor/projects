"""Reorder whole sibling lists safely without changing content hierarchy."""
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from .models import ContentItem, Course, Enrollment


class ContentOrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('order-teacher', is_staff=True)
        cls.foreign = User.objects.create_user('order-foreign', is_staff=True)
        cls.student = User.objects.create_user('order-student')
        cls.admin = User.objects.create_user('order-admin', is_staff=True, is_superuser=True)
        cls.course = Course.objects.create(slug='statistics', title='Statistics', teacher=cls.teacher, content_imported=True)
        cls.other_course = Course.objects.create(slug='corporate-finance', title='Finance', teacher=cls.foreign, content_imported=True)
        Enrollment.objects.create(course=cls.course, student=cls.student)
        cls.first = ContentItem.objects.create(course=cls.course, kind='folder', title='First module', position=10)
        cls.page = ContentItem.objects.create(course=cls.course, kind='page', title='Course introduction', position=20)
        cls.second = ContentItem.objects.create(course=cls.course, kind='folder', title='Second module', position=30)
        cls.lesson = ContentItem.objects.create(course=cls.course, parent=cls.first, kind='folder', title='Class one', position=10)
        cls.note = ContentItem.objects.create(course=cls.course, parent=cls.first, kind='page', title='Class notes', position=20)
        cls.other_lesson = ContentItem.objects.create(course=cls.course, parent=cls.first, kind='folder', title='Class two', position=30)
        cls.grandchild = ContentItem.objects.create(course=cls.course, parent=cls.lesson, kind='page', title='Worked example', position=35)
        cls.foreign_folder = ContentItem.objects.create(course=cls.other_course, kind='folder', title='Foreign folder', position=10)

    def setUp(self):
        self.client.force_login(self.teacher)

    def ids(self, parent=None):
        return list(ContentItem.objects.filter(course=self.course, parent=parent).order_by('position', 'pk').values_list('pk', flat=True))

    def snapshot(self):
        return list(ContentItem.objects.order_by('pk').values_list('pk', 'course_id', 'parent_id', 'position'))

    def reorder(self, item, order_ids=None, **changes):
        payload = {'account_id': str(self.teacher.pk), 'parent': item.parent_id or '',
                   'order': ','.join(map(str, order_ids or list(reversed(self.ids(item.parent))))),
                   'expected_order': ','.join(map(str, self.ids(item.parent)))}
        payload.update(changes)
        return self.client.post(reverse('content_reorder', args=[self.course.slug, item.pk]), payload,
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_root_order_persists_across_mixed_rows_without_moving_children(self):
        descendants = list(ContentItem.objects.filter(parent__isnull=False).values_list('pk', 'parent_id', 'position'))
        order = [self.second.pk, self.first.pk, self.page.pk]
        response = self.reorder(self.second, order)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'order': order, 'parent': None})
        self.assertEqual(self.ids(), order)
        self.assertEqual(list(ContentItem.objects.filter(parent__isnull=False).values_list('pk', 'parent_id', 'position')), descendants)
        self.assertEqual(list(ContentItem.objects.filter(course=self.course, parent=None).order_by('position').values_list('position', flat=True)), [1, 2, 3])
        response = self.client.get(reverse('course_workspace', args=[self.course.slug]))
        self.assertEqual([item.pk for item in response.context['items']], order)

    def test_nested_reorder_keeps_parent_and_other_lists_unchanged(self):
        roots = self.ids()
        order = [self.other_lesson.pk, self.lesson.pk, self.note.pk]
        response = self.reorder(self.other_lesson, order)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'order': order, 'parent': self.first.pk})
        self.assertEqual(self.ids(self.first), order)
        self.assertEqual(self.ids(), roots)
        self.grandchild.refresh_from_db()
        self.assertEqual((self.grandchild.parent_id, self.grandchild.position), (self.lesson.pk, 35))
        self.other_lesson.refresh_from_db()
        self.assertEqual(self.other_lesson.parent_id, self.first.pk)

    def test_invalid_orders_are_rejected_atomically(self):
        baseline = self.snapshot()
        original = self.ids()
        invalid = [
            '', ','.join(map(str, original[:-1])),
            ','.join(map(str, [self.first.pk, self.first.pk, self.second.pk])),
            ','.join(map(str, [self.first.pk, self.page.pk, self.foreign_folder.pk])),
            ','.join(map(str, [self.first.pk, self.page.pk, self.lesson.pk])),
            ','.join(map(str, [*original, 999999])), 'not-an-id',
            ','.join(map(str, original)) + ',',
        ]
        for value in invalid:
            with self.subTest(order=value):
                response = self.reorder(self.first, order=value)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.snapshot(), baseline)

    def test_stale_order_does_not_overwrite_newer_reorder(self):
        original = self.ids()
        first_change = [self.second.pk, self.first.pk, self.page.pk]
        self.assertEqual(self.reorder(self.second, first_change).status_code, 200)
        baseline = self.snapshot()
        response = self.reorder(self.first, list(reversed(first_change)), expected_order=','.join(map(str, original)))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.snapshot(), baseline)

    def test_parent_context_must_still_match_the_dragged_item(self):
        baseline = self.snapshot()
        for wrong_parent in ('', str(self.second.pk), str(self.foreign_folder.pk)):
            with self.subTest(parent=wrong_parent):
                response = self.reorder(self.lesson, parent=wrong_parent)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(self.snapshot(), baseline)

    def test_malformed_parent_and_expected_order_do_not_change_any_rows(self):
        baseline = self.snapshot()
        for field, value in [('parent', 'invalid'), ('expected_order', ''), ('expected_order', 'invalid'),
                             ('expected_order', f'{self.first.pk},{self.first.pk},{self.second.pk}')]:
            with self.subTest(field=field, value=value):
                response = self.reorder(self.first, **{field: value})
                self.assertEqual(response.status_code, 409 if field == 'parent' else 400)
                self.assertEqual(self.snapshot(), baseline)

    def test_only_course_owner_or_admin_may_reorder(self):
        baseline = self.snapshot()
        for user in (self.student, self.foreign):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.reorder(self.first, account_id=str(user.pk))
                self.assertIn(response.status_code, (403, 404))
                self.assertEqual(self.snapshot(), baseline)
        self.client.force_login(self.admin)
        response = self.reorder(self.second, account_id=str(self.admin.pk))
        self.assertEqual(response.status_code, 200)
        self.client.logout()
        self.assertEqual(self.reorder(self.first).status_code, 302)

    def test_account_and_csrf_are_required(self):
        baseline = self.snapshot()
        for account in ('', str(self.foreign.pk)):
            self.assertEqual(self.reorder(self.first, account_id=account).status_code, 403)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.teacher)
        response = protected.post(reverse('content_reorder', args=[self.course.slug, self.first.pk]),
                                  {'account_id': self.teacher.pk, 'parent': '', 'order': ','.join(map(str, self.ids())),
                                   'expected_order': ','.join(map(str, self.ids()))},
                                  HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.snapshot(), baseline)

    def test_old_direction_actions_remain_available(self):
        response = self.client.post(reverse('content_reorder', args=[self.course.slug, self.second.pk]),
                                    {'account_id': self.teacher.pk, 'direction': 'up'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.ids(), [self.first.pk, self.second.pk, self.page.pk])

    def test_student_has_no_drag_handles_but_teacher_does(self):
        url = reverse('course_workspace', args=[self.course.slug])
        self.assertContains(self.client.get(url), 'data-content-drag')
        self.client.force_login(self.student)
        self.assertNotContains(self.client.get(url), 'data-content-drag')
