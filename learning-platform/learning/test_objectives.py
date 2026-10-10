import uuid
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Course, Enrollment, PracticeResult, TestAssignment, TestAttempt
from .objectives import finance_objectives, objective_evidence
from .scoring import bank, questions


class LearningObjectiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('teacher', is_staff=True)
        cls.other_teacher = User.objects.create_user('other-teacher', is_staff=True)
        cls.student = User.objects.create_user('student')
        cls.other_student = User.objects.create_user('other-student')
        cls.stats = Course.objects.create(slug='statistics', title='Statistics', teacher=cls.teacher)
        cls.finance = Course.objects.create(slug='corporate-finance', title='Finance', teacher=cls.teacher)
        cls.private = Course.objects.create(slug='private', title='Private course', teacher=cls.other_teacher)
        Enrollment.objects.create(student=cls.student, course=cls.stats)
        Enrollment.objects.create(student=cls.other_student, course=cls.stats)
        Enrollment.objects.create(student=cls.student, course=cls.private)

    def practice(self, ident='1A.1', question='sample', **values):
        return PracticeResult.objects.create(student=self.student, course=self.stats, session_id=uuid.uuid4(),
                                             question_id=question, objective_ids=[ident], first_correct=True,
                                             first_assisted=False, latest_correct=True, answers={}, **values)

    def evidence(self, ident='1A.1'):
        return next(r for r in objective_evidence(self.student, [self.stats])[0] if r['id'] == ident)

    def test_catalogue_includes_unpractised_goals_and_focused_links(self):
        rows, next_steps = objective_evidence(self.student, [self.stats])
        self.assertEqual(len(rows), len(bank()['objectives']))
        self.assertEqual(len(next_steps), 4)
        row = next(r for r in rows if r['id'] == '1A.1')
        self.assertEqual(row['status'], 'Not yet practised')
        self.assertEqual(row['evidence_count'], 0)
        self.assertEqual(row['lesson_url'], '/courses/statistics/classes/1-a/#objective-1a-1')
        self.assertIn('objective=1A.1', row['practice_url'])
        self.client.force_login(self.student)
        response = self.client.get(reverse('learning_progress'))
        self.assertContains(response, 'Suggested next steps')
        self.assertContains(response, 'No practice evidence yet')
        self.assertEqual(len(response.context['progress']), 20)

    def test_finance_goals_reuse_published_classes_without_fake_results(self):
        catalogue = finance_objectives()
        self.assertEqual(len(catalogue), 64)
        self.assertEqual(catalogue[0]['label'], 'Define corporate finance and the role of the financial manager.')
        rows, recommended = objective_evidence(self.student, [self.finance])
        self.assertEqual(len(rows), 64)
        self.assertEqual(rows[0]['lesson_url'], '/courses/corporate-finance/classes/1-main/#objective-1-1')
        self.assertFalse(recommended)
        self.assertTrue(all(not r.get('practice_url') and not r['evidence_count'] for r in rows))

    def test_repeated_question_does_not_claim_consistent_results(self):
        for _ in range(3):
            self.practice()
        row = self.evidence()
        self.assertEqual(row['unique_questions'], 1)
        self.assertEqual(row['independent'], 3)
        self.assertEqual(row['status'], 'Building evidence')
        self.practice(question='second')
        self.practice(question='third')
        self.assertEqual(self.evidence()['status'], 'Consistent results')

    def test_first_attempt_with_help_and_retries_stay_distinct(self):
        result = self.practice()
        result.first_correct = False
        result.latest_correct = True
        result.save()
        assisted = self.practice(question='helped')
        assisted.first_assisted = True
        assisted.save()
        row = self.evidence()
        self.assertEqual(row['attempted'], 2)
        self.assertEqual(row['independent'], 0)
        self.assertEqual(row['assisted'], 1)
        self.assertEqual(row['latest'], 2)
        self.assertEqual(row['status'], 'Practise next')
        self.assertEqual(objective_evidence(self.student, [self.stats])[1][0]['id'], '1A.1')

    def test_only_submitted_frozen_answers_count_and_fields_map_separately(self):
        question = {'id': 'frozen', 'primaryObjective': '1A.1', 'fields': [
            {'id': 'a', 'kind': 'number', 'answer': 2, 'decimals': 0, 'objectiveIds': ['1A.1']},
            {'id': 'b', 'kind': 'number', 'answer': 4, 'decimals': 0, 'objectiveIds': ['1A.2']},
        ]}
        test = TestAssignment.objects.create(course=self.stats, title='Frozen question', question_snapshot=[question])
        attempt = TestAttempt.objects.create(student=self.student, assignment=test, answers={'frozen': {'a': '0', 'b': '4'}}, correct_count=0)
        self.assertEqual(self.evidence()['tested'], 0)
        attempt.submitted_at = timezone.now()
        attempt.save()
        self.assertEqual(self.evidence()['test_correct'], 0)
        self.assertEqual(self.evidence()['tested'], 1)
        self.assertEqual(self.evidence('1A.2')['test_correct'], 1)
        attempt.refresh_from_db()
        self.assertEqual(attempt.correct_count, 0)
        self.assertEqual(self.evidence('1A.2')['status'], 'Building evidence')

    def test_total_grade_without_answers_does_not_invent_objective_evidence(self):
        question = next(iter(questions().values()))
        test = TestAssignment.objects.create(course=self.stats, title='Legacy totals', question_snapshot=[question])
        TestAttempt.objects.create(student=self.student, assignment=test, submitted_at=timezone.now(), correct_count=1)
        self.assertEqual(self.evidence(question['primaryObjective'])['tested'], 0)

    def test_student_teacher_and_enrolment_scope_and_filters(self):
        PracticeResult.objects.create(student=self.other_student, course=self.stats, session_id=uuid.uuid4(), question_id='other',
                                      objective_ids=['1A.1'], first_correct=False, first_assisted=False, latest_correct=False, answers={})
        PracticeResult.objects.create(student=self.student, course=self.private, session_id=uuid.uuid4(), question_id='secret',
                                      objective_ids=['Secret objective'], first_correct=True, first_assisted=False, latest_correct=True, answers={})
        self.assertEqual(self.evidence()['evidence_count'], 0)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('student_progress', args=[self.student.pk]))
        self.assertNotContains(response, 'Secret objective')
        self.assertEqual(response.context['attempts'], 0)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('learning_progress'), {'course': self.finance.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse('learning_progress'), {'course': 'invalid'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('learning_progress'), {'status': 'invalid'}).status_code, 404)
        self.practice()
        response = self.client.get(reverse('learning_progress'), {'course': self.stats.pk, 'status': 'practised'})
        self.assertEqual(len(response.context['progress']), 1)
        self.assertEqual(response.context['summary']['observed'], 1)
        Enrollment.objects.filter(student=self.student, course=self.stats).delete()
        response = self.client.get(reverse('learning_progress'))
        self.assertFalse(any(r['course'].pk == self.stats.pk for r in response.context['progress']))
        self.assertEqual(response.context['attempts'], 1)  # The other enrolled course still contributes personal evidence.

    def test_filtered_page_preserves_course_and_status(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('learning_progress'), {'course': self.stats.pk, 'status': 'unattempted', 'page': 2})
        self.assertEqual(response.context['page'].number, 2)
        self.assertEqual(response.context['summary']['observed'], 0)
        self.assertIn('status=unattempted', response.context['page_query'])
        self.assertIn(f'course={self.stats.pk}', response.context['page_query'])
