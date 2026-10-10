"""Directory and list summaries without loading every roster or question snapshot."""
from django.db.models import Count, Exists, F, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from .models import Enrollment, StudentRegistration, TestAssignment, TestAttempt
from .students import teacher_students


def count_subquery(queryset, group):
    return Coalesce(Subquery(queryset.order_by().values(group).annotate(total=Count('pk')).values('total')[:1], output_field=IntegerField()), Value(0))


def teacher_tests(teacher):
    enrolled = Enrollment.objects.filter(course_id=OuterRef('course_id'), student__is_staff=False)
    completed = TestAttempt.objects.filter(assignment_id=OuterRef('pk'), submitted_at__isnull=False, student__is_staff=False, student__enrollment__course_id=OuterRef('course_id'))
    return TestAssignment.objects.filter(course__teacher=teacher).select_related('course').defer('question_snapshot').annotate(
        enrolled_total=count_subquery(enrolled, 'course_id'),
        completed_total=count_subquery(completed, 'assignment_id'),
    )


def student_tests(student):
    from .content_access import hidden_test_ids
    attempts = TestAttempt.objects.filter(assignment_id=OuterRef('pk'), student=student)
    return TestAssignment.objects.filter(course__enrollment__student=student).exclude(pk__in=hidden_test_ids(student)).select_related('course').defer('question_snapshot').annotate(
        has_attempt=Exists(attempts),
        is_completed=Exists(attempts.filter(submitted_at__isnull=False)),
    )


def directory_students(teacher, course=None):
    registration = StudentRegistration.objects.filter(student_id=OuterRef('pk'), teacher=teacher)
    enrolled = Enrollment.objects.filter(student_id=OuterRef('pk'), course__teacher=teacher)
    assigned = TestAssignment.objects.filter(course__teacher=teacher, course__enrollment__student_id=OuterRef('pk'))
    completed = TestAttempt.objects.filter(student_id=OuterRef('pk'), assignment__course__teacher=teacher, submitted_at__isnull=False, student__enrollment__course_id=F('assignment__course_id'))
    if course is not None:
        assigned = assigned.filter(course=course)
        completed = completed.filter(assignment__course=course)
    # The inner Exists refers to the assignment and to the student two query levels above.
    overdue = assigned.filter(due_at__lt=timezone.now()).annotate(
        completed_by_student=Exists(TestAttempt.objects.filter(assignment_id=OuterRef('pk'), student_id=OuterRef(OuterRef('pk')), submitted_at__isnull=False))
    ).filter(completed_by_student=False)
    return teacher_students(teacher).annotate(
        major=Coalesce(Subquery(registration.values('major')[:1]), Value('')),
        teaching_group=Coalesce(Subquery(registration.values('teaching_group')[:1]), Value('')),
        has_courses=Exists(enrolled),
        assigned_count=count_subquery(assigned, 'course__enrollment__student_id'),
        completed_count=count_subquery(completed, 'student_id'),
        overdue_count=count_subquery(overdue, 'course__enrollment__student_id'),
    )
