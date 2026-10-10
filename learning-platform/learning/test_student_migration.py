from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class StudentRegistrationMigrationTests(TransactionTestCase):
    def test_existing_student_relationships_survive_upgrade(self):
        previous = [('learning', '0002_testassignment_testattempt')]
        current = [('learning', '0004_studentregistration_major_and_more')]
        executor = MigrationExecutor(connection)
        executor.migrate(previous)
        old = executor.loader.project_state(previous).apps
        try:
            User = old.get_model('auth', 'User')
            Course = old.get_model('learning', 'Course')
            Enrollment = old.get_model('learning', 'Enrollment')
            TestAssignment = old.get_model('learning', 'TestAssignment')
            TestAttempt = old.get_model('learning', 'TestAttempt')
            teacher = User.objects.create(username='legacy-teacher', is_staff=True)
            student = User.objects.create(username='legacy-student')
            for slug in ['statistics', 'corporate-finance']:
                course = Course.objects.create(slug=slug, title=slug, teacher_id=teacher.pk)
                Enrollment.objects.create(student_id=student.pk, course_id=course.pk)
            test = TestAssignment.objects.create(course_id=course.pk, title='Existing test', question_snapshot=[{'week': 2}, {'week': 2}])
            mixed = TestAssignment.objects.create(course_id=course.pk, title='Mixed weeks', question_snapshot=[{'week': 1}, {'week': 2}])
            attempt = TestAttempt.objects.create(assignment_id=test.pk, student_id=student.pk, submitted_at=timezone.now(), correct_count=1, answers={'saved': 'answer'})
            executor = MigrationExecutor(connection)
            executor.migrate(current)
            latest = executor.loader.project_state(current).apps
            registrations = latest.get_model('learning', 'StudentRegistration').objects.filter(student_id=student.pk, teacher_id=teacher.pk)
            self.assertEqual(registrations.count(), 1)
            self.assertEqual(registrations.get().major, '')
            self.assertEqual(latest.get_model('learning', 'TestAssignment').objects.get(pk=test.pk).week, 2)
            self.assertIsNone(latest.get_model('learning', 'TestAssignment').objects.get(pk=mixed.pk).week)
            saved = latest.get_model('learning', 'TestAttempt').objects.get(pk=attempt.pk)
            self.assertEqual(saved.correct_count, 1)
            self.assertEqual(saved.answers, {'saved': 'answer'})
            latest.get_model('learning', 'Enrollment').objects.filter(student_id=student.pk).delete()
            self.assertEqual(registrations.count(), 1)
        finally:
            MigrationExecutor(connection).migrate(current)
