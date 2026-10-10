from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from .models import Enrollment, StudentRegistration


def teacher_students(teacher):
    # Existing enrolments are included for compatibility with historical imports.
    return User.objects.filter(
        Q(teacher_registrations__teacher=teacher) | Q(enrollment__course__teacher=teacher),
        is_staff=False,
    ).distinct().order_by('first_name', 'username')


@transaction.atomic
def set_course_access(teacher, student, courses):
    selected = {course.pk for course in courses}
    # Remember the association before removing the final enrolment.
    StudentRegistration.objects.get_or_create(teacher=teacher, student=student)
    Enrollment.objects.filter(student=student, course__teacher=teacher).exclude(course_id__in=selected).delete()
    Enrollment.objects.bulk_create(
        [Enrollment(student=student, course_id=pk) for pk in selected],
        ignore_conflicts=True,
    )
