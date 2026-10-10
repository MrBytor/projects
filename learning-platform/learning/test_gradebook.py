from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from .models import Course, Enrollment, StudentRegistration, TestAssignment, TestAttempt


class GradebookTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('teacher', is_staff=True)
        cls.other_teacher = User.objects.create_user('other-teacher', is_staff=True)
        cls.student = User.objects.create_user('student', first_name='Student Zero')
        cls.empty_student = User.objects.create_user('empty-student', first_name='Student Empty')
        cls.outside = User.objects.create_user('outside', first_name='Outside Student')
        cls.course = Course.objects.create(slug='statistics', title='Statistics', teacher=cls.teacher)
        cls.other = Course.objects.create(slug='other', title='Private Other Course', teacher=cls.other_teacher)
        for student in (cls.student, cls.empty_student):
            Enrollment.objects.create(student=student, course=cls.course)
        Enrollment.objects.create(student=cls.outside, course=cls.other)
        StudentRegistration.objects.create(student=cls.student, teacher=cls.teacher, major='Business', teaching_group='B1')
        cls.zero = TestAssignment.objects.create(course=cls.course, title='Zero result', week=1, class_label='Class A', question_snapshot=[{}, {}])
        cls.half = TestAssignment.objects.create(course=cls.course, title='Half result', week=2, question_snapshot=[{}] * 4)
        cls.draft = TestAssignment.objects.create(course=cls.course, title='Draft work', question_snapshot=[{}])
        TestAttempt.objects.create(student=cls.student, assignment=cls.zero, submitted_at=timezone.now(), correct_count=0)
        TestAttempt.objects.create(student=cls.student, assignment=cls.half, submitted_at=timezone.now(), correct_count=2)
        TestAttempt.objects.create(student=cls.student, assignment=cls.draft, correct_count=1)
        # An old attempt without a current enrolment must not appear in this class.
        TestAttempt.objects.create(student=cls.outside, assignment=cls.half, submitted_at=timezone.now(), correct_count=4)

    def setUp(self):
        self.client.force_login(self.teacher)
        self.url = reverse('gradebook')

    def test_zero_is_graded_and_drafts_are_excluded_from_average(self):
        response = self.client.get(self.url)
        row = next(r for r in response.context['rows'] if r['student'].pk == self.student.pk)
        self.assertEqual(row['completed'], 2)
        self.assertEqual(row['average'], 25)
        self.assertEqual([c['percentage'] for c in row['cells']], [0, 50, None])
        self.assertEqual(row['cells'][-1]['status'], 'In progress')
        empty = next(r for r in response.context['rows'] if r['student'].pk == self.empty_student.pk)
        self.assertIsNone(empty['average'])
        self.assertContains(response, '0%')
        self.assertNotContains(response, 'Outside Student')
        self.assertNotContains(response, 'Private Other Course')

    def test_combined_major_group_and_week_filters_scope_totals(self):
        response = self.client.get(self.url, {'course': self.course.pk, 'major': 'Business', 'teaching_group': 'B1', 'week': '1'})
        self.assertEqual(len(response.context['rows']), 1)
        self.assertEqual(response.context['test_count'], 1)
        self.assertEqual(response.context['rows'][0]['average'], 0)
        self.assertNotContains(response, 'Half result')
        self.assertEqual(self.client.get(self.url, {'course': self.course.pk, 'week': '__missing__'}).context['test_count'], 1)

    def test_course_ownership_invalid_filters_and_student_permissions(self):
        response = self.client.get(self.url, {'course': self.other.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['course'])
        self.assertFalse(response.context['rows'])
        self.assertFalse(self.client.get(self.url, {'course': self.course.pk, 'major': 'Fake'}).context['rows'])
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_completed_legacy_records_with_no_score_or_questions_are_ungraded(self):
        TestAttempt.objects.create(student=self.empty_student, assignment=self.zero, submitted_at=timezone.now())
        empty = TestAssignment.objects.create(course=self.course, title='Legacy empty test')
        TestAttempt.objects.create(student=self.empty_student, assignment=empty, submitted_at=timezone.now(), correct_count=0)
        response = self.client.get(self.url)
        row = next(r for r in response.context['rows'] if r['student'].pk == self.empty_student.pk)
        self.assertEqual(row['completed'], 2)
        self.assertIsNone(row['average'])

    def test_column_pages_keep_overall_average_and_student_pages(self):
        for index in range(11):
            assignment = TestAssignment.objects.create(course=self.course, title=f'Extra {index}', week=3, question_snapshot=[{}])
            TestAttempt.objects.create(student=self.student, assignment=assignment, submitted_at=timezone.now(), correct_count=1)
        response = self.client.get(self.url, {'course': self.course.pk, 'test_page': 2})
        row = next(r for r in response.context['rows'] if r['student'].pk == self.student.pk)
        self.assertEqual(response.context['test_count'], 14)
        self.assertEqual(len(response.context['tests']), 2)
        self.assertEqual(row['completed'], 13)
        self.assertAlmostEqual(row['average'], 1150 / 13)
        self.assertIn('test_page=2', response.context['page_query'])
        for index in range(26):
            user = User.objects.create_user(f'bulk-{index}', first_name=f'Bulk {index:02}')
            Enrollment.objects.create(student=user, course=self.course)
        response = self.client.get(self.url, {'course': self.course.pk, 'page': 2})
        self.assertEqual(len(response.context['rows']), 3)
        self.assertIn('page=2', response.context['test_query'])

    def test_query_count_stays_bounded_as_matrix_grows(self):
        with CaptureQueriesContext(connection) as baseline:
            self.client.get(self.url, {'course': self.course.pk})
        for index in range(20):
            user = User.objects.create_user(f'large-{index}')
            Enrollment.objects.create(student=user, course=self.course)
            TestAttempt.objects.create(student=user, assignment=self.zero)
        with CaptureQueriesContext(connection) as grown:
            self.client.get(self.url, {'course': self.course.pk})
        self.assertEqual(len(baseline), len(grown))
        self.assertLess(len(grown), 20)
        # Per-cell fetches must not accidentally load question bodies or answers.
        self.assertFalse(any('"learning_testattempt"."answers"' in q['sql'] for q in grown))
