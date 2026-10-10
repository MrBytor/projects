from datetime import timedelta
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from .models import Course, Enrollment, StudentRegistration, TestAssignment, TestAttempt
from .scoring import questions


class DashboardFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('teacher', is_staff=True)
        cls.other_teacher = User.objects.create_user('other-teacher', is_staff=True)
        cls.stats = Course.objects.create(slug='statistics', title='Statistics', teacher=cls.teacher)
        cls.finance = Course.objects.create(slug='corporate-finance', title='Corporate Finance', teacher=cls.teacher)
        cls.project = Course.objects.create(slug='project-management', title='Project Management', teacher=cls.teacher)
        cls.other_course = Course.objects.create(slug='other', title='Private course', teacher=cls.other_teacher)
        for name, major, group, courses in [
            ('Alice', 'Accounting', '2026 A', [cls.stats, cls.finance]),
            ('Ben', 'Accounting', '2026 B', [cls.stats]),
            ('Cara', 'Finance', '2026 A', [cls.stats]),
            ('Dan', '', '', []),
            ('Eva', 'Accounting', '2026 A', [cls.project]),
        ]:
            student = User.objects.create_user(name.lower(), first_name=name, email=f'{name.lower()}@example.test')
            setattr(cls, name.lower(), student)
            StudentRegistration.objects.create(teacher=cls.teacher, student=student, major=major, teaching_group=group)
            for course in courses:
                Enrollment.objects.create(student=student, course=course)
        cls.outsider = User.objects.create_user('outsider', first_name='Private student')
        StudentRegistration.objects.create(teacher=cls.other_teacher, student=cls.outsider, major='Private major', teaching_group='Private group')
        Enrollment.objects.create(student=cls.outsider, course=cls.other_course)
        Enrollment.objects.create(student=cls.alice, course=cls.other_course)
        StudentRegistration.objects.create(teacher=cls.other_teacher, student=cls.alice, major='Other classification', teaching_group='Other group')
        snapshot = [next(iter(questions().values()))] * 4
        cls.past = TestAssignment.objects.create(course=cls.stats, title='Statistics class A', week=1, class_label='Class A', due_at=timezone.now() - timedelta(days=1), question_snapshot=snapshot)
        cls.future = TestAssignment.objects.create(course=cls.stats, title='Statistics class B', week=2, class_label='Class B', due_at=timezone.now() + timedelta(days=1), question_snapshot=snapshot)
        cls.finance_test = TestAssignment.objects.create(course=cls.finance, title='Finance class A', week=1, class_label='Class A', due_at=timezone.now() - timedelta(days=1), question_snapshot=snapshot)
        cls.private_test = TestAssignment.objects.create(course=cls.other_course, title='Private test', week=1, class_label='Private session', question_snapshot=snapshot)
        for student, assignment, points in [(cls.alice, cls.past, 4), (cls.alice, cls.finance_test, 2), (cls.cara, cls.past, 0), (cls.cara, cls.future, 2), (cls.outsider, cls.past, 4)]:
            TestAttempt.objects.create(student=student, assignment=assignment, correct_count=points, submitted_at=timezone.now())
        TestAttempt.objects.create(student=cls.ben, assignment=cls.past, correct_count=4, answers={'draft': 'saved'})

    def setUp(self):
        self.client.force_login(self.teacher)

    def student_names(self, params=None):
        page = self.client.get(reverse('student_directory'), params or {})
        self.assertEqual(page.status_code, 200)
        return {row['student'].first_name for row in page.context['rows']}

    def test_combined_major_group_and_course_filters(self):
        self.assertEqual(self.student_names({'major': 'Accounting'}), {'Alice', 'Ben', 'Eva'})
        self.assertEqual(self.student_names({'teaching_group': '2026 A'}), {'Alice', 'Cara', 'Eva'})
        self.assertEqual(self.student_names({'course': self.stats.pk}), {'Alice', 'Ben', 'Cara'})
        self.assertEqual(self.student_names({'major': 'Accounting', 'teaching_group': '2026 A', 'course': self.stats.pk}), {'Alice'})
        self.assertEqual(self.student_names({'major': '__missing__', 'teaching_group': '__missing__'}), {'Dan'})

    def test_coursework_filters_count_only_current_enrolments(self):
        self.assertEqual(self.student_names({'status': 'completed'}), {'Cara'})
        self.assertEqual(self.student_names({'status': 'outstanding'}), {'Alice', 'Ben'})
        self.assertEqual(self.student_names({'status': 'overdue'}), {'Ben'})
        self.assertEqual(self.student_names({'status': 'no_tests'}), {'Dan', 'Eva'})
        self.assertEqual(self.student_names({'status': 'no_courses'}), {'Dan'})
        page = self.client.get(reverse('student_directory'))
        alice = next(row for row in page.context['rows'] if row['student'].pk == self.alice.pk)
        self.assertEqual((alice['assigned'], alice['completed'], alice['overdue']), (3, 2, 0))
        self.assertEqual(page.context['registered_count'], 5)

    def test_course_filter_scopes_completion_and_overdue_counts(self):
        self.assertEqual(self.student_names({'course': self.finance.pk, 'status': 'completed'}), {'Alice'})
        page = self.client.get(reverse('student_directory'), {'course': self.finance.pk})
        self.assertEqual([(r['assigned'], r['completed']) for r in page.context['rows']], [(1, 1)])
        self.assertEqual(self.student_names({'course': self.stats.pk, 'status': 'overdue'}), {'Ben'})

    def test_directory_filters_and_choices_are_teacher_scoped(self):
        page = self.client.get(reverse('student_directory'))
        for private in ['Private student', 'Private major', 'Private group', 'Other classification', 'Other group', 'Private course']:
            self.assertNotContains(page, private)
        self.assertEqual(self.student_names({'course': self.other_course.pk}), set())
        self.assertEqual(self.student_names({'major': 'Private major'}), set())
        self.assertEqual(self.student_names({'status': 'unknown'}), set())
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('student_directory')).status_code, 403)

    def test_edit_student_saves_metadata_for_current_teacher_and_keeps_filters(self):
        url = reverse('edit_student', args=[self.alice.pk]) + '?major=Accounting&page=2'
        before = self.client.get(url)
        self.assertEqual(before.context['form']['major'].value(), 'Accounting')
        response = self.client.post(url, {'first_name': 'Alice', 'email': 'alice@example.test', 'major': 'Business', 'teaching_group': '2027 A'})
        self.assertEqual(response.url, reverse('student_directory') + '?major=Accounting&page=2')
        registration = StudentRegistration.objects.get(student=self.alice, teacher=self.teacher)
        self.assertEqual((registration.major, registration.teaching_group), ('Business', '2027 A'))
        self.assertEqual(StudentRegistration.objects.get(student=self.alice, teacher=self.other_teacher).major, 'Other classification')
        invalid = self.client.post(url, {'first_name': 'Alice', 'email': 'alice@example.test', 'major': 'x' * 121, 'teaching_group': 'Changed'})
        self.assertEqual(invalid.status_code, 200)
        registration.refresh_from_db()
        self.assertEqual(registration.teaching_group, '2027 A')

    def test_new_student_metadata_and_course_access_preserve_directory_filter(self):
        response = self.client.post(reverse('add_student'), {'username': 'new', 'first_name': 'New student', 'major': 'Accounting', 'teaching_group': '2026 A', 'courses': [self.stats.pk], 'password1': 'a-distinct-passphrase-6789', 'password2': 'a-distinct-passphrase-6789'})
        self.assertEqual(response.status_code, 302)
        student = User.objects.get(username='new')
        registration = StudentRegistration.objects.get(student=student, teacher=self.teacher)
        self.assertEqual((registration.major, registration.teaching_group), ('Accounting', '2026 A'))
        url = reverse('update_student_access', args=[student.pk]) + '?major=Accounting&course=' + str(self.stats.pk)
        response = self.client.post(url, {'courses': [self.finance.pk]})
        self.assertEqual(response.url, reverse('student_directory') + '?major=Accounting&course=' + str(self.stats.pk))
        self.assertTrue(Enrollment.objects.filter(student=student, course=self.finance).exists())
        registration.refresh_from_db()
        self.assertEqual(registration.major, 'Accounting')

    def test_directory_pagination_preserves_filters_without_duplicate_students(self):
        for index in range(28):
            student = User.objects.create_user(f'extra-{index:02}', first_name=f'Extra {index:02}')
            StudentRegistration.objects.create(teacher=self.teacher, student=student, major='Accounting', teaching_group='2026 A')
            Enrollment.objects.bulk_create([Enrollment(student=student, course=c) for c in [self.stats, self.finance]])
        params = {'major': 'Accounting', 'teaching_group': '2026 A'}
        first = self.client.get(reverse('student_directory'), params)
        second = self.client.get(reverse('student_directory'), {**params, 'page': 2})
        self.assertEqual(first.context['page'].paginator.count, 30)
        self.assertEqual(len(first.context['rows']), 25)
        self.assertEqual(len(second.context['rows']), 5)
        ids = [r['student'].pk for page in [first, second] for r in page.context['rows']]
        self.assertEqual(len(set(ids)), 30)
        self.assertContains(first, 'major=Accounting&amp;teaching_group=2026+A&amp;page=2')
        self.assertEqual(self.client.get(reverse('student_directory'), {**params, 'page': 'invalid'}).context['page'].number, 1)

    def test_directory_queries_do_not_grow_per_student(self):
        # Warm template/bank caches, then compare one populated page with another.
        self.client.get(reverse('student_directory'))
        with CaptureQueriesContext(connection) as small:
            self.client.get(reverse('student_directory'))
        for index in range(22):
            student = User.objects.create_user(f'query-{index:02}', first_name=f'Query {index:02}')
            StudentRegistration.objects.create(teacher=self.teacher, student=student)
            Enrollment.objects.create(student=student, course=self.stats)
        with CaptureQueriesContext(connection) as large:
            page = self.client.get(reverse('student_directory'))
        self.assertEqual(len(page.context['rows']), 25)
        self.assertLessEqual(len(large), len(small) + 1)
        self.assertLessEqual(len(large), 13)

    def test_tests_group_filter_and_summary_are_teacher_scoped(self):
        page = self.client.get(reverse('assigned_tests'))
        self.assertEqual(page.context['page'].paginator.count, 3)
        self.assertNotContains(page, 'Private test')
        self.assertNotContains(page, 'Private session')
        self.assertContains(page, 'Week 1 · Class A')
        self.assertContains(page, '2 / 3 completed')
        self.assertContains(page, '1 / 1 completed')
        for params, expected in [
            ({'course': self.stats.pk, 'week': '1', 'class_label': 'Class A'}, [self.past.pk]),
            ({'status': 'completed'}, [self.finance_test.pk]),
            ({'status': 'outstanding'}, [self.past.pk, self.future.pk]),
            ({'status': 'overdue'}, [self.past.pk]),
            ({'course': self.other_course.pk}, []),
            ({'class_label': 'Private session'}, []),
        ]:
            response = self.client.get(reverse('assigned_tests'), params)
            self.assertCountEqual([a.pk for a in response.context['page'].object_list], expected)

    def test_test_pagination_missing_labels_sort_and_queries(self):
        self.client.get(reverse('assigned_tests'))
        with CaptureQueriesContext(connection) as small:
            self.client.get(reverse('assigned_tests'))
        for index in range(24):
            TestAssignment.objects.create(course=self.stats, title=f'Additional test {index:02}', week=1, class_label='Class A', question_snapshot=self.past.question_snapshot)
        with CaptureQueriesContext(connection) as large:
            page = self.client.get(reverse('assigned_tests'), {'course': self.stats.pk, 'week': '1', 'class_label': 'Class A', 'sort': 'newest'})
        self.assertEqual(page.context['page'].paginator.count, 25)
        self.assertEqual(len(page.context['page'].object_list), 20)
        self.assertLessEqual(len(large), len(small) + 2)
        self.assertLessEqual(len(large), 10)
        self.assertTrue(all('question_snapshot' in a.get_deferred_fields() for a in page.context['page'].object_list))
        self.assertContains(page, f'course={self.stats.pk}&amp;week=1&amp;class_label=Class+A&amp;sort=newest&amp;page=2')
        second = self.client.get(reverse('assigned_tests'), {'course': self.stats.pk, 'week': 1, 'class_label': 'Class A', 'page': 2})
        self.assertEqual(len(second.context['page'].object_list), 5)
        general = TestAssignment.objects.create(course=self.stats, title='General test')
        page = self.client.get(reverse('assigned_tests'), {'week': '__missing__', 'class_label': '__missing__'})
        self.assertEqual([a.pk for a in page.context['page'].object_list], [general.pk])
        self.assertContains(page, 'General tests')
        due = self.client.get(reverse('assigned_tests'), {'sort': 'due'})
        self.assertIsNone(list(due.context['page'].object_list)[-1].due_at)

    def test_student_test_filters_show_only_enrolled_work(self):
        self.client.force_login(self.ben)
        for status, expected in [('not_started', [self.future.pk]), ('in_progress', [self.past.pk]), ('completed', []), ('outstanding', [self.past.pk, self.future.pk]), ('overdue', [self.past.pk])]:
            page = self.client.get(reverse('assigned_tests'), {'status': status})
            self.assertCountEqual([a.pk for a in page.context['page'].object_list], expected)
        page = self.client.get(reverse('assigned_tests'))
        self.assertNotContains(page, 'Finance class A')
        self.assertNotContains(page, 'Private test')
        self.assertNotContains(page, 'Organise')
        self.client.force_login(self.cara)
        page = self.client.get(reverse('assigned_tests'), {'week': 1, 'status': 'completed'})
        self.assertContains(page, '0 points · 0%')

    def test_grouping_edit_preserves_frozen_questions_and_results(self):
        url = reverse('organise_test', args=[self.past.pk])
        snapshot = self.past.question_snapshot
        before = list(TestAttempt.objects.filter(assignment=self.past).values('pk', 'answers', 'correct_count', 'submitted_at'))
        response = self.client.post(url, {'week': 3, 'class_label': 'Session 2', 'question_snapshot': '[]', 'course': self.other_course.pk, 'title': 'Changed'})
        self.assertEqual(response.url, reverse('assigned_tests'))
        self.past.refresh_from_db()
        self.assertEqual((self.past.week, self.past.class_label), (3, 'Session 2'))
        self.assertEqual(self.past.title, 'Statistics class A')
        self.assertEqual(self.past.course_id, self.stats.pk)
        self.assertEqual(self.past.question_snapshot, snapshot)
        self.assertEqual(list(TestAttempt.objects.filter(assignment=self.past).values('pk', 'answers', 'correct_count', 'submitted_at')), before)
        self.assertEqual(self.client.post(url, {'week': 17, 'class_label': 'Invalid'}).status_code, 200)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.post(url, {'week': 4}).status_code, 404)
        self.client.force_login(self.ben)
        self.assertEqual(self.client.get(url).status_code, 403)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.teacher)
        self.assertEqual(client.post(url, {'week': 4}).status_code, 403)

    def test_new_tests_infer_week_or_use_chosen_teaching_week(self):
        one = next(q for q in questions().values() if q['week'] == 1)
        two = next(q for q in questions().values() if q['week'] == 2)
        for title, selected, week, expected in [
            ('Inferred', [one['id']], '', 1),
            ('Mixed', [one['id'], two['id']], '', None),
            ('Chosen', [one['id']], '5', 5),
        ]:
            response = self.client.post(reverse('add_test'), {'course': self.stats.pk, 'title': title, 'question_ids': selected, 'week': week, 'class_label': 'Class 3'})
            self.assertEqual(response.status_code, 302)
            assignment = TestAssignment.objects.get(title=title)
            self.assertEqual(assignment.week, expected)
            self.assertEqual(assignment.class_label, 'Class 3')

    def test_result_summaries_include_zero_exclude_drafts_and_unenrolled_scores(self):
        page = self.client.get(reverse('test_roster', args=[self.past.pk]))
        self.assertEqual((page.context['completed'], page.context['enrolled']), (2, 3))
        self.assertEqual(page.context['average_score'], 2)
        self.assertEqual(page.context['average_percentage'], 50)
        self.assertContains(page, '50.0%')
        self.assertContains(page, 'Average score')
        self.assertNotContains(page, 'Points available')
        self.assertNotContains(page, 'Most difficult')
        filtered = self.client.get(reverse('test_roster', args=[self.past.pk]), {'status': 'in_progress'})
        self.assertEqual(len(filtered.context['roster']), 1)
        self.assertEqual(filtered.context['average_percentage'], 50)
        Enrollment.objects.filter(student=self.alice, course=self.stats).delete()
        page = self.client.get(reverse('test_roster', args=[self.past.pk]))
        self.assertEqual((page.context['completed'], page.context['enrolled']), (1, 2))
        self.assertEqual(page.context['average_percentage'], 0)
        self.assertContains(page, '0.0%')

    def test_result_pagination_retains_whole_class_metrics_and_empty_average(self):
        empty = TestAssignment.objects.create(course=self.project, title='Unsubmitted test', question_snapshot=self.past.question_snapshot)
        page = self.client.get(reverse('test_roster', args=[empty.pk]))
        self.assertIsNone(page.context['average_score'])
        self.assertIsNone(page.context['average_percentage'])
        self.assertContains(page, 'No completed scores yet')
        self.assertNotContains(page, '0.0%')
        for index in range(27):
            student = User.objects.create_user(f'roster-{index:02}', first_name=f'Roster {index:02}')
            Enrollment.objects.create(student=student, course=self.stats)
        url = reverse('test_roster', args=[self.past.pk])
        first = self.client.get(url, {'status': 'not_started'})
        second = self.client.get(url, {'status': 'not_started', 'page': 2})
        self.assertEqual(len(first.context['roster']), 25)
        self.assertEqual(len(second.context['roster']), 2)
        for page in [first, second]:
            self.assertEqual((page.context['completed'], page.context['enrolled']), (2, 30))
            self.assertEqual(page.context['average_percentage'], 50)
        self.assertContains(first, 'status=not_started&amp;page=2')

    def test_overview_counts_ignore_other_teachers_and_old_enrolments(self):
        overview = self.client.get('/')
        self.assertEqual((overview.context['pending'], overview.context['completed']), (3, 4))
        self.assertEqual(overview.context['student_count'], 5)
        self.client.force_login(self.ben)
        overview = self.client.get('/')
        self.assertEqual((overview.context['outstanding'], overview.context['completed']), (2, 0))
