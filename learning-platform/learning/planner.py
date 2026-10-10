import calendar
from datetime import datetime, time, timedelta
from django import forms
from django.db.models import F
from django.utils import timezone
from .models import Course
from .reporting import student_tests, teacher_tests


class PlannerFilters(forms.Form):
    course = forms.ModelChoiceField(queryset=Course.objects.none(), required=False, empty_label='All courses')
    status = forms.ChoiceField(required=False, choices=[('', 'All outstanding tasks'), ('overdue', 'Overdue'), ('in_progress', 'In progress'), ('not_started', 'Not started')])

    def __init__(self, student, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course'].queryset = (Course.objects.filter(teacher=student) if student.is_staff else Course.objects.filter(enrollment__student=student)).order_by('title')


def task_rows(tests):
    now = timezone.now()
    return [{'assignment': a, 'status': 'Completed' if a.is_completed else 'In progress' if a.has_attempt else 'Not started',
             'overdue': bool(not a.is_completed and a.due_at and a.due_at < now),
             'action': 'View result' if a.is_completed else 'Resume' if a.has_attempt else 'Start'} for a in tests]


def pending_tasks(student, course=None, state=''):
    tests = student_tests(student).filter(is_completed=False)
    if course:
        tests = tests.filter(course=course)
    if state == 'overdue':
        tests = tests.filter(due_at__lt=timezone.now())
    elif state == 'in_progress':
        tests = tests.filter(has_attempt=True)
    elif state == 'not_started':
        tests = tests.filter(has_attempt=False)
    return tests.order_by(F('due_at').asc(nulls_last=True), 'created_at', 'pk')


def calendar_month(student, selected, course=None):
    # Keep navigation bounded and month parsing independent of server timezone.
    try:
        month = datetime.strptime(selected, '%Y-%m').date().replace(day=1)
        if not 2000 <= month.year <= 2100 or month.strftime('%Y-%m') != selected:
            raise ValueError
    except (ValueError, TypeError):
        raise forms.ValidationError('Choose a month between January 2000 and December 2100.')
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    previous = (month - timedelta(days=1)).replace(day=1)
    start = timezone.make_aware(datetime.combine(month, time.min))
    end = timezone.make_aware(datetime.combine(next_month, time.min))
    tests = (teacher_tests(student) if student.is_staff else student_tests(student)).filter(due_at__gte=start, due_at__lt=end).order_by('due_at', 'pk')
    if course:
        tests = tests.filter(course=course)
    events = {}
    rows = [{'assignment': a, 'status': f'{a.completed_total} / {a.enrolled_total} completed', 'overdue': False} for a in tests] if student.is_staff else task_rows(tests)
    for row in rows:
        day = timezone.localtime(row['assignment'].due_at).date()
        events.setdefault(day, []).append(row)
    today = timezone.localdate()
    weeks = [[{'date': day, 'in_month': day.month == month.month, 'today': day == today, 'events': events.get(day, [])} for day in week] for week in calendar.Calendar(firstweekday=0).monthdatescalendar(month.year, month.month)]
    return {'month': selected, 'month_title': month.strftime('%B %Y'), 'weeks': weeks,
            'previous_month': previous.strftime('%Y-%m') if previous.year >= 2000 else None,
            'next_month': next_month.strftime('%Y-%m') if next_month.year <= 2100 else None,
            'event_count': sum(len(rows) for rows in events.values())}
