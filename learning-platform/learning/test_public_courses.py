from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from .models import Course, TestAssignment, TestAttempt, PracticeResult


class PublicCourseAccessTests(TestCase):
    def test_guests_can_read_course_information_and_class_pages(self):
        pages = ['index.html', 'courses.html', 'publications.html', 'about-me.html', 'statistics.html', 'corporate-finance.html', 'project-management.html']
        pages += [p.name for pattern in ['statistics-week-*.html', 'corporate-finance-week-*.html'] for p in settings.SITE_DIR.glob(pattern)]
        for page in pages:
            with self.subTest(page=page):
                response = self.client.get('/site/' + page)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.has_header('Location'))
        self.assertContains(self.client.get('/site/index.html'), 'Sign in / Dashboard')

    def test_homework_tests_practice_and_personal_pages_still_require_login(self):
        teacher = User.objects.create_user('teacher', is_staff=True)
        course = Course.objects.create(slug='statistics', title='Statistics', teacher=teacher)
        work = TestAssignment.objects.create(course=course, title='Private homework test')
        paths = ['/', '/assigned-tests/', '/my-courses/', '/learning-progress/', '/teacher/students/', '/site/statistics-practice.html', reverse('take_test', args=[work.pk])]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith('/login/?next='))
        response = self.client.post(reverse('take_test', args=[work.pk]), {'action': 'start'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.post('/api/practice/attempt/', '{}', content_type='application/json').status_code, 302)
        self.assertFalse(TestAttempt.objects.exists())
        self.assertFalse(PracticeResult.objects.exists())
