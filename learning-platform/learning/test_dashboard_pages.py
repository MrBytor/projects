from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from .models import Course, Enrollment, StudentRegistration, TestAssignment, TestAttempt
from .scoring import questions


class DashboardPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('teacher', is_staff=True)
        cls.other_teacher = User.objects.create_user('another-teacher', is_staff=True)
        cls.student = User.objects.create_user('student', first_name='Student One', email='student@example.test')
        cls.other_student = User.objects.create_user('outside-student', first_name='Outside Student', email='private@example.test')
        cls.stats = Course.objects.create(slug='statistics', title='Statistics', teacher=cls.teacher)
        cls.finance = Course.objects.create(slug='corporate-finance', title='Corporate Finance', teacher=cls.teacher)
        cls.project = Course.objects.create(slug='project-management', title='Project Management', teacher=cls.other_teacher)
        Enrollment.objects.create(student=cls.student, course=cls.stats)
        Enrollment.objects.create(student=cls.other_student, course=cls.project)
        cls.work = TestAssignment.objects.create(course=cls.stats, title='Existing Statistics test', question_snapshot=[next(iter(questions().values()))])

    def test_teacher_menu_opens_separate_pages_and_overview_is_short(self):
        self.client.force_login(self.teacher)
        overview = self.client.get('/')
        self.assertContains(overview, 'href="/teacher/students/"')
        self.assertContains(overview, 'href="/assigned-tests/"')
        for unwanted in ['/#students', '/#homework', '/#courses-heading', 'Statistics practice', 'My courses', 'student@example.test']:
            self.assertNotContains(overview, unwanted)
        self.assertContains(overview, 'Open full gradebook')
        self.assertContains(overview, self.work.title)
        self.assertLessEqual(len(overview.context['grade_preview']['rows']), 4)
        self.assertLessEqual(len(overview.context['grade_preview']['tests']), 3)
        students = self.client.get(reverse('student_directory'))
        self.assertContains(students, 'Student One')
        self.assertContains(students, 'student@example.test')
        self.assertNotContains(students, 'private@example.test')
        self.assertNotContains(students, self.work.title)
        tests = self.client.get(reverse('assigned_tests'))
        self.assertContains(tests, self.work.title)
        self.assertNotContains(tests, 'student@example.test')

    def test_course_access_can_be_replaced_cleared_and_restored(self):
        self.client.force_login(self.teacher)
        url = reverse('update_student_access', args=[self.student.pk])
        TestAttempt.objects.create(assignment=self.work, student=self.student, answers={'saved': 'work'})
        self.assertRedirects(self.client.post(url, {'courses': [self.finance.pk]}), reverse('student_directory'))
        self.assertEqual(list(Enrollment.objects.filter(student=self.student).values_list('course_id', flat=True)), [self.finance.pk])
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse('student_courses')), 'Corporate Finance')
        self.assertNotContains(self.client.get(reverse('student_courses')), 'Statistics')
        self.assertNotContains(self.client.get(reverse('assigned_tests')), self.work.title)
        self.assertEqual(self.client.get('/site/statistics.html').status_code, 200)
        self.assertEqual(self.client.get('/site/statistics-practice.html').status_code, 404)
        self.assertEqual(self.client.get('/site/corporate-finance.html').status_code, 200)
        self.assertEqual(self.client.get(reverse('take_test', args=[self.work.pk])).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertRedirects(self.client.post(url, {}), reverse('student_directory'))
        self.assertFalse(Enrollment.objects.filter(student=self.student).exists())
        self.assertContains(self.client.get(reverse('student_directory')), 'student@example.test')
        self.assertEqual(self.client.get(reverse('student_progress', args=[self.student.pk])).status_code, 200)
        self.assertTrue(StudentRegistration.objects.filter(teacher=self.teacher, student=self.student).exists())
        self.assertEqual(TestAttempt.objects.get().answers, {'saved': 'work'})
        self.client.post(url, {'courses': [self.stats.pk]})
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse('assigned_tests')), self.work.title)
        self.assertEqual(self.client.get(reverse('take_test', args=[self.work.pk])).status_code, 200)

    def test_course_access_cannot_grant_another_teachers_course(self):
        self.client.force_login(self.teacher)
        url = reverse('update_student_access', args=[self.student.pk])
        response = self.client.post(url, {'courses': [self.finance.pk, self.project.pk]})
        self.assertContains(response, 'Select a valid choice')
        self.assertTrue(Enrollment.objects.filter(student=self.student, course=self.stats).exists())
        self.assertFalse(Enrollment.objects.filter(student=self.student, course=self.finance).exists())

    def test_course_changes_preserve_access_managed_by_other_teachers(self):
        Enrollment.objects.create(student=self.student, course=self.project)
        self.client.force_login(self.teacher)
        url = reverse('update_student_access', args=[self.student.pk])
        self.client.post(url, {'courses': [self.finance.pk]})
        self.assertTrue(Enrollment.objects.filter(student=self.student, course=self.project).exists())
        self.assertTrue(Enrollment.objects.filter(student=self.student, course=self.finance).exists())
        self.assertFalse(Enrollment.objects.filter(student=self.student, course=self.stats).exists())

    def test_student_management_permissions_and_csrf(self):
        edit = reverse('edit_student', args=[self.student.pk])
        access = reverse('update_student_access', args=[self.student.pk])
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(edit).status_code, 404)
        self.assertEqual(self.client.post(access, {}).status_code, 404)
        self.assertNotContains(self.client.get(reverse('student_directory')), 'student@example.test')
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('student_directory')).status_code, 403)
        self.assertEqual(self.client.post(edit, {'first_name': 'Bad'}).status_code, 403)
        self.assertEqual(self.client.post(access, {}).status_code, 403)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(access).status_code, 405)
        self.assertEqual(self.client.post(reverse('update_student_access', args=[self.other_student.pk]), {}).status_code, 404)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.teacher)
        self.assertEqual(client.post(access, {}).status_code, 403)
        self.assertEqual(client.post(edit, {}).status_code, 403)

    def test_edit_name_email_and_validate_without_changing_role(self):
        self.client.force_login(self.teacher)
        url = reverse('edit_student', args=[self.student.pk])
        data = {'first_name': 'Updated Name', 'email': 'updated@example.test', 'is_staff': True, 'is_superuser': True, 'username': 'rewritten'}
        self.assertRedirects(self.client.post(url, data), reverse('student_directory'))
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, 'Updated Name')
        self.assertEqual(self.student.email, 'updated@example.test')
        self.assertEqual(self.student.username, 'student')
        self.assertFalse(self.student.is_staff)
        self.assertFalse(self.student.is_superuser)
        self.assertContains(self.client.get(reverse('student_directory')), 'updated@example.test')
        self.assertContains(self.client.post(url, {'first_name': 'Invalid', 'email': 'wrong-address'}), 'Enter a valid email address')
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, 'Updated Name')

    def test_new_student_without_courses_remains_in_directory(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('add_student'), {'username': 'new-student', 'first_name': 'New Student', 'email': 'new@example.test', 'password1': 'a-distinct-long-passphrase-123', 'password2': 'a-distinct-long-passphrase-123'})
        self.assertRedirects(response, reverse('student_directory'))
        student = User.objects.get(username='new-student')
        self.assertFalse(Enrollment.objects.filter(student=student).exists())
        self.assertTrue(StudentRegistration.objects.filter(student=student, teacher=self.teacher).exists())
        self.assertContains(self.client.get(reverse('student_directory')), 'new@example.test')
        self.client.post(reverse('update_student_access', args=[student.pk]), {'courses': [self.stats.pk]})
        self.client.force_login(student)
        self.assertContains(self.client.get(reverse('assigned_tests')), self.work.title)

    def test_student_navigation_separates_public_catalog_and_enrolled_courses(self):
        self.client.force_login(self.student)
        overview = self.client.get('/')
        self.assertContains(overview, 'href="/my-courses/"')
        self.assertContains(overview, 'href="/assigned-tests/"')
        self.assertNotContains(overview, 'Statistics practice')
        self.assertContains(overview, self.work.title)
        self.assertNotContains(overview, '/teacher/students/')
        catalog = self.client.get('/site/courses.html')
        for course in ['Statistics', 'Corporate Finance', 'Project Management']:
            self.assertContains(catalog, course)
        courses = self.client.get(reverse('student_courses'))
        self.assertContains(courses, 'Statistics')
        self.assertNotContains(courses, 'Corporate Finance')
        self.assertNotContains(courses, 'Project Management')
        self.assertContains(self.client.get(reverse('assigned_tests')), self.work.title)

    def test_restart_preserves_demo_course_choices(self):
        with TemporaryDirectory() as folder, self.settings(DATA_DIR=Path(folder)):
            call_command('seed_demo', stdout=StringIO())
            teacher = User.objects.get(username='teacher-demo')
            student = User.objects.get(username='student-demo')
            self.stats.teacher = teacher
            self.stats.save(update_fields=['teacher'])
            self.client.force_login(teacher)
            self.client.post(reverse('update_student_access', args=[student.pk]), {})
            self.assertFalse(Enrollment.objects.filter(student=student, course=self.stats).exists())
            before = set(Enrollment.objects.filter(student=student).values_list('course_id', flat=True))
            call_command('seed_demo', stdout=StringIO())
            self.assertEqual(set(Enrollment.objects.filter(student=student).values_list('course_id', flat=True)), before)
