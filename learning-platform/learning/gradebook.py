"""Course-scoped grade matrix; question bodies stay in the database."""
from django import forms
from django.core.paginator import Paginator
from django.db.models import Avg, Count, ExpressionWrapper, F, FloatField, Func, IntegerField
from django.db.models.functions import NullIf
from .filters import MISSING, metadata_options
from .models import Course, TestAssignment, TestAttempt
from .reporting import directory_students


class QuestionCount(Func):
    function = 'json_array_length'
    output_field = IntegerField()

    def as_postgresql(self, compiler, connection, **extra):
        return self.as_sql(compiler, connection, function='jsonb_array_length', **extra)

    def as_mysql(self, compiler, connection, **extra):
        return self.as_sql(compiler, connection, function='JSON_LENGTH', **extra)


class GradebookFilters(forms.Form):
    course = forms.ModelChoiceField(queryset=Course.objects.none(), empty_label=None)
    major = forms.ChoiceField(required=False)
    teaching_group = forms.ChoiceField(required=False, label='Teaching group')
    week = forms.ChoiceField(required=False, choices=[('', 'All weeks'), (MISSING, 'Week not set')] + [(str(n), f'Week {n}') for n in range(1, 17)])

    def __init__(self, teacher, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course'].queryset = Course.objects.filter(teacher=teacher).order_by('title')
        options = metadata_options(teacher)
        self.fields['major'].choices = [('', 'All majors'), (MISSING, 'Major not set')] + [(v, v) for v in options['major_options']]
        self.fields['teaching_group'].choices = [('', 'All groups'), (MISSING, 'Group not set')] + [(v, v) for v in options['group_options']]


def gradebook_data(teacher, params, student_limit=25, test_limit=12):
    data = params.copy()
    if 'course' not in data:
        first = Course.objects.filter(teacher=teacher).order_by('title').values_list('pk', flat=True).first()
        data['course'] = str(first or '')
    form = GradebookFilters(teacher, data)
    students, tests, course = directory_students(teacher).none(), TestAssignment.objects.none(), None
    if form.is_valid():
        values = form.cleaned_data
        course = values['course']
        students = directory_students(teacher, course).filter(enrollment__course=course)
        for key in ('major', 'teaching_group'):
            if values[key]:
                students = students.filter(**{key: '' if values[key] == MISSING else values[key]})
        tests = TestAssignment.objects.filter(course=course)
        if values['week']:
            tests = tests.filter(week__isnull=True) if values['week'] == MISSING else tests.filter(week=int(values['week']))
    tests = tests.annotate(points=QuestionCount('question_snapshot')).defer('question_snapshot').order_by(F('week').asc(nulls_last=True), 'class_label', 'created_at', 'pk')
    test_page = Paginator(tests, test_limit).get_page(params.get('test_page'))
    page = Paginator(students, student_limit).get_page(params.get('page'))
    shown_students, shown_tests = list(page.object_list), list(test_page.object_list)
    attempts = TestAttempt.objects.filter(student__in=shown_students, assignment__in=tests)
    percentage = ExpressionWrapper(100.0 * F('correct_count') / NullIf(QuestionCount('assignment__question_snapshot'), 0), output_field=FloatField())
    summaries = {r['student_id']: r for r in attempts.filter(submitted_at__isnull=False).values('student_id').annotate(completed=Count('pk'), average=Avg(percentage))}
    cells = {(a.student_id, a.assignment_id): a for a in attempts.filter(assignment__in=shown_tests).only('student_id', 'assignment_id', 'submitted_at', 'correct_count')}
    rows = []
    for student in shown_students:
        summary = summaries.get(student.pk, {})
        row_cells = []
        for assignment in shown_tests:
            attempt = cells.get((student.pk, assignment.pk))
            completed = bool(attempt and attempt.submitted_at)
            row_cells.append({'assignment': assignment, 'attempt': attempt, 'completed': completed,
                              'percentage': 100 * attempt.correct_count / assignment.points if completed and attempt.correct_count is not None and assignment.points else None,
                              'status': 'Completed' if completed else 'In progress' if attempt else 'Not started'})
        rows.append({'student': student, 'cells': row_cells, 'completed': summary.get('completed', 0), 'average': summary.get('average')})
    student_query, test_query = data.copy(), data.copy()
    student_query.pop('page', None)
    test_query.pop('test_page', None)
    return {'filter_form': form, 'course': course, 'rows': rows, 'tests': shown_tests, 'test_page': test_page,
            'test_count': test_page.paginator.count, 'page': page, 'page_query': student_query.urlencode(), 'test_query': test_query.urlencode()}
