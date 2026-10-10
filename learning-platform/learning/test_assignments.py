from copy import deepcopy
from datetime import timedelta
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Course, Enrollment, TestAssignment, TestAttempt
from .scoring import questions


class AssignedTestWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('teacher', password='a-long-test-password', first_name='Teacher name', is_staff=True)
        cls.other_teacher = User.objects.create_user('another-teacher', is_staff=True)
        cls.student = User.objects.create_user('student', password='a-long-test-password', first_name='Student name')
        cls.waiting_student = User.objects.create_user('waiting-student', first_name='Still waiting')
        cls.outsider = User.objects.create_user('outsider')
        cls.course = Course.objects.create(slug='statistics', title='Statistics', teacher=cls.teacher)
        Enrollment.objects.bulk_create([Enrollment(course=cls.course, student=s) for s in (cls.student, cls.waiting_student)])
        cls.choice = next(q for q in questions().values() if all(f['kind'] == 'choice' for f in q['fields']))
        cls.numeric = next(q for q in questions().values() if any(f['kind'] == 'number' for f in q['fields']))
        cls.assignment = TestAssignment.objects.create(course=cls.course, title='Week one test', question_snapshot=[cls.choice, cls.numeric])

    def answers(self, action='submit'):
        data = {'action': action, 'correct_count': '100', 'student_id': self.outsider.pk}
        for qi, q in enumerate(self.assignment.question_snapshot):
            for fi, f in enumerate(q['fields']):
                data[f'q{qi}_f{fi}'] = str(f['answer']) if f['kind'] == 'choice' else f"{f['answer']:.{f.get('decimals', 0)}f}"
        return data

    def start(self):
        self.client.force_login(self.student)
        return self.client.post(reverse('take_test', args=[self.assignment.pk]), {'action': 'start'})

    def test_assign_selects_bank_questions_and_all_enrolled_students(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('add_test'), {'course': self.course.pk, 'title': 'New test', 'question_ids': [self.numeric['id'], self.choice['id']]})
        test = TestAssignment.objects.get(title='New test')
        self.assertRedirects(response, reverse('test_roster', args=[test.pk]))
        self.assertEqual([q['id'] for q in test.question_snapshot], [self.numeric['id'], self.choice['id']])
        page = self.client.get(response.url)
        self.assertContains(page, 'Still waiting')
        self.assertEqual([row['status'] for row in page.context['roster']], ['Not started', 'Not started'])
        self.assertEqual(TestAttempt.objects.count(), 0)
        Enrollment.objects.create(course=self.course, student=self.outsider)
        self.assertContains(self.client.get(response.url), 'outsider')

    def test_teacher_cannot_assign_other_course_or_unknown_questions(self):
        self.client.force_login(self.other_teacher)
        data = {'course': self.course.pk, 'title': 'Invalid', 'question_ids': [self.choice['id']]}
        self.assertEqual(self.client.post(reverse('add_test'), data).status_code, 200)
        self.client.force_login(self.teacher)
        for selected in [[], ['unknown'], list(questions())[:51]]:
            data['question_ids'] = selected
            self.assertEqual(self.client.post(reverse('add_test'), data).status_code, 200)
        self.assertFalse(TestAssignment.objects.filter(title='Invalid').exists())

    def test_roster_and_test_are_scoped_to_course(self):
        roster = reverse('test_roster', args=[self.assignment.pk])
        test = reverse('take_test', args=[self.assignment.pk])
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(roster).status_code, 404)
        self.assertEqual(self.client.get(test).status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(test).status_code, 404)
        self.assertEqual(self.client.post(test, {'action': 'start'}).status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(roster).status_code, 403)
        self.assertEqual(self.client.get(reverse('add_test')).status_code, 403)

    def test_start_save_resume_submit_and_immutable_result(self):
        self.start()
        url = reverse('take_test', args=[self.assignment.pk])
        page = self.client.get(url)
        self.assertContains(page, self.choice['title'])
        self.assertNotContains(page, 'solutionHtml')
        self.assertNotContains(page, self.numeric['solutionHtml'])
        data = self.answers('save')
        data['q1_f0'] = ''
        self.assertEqual(self.client.post(url, data).status_code, 302)
        attempt = TestAttempt.objects.get()
        self.assertIsNone(attempt.submitted_at)
        self.assertContains(self.client.get('/assigned-tests/'), 'In progress')
        self.client.logout()
        self.client.force_login(self.student)
        page = self.client.get(url)
        self.assertEqual(page.context['form']['q0_f0'].value(), data['q0_f0'])
        self.assertEqual(self.client.post(url, self.answers()).status_code, 302)
        attempt.refresh_from_db()
        self.assertEqual(attempt.correct_count, 2)
        self.assertEqual(attempt.percentage, 100)
        self.assertEqual(attempt.student, self.student)
        self.assertContains(self.client.get(url), 'Test completed')
        saved_at = attempt.submitted_at
        self.client.post(url, {'action': 'save', 'q0_f0': 'invalid'})
        attempt.refresh_from_db()
        self.assertEqual(attempt.submitted_at, saved_at)
        self.assertEqual(attempt.correct_count, 2)
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse('test_roster', args=[self.assignment.pk])), '100%')
        self.assertContains(self.client.get('/assigned-tests/'), '1 / 2 completed')

    def test_incomplete_or_malformed_answers_cannot_complete(self):
        self.start()
        url = reverse('take_test', args=[self.assignment.pk])
        for data in [{'action': 'submit'}, {**self.answers(), 'q0_f0': 'invented'}]:
            self.assertEqual(self.client.post(url, data).status_code, 200)
            self.assertIsNone(TestAttempt.objects.get().submitted_at)
        numeric_index = next(i for i, f in enumerate(self.numeric['fields']) if f['kind'] == 'number')
        data = self.answers()
        data[f'q1_f{numeric_index}'] = 'not a number'
        response = self.client.post(url, data)
        self.assertContains(response, 'Enter a valid number or fraction.')
        self.assertIsNone(TestAttempt.objects.get().submitted_at)

    def test_wrong_answers_complete_but_do_not_gain_points(self):
        self.start()
        data = self.answers()
        field = self.choice['fields'][0]
        data['q0_f0'] = next(o['value'] for o in field['options'] if o['value'] != field['answer'])
        self.client.post(reverse('take_test', args=[self.assignment.pk]), data)
        attempt = TestAttempt.objects.get()
        self.assertIsNotNone(attempt.submitted_at)
        self.assertEqual(attempt.correct_count, 1)
        self.assertEqual(attempt.percentage, 50)

    def test_assigned_snapshot_survives_source_changes(self):
        self.start()
        before = deepcopy(self.assignment.question_snapshot)
        source = questions()[self.choice['id']]
        old = source['fields'][0]['answer']
        try:
            source['fields'][0]['answer'] = 'changed-source'
            self.client.post(reverse('take_test', args=[self.assignment.pk]), self.answers())
            self.assertEqual(TestAttempt.objects.get().correct_count, 2)
        finally:
            source['fields'][0]['answer'] = old
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.question_snapshot, before)

    def test_overdue_and_late_completion(self):
        self.assignment.due_at = timezone.now() - timedelta(days=1)
        self.assignment.save()
        self.start()
        self.assertContains(self.client.get('/assigned-tests/'), 'Overdue')
        self.client.post(reverse('take_test', args=[self.assignment.pk]), self.answers())
        self.assertContains(self.client.get('/assigned-tests/'), 'Completed late')
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse('test_roster', args=[self.assignment.pk])), 'Late completion')

    def test_teacher_preview_and_csrf(self):
        url = reverse('take_test', args=[self.assignment.pk])
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(url), 'Teacher preview')
        self.assertEqual(self.client.post(url, {'action': 'start'}).status_code, 403)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.student)
        self.assertEqual(client.post(url, {'action': 'start'}).status_code, 403)
        client.force_login(self.teacher)
        self.assertEqual(client.post(reverse('add_test'), {}).status_code, 403)

    def test_navigation_and_signout_across_local_site(self):
        self.assertContains(self.client.get('/site/index.html'), 'Sign in / Dashboard')
        self.assertEqual(self.client.get('/site/statistics.html').status_code, 200)
        self.assertEqual(self.client.get('/site/statistics-practice.html').status_code, 302)
        for user, label in [(self.student, 'Student'), (self.teacher, 'Teacher')]:
            self.client.force_login(user)
            for path in ['/', '/site/index.html', '/site/courses.html', '/site/statistics.html', '/site/publications.html', '/site/about-me.html']:
                page = self.client.get(path, follow=True)
                self.assertIn('no-store', page['Cache-Control'])
                self.assertContains(page, user.first_name)
                self.assertContains(page, 'Sign out')
                if path == '/':
                    self.assertContains(page, 'lms-topbar')
                    self.assertContains(page, f'· {label}')
                    self.assertContains(page, 'Dashboard</a>')
                    self.assertContains(page, f'data-account-id="{user.pk}"')
                else:
                    self.assertContains(page, 'Signed in as')
                    self.assertContains(page, f'platform-role">{label}')
                    self.assertContains(page, 'href="/">Dashboard')
            self.assertEqual(self.client.get('/logout/').status_code, 405)
            self.assertEqual(self.client.post('/logout/').status_code, 302)
            self.assertContains(self.client.get('/site/index.html'), 'Sign in / Dashboard')

    def test_login_remember_me_and_return_destination(self):
        data = {'username': 'student', 'password': 'a-long-test-password', 'next': '/site/statistics.html'}
        response = self.client.post('/login/', data)
        self.assertRedirects(response, '/site/statistics.html')
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.client.logout()
        self.client.post('/login/', {**data, 'remember': 'on', 'next': 'https://example.com/'})
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.assertEqual(self.client.session.get_expiry_age(), 14 * 24 * 60 * 60)

    def test_session_endpoint_and_stale_practice_account(self):
        self.assertIsNone(self.client.get('/api/session/').json()['account_id'])
        self.client.force_login(self.student)
        self.assertEqual(self.client.get('/api/session/').json()['account_id'], self.student.pk)
        response = self.client.post('/api/practice/attempt/', {'account_id': self.outsider.pk}, content_type='application/json')
        self.assertEqual(response.status_code, 409)
