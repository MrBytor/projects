import json
import uuid
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from .models import Assignment, Course, Enrollment, PracticeResult, Submission
from .scoring import number, questions, score


class PlatformTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('teacher', password='a-long-test-password', is_staff=True)
        cls.other_teacher = User.objects.create_user('otherteacher', password='a-long-test-password', is_staff=True)
        cls.student = User.objects.create_user('student', password='a-long-test-password')
        cls.other_student = User.objects.create_user('otherstudent', password='a-long-test-password')
        cls.course = Course.objects.create(slug='statistics', title='Statistics', image='statistics.jpg', teacher=cls.teacher)
        Enrollment.objects.create(student=cls.student, course=cls.course)
        cls.work = Assignment.objects.create(course=cls.course, title='Test homework', instructions='Explain your sampling method.')

    def login_as(self, user):
        self.client.force_login(user)

    def attempt(self, **changes):
        q = next(iter(questions().values()))
        data = {'account_id': self.student.pk, 'session_id': str(uuid.uuid4()), 'question_id': q['id'], 'answers': {f['id']: str(f['answer']) for f in q['fields']}, 'assisted': False}
        data.update(changes)
        return self.client.post('/api/practice/attempt/', json.dumps(data), content_type='application/json'), data

    def test_login_and_role_dashboards(self):
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertTrue(self.client.login(username='teacher', password='a-long-test-password'))
        self.assertContains(self.client.get('/'), 'Teacher workspace')
        self.login_as(self.student)
        self.assertContains(self.client.get('/'), 'My learning')
        self.assertEqual(self.client.get('/teacher/homework/new/').status_code, 403)

    def test_login_throttle(self):
        for _ in range(10):
            self.client.post('/login/', {'username': 'student', 'password': 'wrong'})
        self.assertEqual(self.client.post('/login/', {'username': 'student', 'password': 'wrong'}).status_code, 429)

    def test_csrf_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.student)
        self.assertEqual(client.post(reverse('assignment', args=[self.work.id]), {'answer': 'Test'}).status_code, 403)
        self.assertEqual(client.post('/api/practice/attempt/', '{}', content_type='application/json').status_code, 403)

    def test_enrollment_limits_access(self):
        self.login_as(self.other_student)
        self.assertEqual(self.client.get(reverse('assignment', args=[self.work.id])).status_code, 404)
        self.assertEqual(self.client.get('/site/statistics.html').status_code, 200)
        self.assertEqual(self.client.get('/site/statistics-practice.html').status_code, 404)
        response, _ = self.attempt()
        self.assertEqual(response.status_code, 404)

    def test_teacher_course_ownership(self):
        self.login_as(self.other_teacher)
        response = self.client.post('/teacher/homework/new/', {'course': self.course.id, 'title': 'Intrusion', 'instructions': 'Bad'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Assignment.objects.filter(title='Intrusion').exists())
        self.assertEqual(self.client.get(reverse('student_progress', args=[self.student.id])).status_code, 404)

    def test_create_student_ignores_role_injection(self):
        self.login_as(self.teacher)
        response = self.client.post('/teacher/students/new/', {'username': 'new-student', 'first_name': 'New', 'password1': 'a-distinct-long-passphrase-123', 'password2': 'a-distinct-long-passphrase-123', 'courses': [self.course.id], 'is_staff': True, 'is_superuser': True})
        self.assertEqual(response.status_code, 302)
        student = User.objects.get(username='new-student')
        self.assertFalse(student.is_staff)
        self.assertFalse(student.is_superuser)
        self.assertTrue(Enrollment.objects.filter(student=student, course=self.course).exists())

    def test_homework_feedback_and_resubmission(self):
        self.login_as(self.student)
        response = self.client.post(reverse('assignment', args=[self.work.id]), {'answer': '<script>alert(1)</script> Stratified sample.'})
        self.assertEqual(response.status_code, 302)
        submission = Submission.objects.get()
        self.login_as(self.other_teacher)
        self.assertEqual(self.client.get(reverse('review', args=[submission.id])).status_code, 404)
        self.login_as(self.teacher)
        self.assertContains(self.client.get(reverse('review', args=[submission.id])), '&lt;script&gt;')
        self.client.post(reverse('review', args=[submission.id]), {'feedback': 'Explain your strata.', 'score': 75})
        self.login_as(self.student)
        self.assertContains(self.client.get(reverse('assignment', args=[self.work.id])), 'Explain your strata.')
        self.client.post(reverse('assignment', args=[self.work.id]), {'answer': 'Updated answer.'})
        submission.refresh_from_db()
        self.assertIsNone(submission.graded_at)
        self.assertEqual(submission.feedback, '')

    def test_grade_validation(self):
        submission = Submission.objects.create(assignment=self.work, student=self.student, answer='Answer')
        self.login_as(self.teacher)
        self.client.post(reverse('review', args=[submission.id]), {'score': 101, 'feedback': 'Invalid'})
        submission.refresh_from_db()
        self.assertIsNone(submission.score)

    def test_saved_practice_survives_login_and_is_private(self):
        self.login_as(self.student)
        response, _ = self.attempt(student_id=self.other_student.id, correct=False)
        self.assertEqual(response.status_code, 200)
        result = PracticeResult.objects.get()
        self.assertEqual(result.student, self.student)
        self.assertTrue(result.first_correct)
        self.client.logout()
        self.login_as(self.student)
        self.assertContains(self.client.get('/learning-progress/'), result.objective_ids[0])
        self.login_as(self.other_student)
        self.assertContains(self.client.get('/learning-progress/'), 'No practice evidence yet')

    def test_first_attempt_is_immutable_on_retry(self):
        self.login_as(self.student)
        q = next(iter(questions().values()))
        field = q['fields'][0]
        wrong = next(o['value'] for o in field['options'] if o['value'] != field['answer'])
        response, data = self.attempt(answers={field['id']: wrong}, assisted=True, correct=True)
        self.assertEqual(response.status_code, 200)
        data['answers'] = {field['id']: field['answer']}
        data['assisted'] = False
        self.client.post('/api/practice/attempt/', json.dumps(data), content_type='application/json')
        result = PracticeResult.objects.get()
        self.assertFalse(result.first_correct)
        self.assertTrue(result.first_assisted)
        self.assertTrue(result.latest_correct)
        self.assertEqual(PracticeResult.objects.count(), 1)

    def test_invalid_practice_is_not_saved(self):
        self.login_as(self.student)
        for changes in [{'answers': {}}, {'question_id': 'invented'}, {'session_id': 'bad'}, {'assisted': 'false'}]:
            response, _ = self.attempt(**changes)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(PracticeResult.objects.count(), 0)

    def test_teacher_preview_does_not_record(self):
        self.login_as(self.teacher)
        response, _ = self.attempt()
        self.assertEqual(response.status_code, 403)

    def test_local_course_and_asset_routes(self):
        self.login_as(self.student)
        response = self.client.get('/site/statistics-practice.html')
        self.assertContains(response, 'practice-bridge.js')
        self.assertIn('no-store', response['Cache-Control'])
        for path in ['../learning-platform/manage.py', '.git/config', 'README.md']:
            self.assertEqual(self.client.get('/site/' + path).status_code, 404)
        self.assertEqual(self.client.get('/site/assets/statistics-practice.js').status_code, 200)

    def test_teacher_progress_multiple_enrollments(self):
        course = Course.objects.create(slug='finance', title='Finance', teacher=self.teacher)
        Enrollment.objects.create(course=course, student=self.student)
        self.login_as(self.teacher)
        self.assertEqual(self.client.get(reverse('student_progress', args=[self.student.id])).status_code, 200)


class ScoringTests(TestCase):
    def test_all_bank_answers_at_requested_precision(self):
        for q in questions().values():
            answers = {f['id']: str(f['answer']) if f['kind'] == 'choice' else f"{f['answer']:.{f.get('decimals', 0)}f}" for f in q['fields']}
            self.assertEqual(score(q, answers), (True, True), q['id'])
            self.assertEqual(score(q, {}), (False, False), q['id'])

    def test_number_boundaries(self):
        self.assertEqual(number('1,234.5'), 1234.5)
        self.assertEqual(number('1/4'), .25)
        self.assertEqual(number('25%', True), 25)
        for raw in ['1/0', '1e3', '4junk', 'NaN', '1,00', '', '25%']:
            self.assertIsNone(number(raw), raw)
        q = {'fields': [{'id': 'n', 'kind': 'number', 'answer': 3, 'exact': True, 'integer': True}]}
        self.assertEqual(score(q, {'n': '3.01'}), (True, False))
