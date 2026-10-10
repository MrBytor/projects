from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .curriculum import outline, get_lesson, quick_questions, trusted_material
from .models import Course, Enrollment, LessonPractice, PracticeResult, TestAssignment, TestAttempt


class CourseWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('teacher', first_name='Jacob', is_staff=True)
        cls.foreign = User.objects.create_user('foreign-teacher', is_staff=True)
        cls.student = User.objects.create_user('student', first_name='Student')
        cls.other = User.objects.create_user('other-student')
        cls.stats = Course.objects.create(slug='statistics', title='Statistics', teacher=cls.teacher)
        cls.finance = Course.objects.create(slug='corporate-finance', title='Corporate Finance', teacher=cls.teacher)
        cls.project = Course.objects.create(slug='project-management', title='Project Management', teacher=cls.foreign)
        Enrollment.objects.create(student=cls.student, course=cls.stats)
        Enrollment.objects.create(student=cls.other, course=cls.stats)

    def setUp(self):
        self.private = TemporaryDirectory()
        self.addCleanup(self.private.cleanup)
        self.override = override_settings(DATA_DIR=Path(self.private.name))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.client.force_login(self.student)
        self.lesson_url = reverse('course_lesson', args=['statistics', '1-b'])

    def payload(self, correct=True, action='check'):
        snapshot = self.client.get(self.lesson_url).context['quick_form'].snapshot
        data = {'action': action, 'account_id': str(self.student.pk)}
        for qi, q in enumerate(snapshot):
            for fi, field in enumerate(q['fields']):
                answer = field['answer']
                if not correct:
                    answer = next(o['value'] for o in field['options'] if o['value'] != answer) if field['kind'] == 'choice' else '999999'
                data[f'q{qi}_f{fi}'] = str(answer)
        return data

    def test_real_outline_classes_materials_and_objectives(self):
        self.assertEqual(sum(len(m['lessons']) for m in outline('statistics')), 40)
        self.assertEqual(sum(len(m['lessons']) for m in outline('corporate-finance')), 16)
        self.assertEqual(sum(len(m['lessons']) for m in outline('project-management')), 16)
        lesson = get_lesson('statistics', '1-b')
        self.assertEqual(lesson['title'], 'Calculations in context')
        self.assertEqual(lesson['materials'][0]['name'], 'IFY_Statistics_Week_1_Class_B.pptx')
        self.assertTrue(any(o['anchor'] == 'objective-1b-4' for o in lesson['objectives']))
        self.assertTrue(any('Vocabulary' in m['name'] for m in lesson['materials']))
        for slug in ('statistics', 'corporate-finance', 'project-management'):
            lessons = [l for m in outline(slug) for l in m['lessons']]
            self.assertEqual(len(lessons), len({l['key'] for l in lessons}))
        for bad in ('../learning-platform/manage.py', '/etc/passwd', 'https://example.test/a.pptx', 'materials/../../learning-platform/manage.py'):
            self.assertIsNone(trusted_material(bad))

    def test_course_access_and_public_site_separation(self):
        self.assertContains(self.client.get(reverse('course_workspace', args=['statistics'])), 'Module 1')
        self.assertEqual(self.client.get(reverse('course_workspace', args=['corporate-finance'])).status_code, 404)
        self.assertContains(self.client.get(self.lesson_url), 'lms-topbar')
        self.assertNotContains(self.client.get(self.lesson_url), 'platform-banner')
        self.assertNotContains(self.client.get('/site/statistics.html'), 'lms.css')
        self.client.logout()
        self.assertEqual(self.client.get(self.lesson_url).status_code, 302)
        self.assertEqual(self.client.get('/site/statistics.html').status_code, 200)
        self.assertEqual(self.client.get(reverse('course_practice')).status_code, 302)

    def test_draft_resumes_without_grading_or_learning_evidence(self):
        data = self.payload(action='save')
        data['q0_f0'] = 'unfinished calculation'
        self.assertRedirects(self.client.post(self.lesson_url, data), self.lesson_url)
        practice = LessonPractice.objects.get(student=self.student)
        self.assertEqual(practice.answers[practice.question_snapshot[0]['id']][practice.question_snapshot[0]['fields'][0]['id']], 'unfinished calculation')
        self.assertFalse(PracticeResult.objects.exists())
        self.assertFalse(TestAttempt.objects.exists())
        self.assertContains(self.client.get(self.lesson_url), 'unfinished calculation')
        self.client.get(self.lesson_url)
        self.assertEqual(LessonPractice.objects.count(), 1)

    def test_check_and_retry_preserve_first_attempt_and_assigned_grades(self):
        homework = TestAssignment.objects.create(course=self.stats, title='Independent homework', question_snapshot=[])
        attempt = TestAttempt.objects.create(student=self.student, assignment=homework, correct_count=0, submitted_at=timezone.now())
        self.client.post(self.lesson_url, self.payload(correct=False))
        self.assertTrue(PracticeResult.objects.exists())
        self.assertFalse(PracticeResult.objects.filter(first_correct=True).exists())
        self.client.post(self.lesson_url, self.payload(correct=True))
        self.assertFalse(PracticeResult.objects.filter(first_correct=True).exists())
        self.assertFalse(PracticeResult.objects.filter(latest_correct=False).exists())
        practice = LessonPractice.objects.get(student=self.student)
        self.assertEqual(PracticeResult.objects.count(), len(practice.question_snapshot))
        self.assertTrue(all(r['correct'] for r in practice.last_results))
        invalid = self.payload(); invalid['q0_f0'] = 'unfinished'
        self.assertNotContains(self.client.post(self.lesson_url, invalid), '✓ Correct')
        attempt.refresh_from_db()
        self.assertEqual(attempt.correct_count, 0)

    def test_invalid_or_stale_account_answers_never_record_evidence(self):
        data = self.payload()
        data['q0_f0'] = 'not a number'
        self.assertEqual(self.client.post(self.lesson_url, data).status_code, 200)
        self.assertFalse(PracticeResult.objects.exists())
        data = self.payload(); data['account_id'] = str(self.other.pk)
        self.assertEqual(self.client.post(self.lesson_url, data).status_code, 403)
        self.assertFalse(PracticeResult.objects.exists())
        protected = Client(enforce_csrf_checks=True); protected.force_login(self.student)
        self.assertEqual(protected.post(self.lesson_url, self.payload()).status_code, 403)

    def test_revoked_access_blocks_saved_lessons_and_materials(self):
        data = self.payload(action='save')
        self.client.post(self.lesson_url, data)
        saved = deepcopy(LessonPractice.objects.get(student=self.student).answers)
        Enrollment.objects.filter(student=self.student, course=self.stats).delete()
        for url in (self.lesson_url, reverse('course_workspace', args=['statistics']), reverse('course_practice'), reverse('lesson_material', args=['statistics', '1-b', 0]), reverse('lesson_slide', args=['statistics', '1-b', 0, 1])):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(self.lesson_url, data).status_code, 404)
        self.assertEqual(LessonPractice.objects.get(student=self.student).answers, saved)
        Enrollment.objects.create(student=self.student, course=self.stats)
        self.assertEqual(self.client.get(self.lesson_url).status_code, 200)

    def test_student_drafts_are_private(self):
        data = self.payload(action='save'); data['q0_f0'] = 'private draft'
        self.client.post(self.lesson_url, data)
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(self.lesson_url), 'private draft')
        self.assertEqual(LessonPractice.objects.get(student=self.other).answers, {})

    def test_teacher_preview_and_foreign_course_permissions(self):
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(self.lesson_url), 'Teacher preview')
        self.assertFalse(LessonPractice.objects.exists())
        self.assertEqual(self.client.post(self.lesson_url, {'action': 'check'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('course_workspace', args=['project-management'])).status_code, 404)
        self.assertContains(self.client.get(reverse('student_courses')), 'Teaching courses')
        self.assertNotContains(self.client.get('/'), 'My courses')

    def test_preview_slide_access_and_bounds(self):
        folder = Path(self.private.name)
        (folder / 'Slide1.PNG').write_bytes(b'PNG test fixture')
        preview = {'folder': folder, 'count': 1}
        with patch('learning.workspace_views.presentation_preview', return_value=preview):
            response = self.client.get(self.lesson_url)
            self.assertContains(response, 'data-slide-viewer')
            self.assertContains(response, 'id="objective-1b-4"')
            slide = self.client.get(reverse('lesson_slide', args=['statistics', '1-b', 0, 1]))
            self.assertEqual(b''.join(slide.streaming_content), b'PNG test fixture')
            self.assertIn('no-store', slide['Cache-Control'])
            for index, number in ((0, 0), (0, 2), (1, 1), (99, 1)):
                self.assertEqual(self.client.get(reverse('lesson_slide', args=['statistics', '1-b', index, number])).status_code, 404)

    def test_ppt_download_uses_trusted_original(self):
        response = self.client.get(reverse('lesson_material', args=['statistics', '1-b', 0]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('IFY_Statistics_Week_1_Class_B.pptx', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        response.close()
        self.assertEqual(self.client.get(reverse('lesson_material', args=['statistics', '1-b', 99])).status_code, 404)

    def test_finance_and_project_lessons_do_not_fabricate_materials_or_questions(self):
        Enrollment.objects.create(student=self.student, course=self.finance)
        finance = self.client.get(reverse('course_lesson', args=['corporate-finance', '1-main']))
        self.assertContains(finance, 'Define corporate finance')
        self.assertNotContains(finance, 'Check answers')
        self.assertFalse(quick_questions('project-management', get_lesson('project-management', '1-main')))
        self.assertEqual(self.client.get(reverse('course_lesson', args=['statistics', 'bad-key'])).status_code, 404)

    def test_teacher_calendar_only_shows_owned_test_deadlines(self):
        TestAssignment.objects.create(course=self.stats, title='Owned deadline', due_at=timezone.now())
        TestAssignment.objects.create(course=self.project, title='Foreign private deadline', due_at=timezone.now())
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('student_calendar'))
        self.assertContains(response, 'Owned deadline')
        self.assertNotContains(response, 'Foreign private deadline')
        self.assertEqual(response.context['event_count'], 1)
