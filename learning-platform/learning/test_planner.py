from datetime import datetime, timedelta, timezone as utc
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Course, Enrollment, TestAssignment, TestAttempt
from .planner import calendar_month


class PlannerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('teacher', is_staff=True)
        cls.student = User.objects.create_user('student')
        cls.other_student = User.objects.create_user('other')
        cls.stats = Course.objects.create(slug='statistics', title='Statistics', teacher=cls.teacher)
        cls.finance = Course.objects.create(slug='corporate-finance', title='Finance', teacher=cls.teacher)
        Enrollment.objects.create(student=cls.student, course=cls.stats)
        cls.overdue = TestAssignment.objects.create(course=cls.stats, title='Overdue homework', due_at=timezone.now() - timedelta(days=2))
        cls.draft = TestAssignment.objects.create(course=cls.stats, title='Saved draft', due_at=timezone.now() + timedelta(days=1))
        cls.undated = TestAssignment.objects.create(course=cls.stats, title='Undated work')
        cls.completed = TestAssignment.objects.create(course=cls.stats, title='Completed work', due_at=timezone.now() - timedelta(days=1))
        cls.private = TestAssignment.objects.create(course=cls.finance, title='Unenrolled private work', due_at=timezone.now())
        TestAttempt.objects.create(student=cls.student, assignment=cls.draft)
        TestAttempt.objects.create(student=cls.student, assignment=cls.completed, submitted_at=timezone.now(), correct_count=0)
        TestAttempt.objects.create(student=cls.other_student, assignment=cls.undated, submitted_at=timezone.now())

    def setUp(self):
        self.client.force_login(self.student)

    def test_outstanding_order_and_resume_links_are_personal(self):
        response = self.client.get(reverse('to_do'))
        self.assertEqual([r['assignment'].pk for r in response.context['work']], [self.overdue.pk, self.draft.pk, self.undated.pk])
        self.assertContains(response, 'Resume')
        self.assertContains(response, 'Overdue')
        self.assertContains(response, 'No deadline')
        self.assertNotContains(response, self.completed.title)
        self.assertNotContains(response, self.private.title)
        self.assertEqual(len(self.client.get(reverse('to_do'), {'status': 'overdue'}).context['work']), 1)
        self.assertEqual(self.client.get(reverse('to_do'), {'status': 'in_progress'}).context['work'][0]['assignment'], self.draft)
        self.assertEqual(len(self.client.get(reverse('to_do'), {'status': 'not_started'}).context['work']), 2)

    def test_course_filter_requires_enrolment_and_revocation_hides_saved_work(self):
        self.assertFalse(self.client.get(reverse('to_do'), {'course': self.finance.pk}).context['work'])
        self.assertFalse(self.client.get(reverse('to_do'), {'status': 'made-up'}).context['work'])
        self.assertNotContains(self.client.get(reverse('student_calendar'), {'course': self.finance.pk}), self.private.title)
        Enrollment.objects.filter(student=self.student).delete()
        self.assertFalse(self.client.get(reverse('to_do')).context['work'])
        self.assertEqual(self.client.get(reverse('student_calendar')).context['event_count'], 0)
        self.assertTrue(TestAttempt.objects.filter(student=self.student, assignment=self.draft).exists())

    def test_calendar_uses_china_day_and_month_boundaries(self):
        TestAssignment.objects.all().update(due_at=None)
        first = TestAssignment.objects.create(course=self.stats, title='China October start', due_at=datetime(2026, 9, 30, 16, tzinfo=utc.utc))
        last = TestAssignment.objects.create(course=self.stats, title='China October end', due_at=datetime(2026, 10, 31, 15, 59, tzinfo=utc.utc))
        TestAssignment.objects.create(course=self.stats, title='China November start', due_at=datetime(2026, 10, 31, 16, tzinfo=utc.utc))
        TestAttempt.objects.create(student=self.student, assignment=first, submitted_at=timezone.now(), correct_count=0)
        data = calendar_month(self.student, '2026-10')
        events = {day['date'].day: day['events'] for week in data['weeks'] for day in week if day['events']}
        self.assertEqual(data['event_count'], 2)
        self.assertEqual(events[1][0]['assignment'], first)
        self.assertEqual(events[1][0]['status'], 'Completed')
        self.assertEqual(events[31][0]['assignment'], last)
        response = self.client.get(reverse('student_calendar'), {'month': '2026-10', 'course': self.stats.pk})
        self.assertContains(response, '00:00')
        self.assertNotContains(response, 'China November start')
        self.assertContains(response, f'&amp;course={self.stats.pk}')
        self.assertContains(response, 'without a deadline')

    def test_calendar_month_validation_navigation_and_empty_month(self):
        for month in ['not-a-month', '2026-13', '9999-01', '2026-1', '1999-12']:
            self.assertContains(self.client.get(reverse('student_calendar'), {'month': month}), 'Choose a month')
        self.assertIsNone(calendar_month(self.student, '2000-01')['previous_month'])
        self.assertIsNone(calendar_month(self.student, '2100-12')['next_month'])
        self.assertEqual(calendar_month(self.student, '2000-02')['event_count'], 0)

    def test_dashboard_next_tasks_and_pagination_stay_short(self):
        for index in range(30):
            TestAssignment.objects.create(course=self.stats, title=f'Additional task {index}')
        overview = self.client.get('/')
        self.assertEqual(len(overview.context['upcoming']), 5)
        self.assertEqual(overview.context['overdue'], 1)
        self.assertContains(overview, 'href="/calendar/"')
        response = self.client.get(reverse('to_do'), {'course': self.stats.pk, 'page': 2})
        self.assertEqual(len(response.context['work']), 8)
        self.assertIn(f'course={self.stats.pk}', response.context['page_query'])

    def test_teacher_redirect_and_anonymous_login(self):
        self.client.force_login(self.teacher)
        self.assertRedirects(self.client.get(reverse('to_do')), '/')
        self.assertEqual(self.client.get(reverse('student_calendar')).status_code, 200)
        self.client.logout()
        for name in ['to_do', 'student_calendar']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)
