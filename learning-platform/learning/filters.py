from django import forms
from .models import Course, StudentRegistration, TestAssignment


MISSING = '__missing__'


def metadata_options(teacher):
    registrations = StudentRegistration.objects.filter(teacher=teacher, student__is_staff=False)
    return {
        'major_options': list(registrations.exclude(major='').order_by('major').values_list('major', flat=True).distinct()),
        'group_options': list(registrations.exclude(teaching_group='').order_by('teaching_group').values_list('teaching_group', flat=True).distinct()),
    }


class StudentDirectoryFilters(forms.Form):
    major = forms.ChoiceField(required=False)
    teaching_group = forms.ChoiceField(required=False, label='Teaching group')
    course = forms.ModelChoiceField(queryset=Course.objects.none(), required=False, empty_label='All courses')
    status = forms.ChoiceField(required=False, label='Coursework status', choices=[('', 'All students'), ('overdue', 'Has overdue tests'), ('outstanding', 'Has tests to complete'), ('completed', 'All assigned tests completed'), ('no_tests', 'No tests assigned'), ('no_courses', 'No courses assigned')])

    def __init__(self, teacher, *args, **kwargs):
        super().__init__(*args, **kwargs)
        options = metadata_options(teacher)
        self.fields['major'].choices = [('', 'All majors'), (MISSING, 'Major not set')] + [(name, name) for name in options['major_options']]
        self.fields['teaching_group'].choices = [('', 'All groups'), (MISSING, 'Group not set')] + [(name, name) for name in options['group_options']]
        self.fields['course'].queryset = Course.objects.filter(teacher=teacher).order_by('title')


class TestListFilters(forms.Form):
    course = forms.ModelChoiceField(queryset=Course.objects.none(), required=False, empty_label='All courses')
    week = forms.ChoiceField(required=False, choices=[('', 'All weeks'), (MISSING, 'Week not set')] + [(str(n), f'Week {n}') for n in range(1, 17)])
    class_label = forms.ChoiceField(required=False, label='Class / session')
    status = forms.ChoiceField(required=False)
    sort = forms.ChoiceField(required=False, label='Order', choices=[('', 'Course, week & class'), ('newest', 'Newest first'), ('due', 'Due date first')])

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        courses = Course.objects.filter(teacher=user) if user.is_staff else Course.objects.filter(enrollment__student=user)
        self.fields['course'].queryset = courses.order_by('title')
        tests = TestAssignment.objects.filter(course__in=courses)
        selected = self.data.get('course', '')
        if selected.isdigit():
            tests = tests.filter(course_id=int(selected))
        labels = tests.exclude(class_label='').order_by('class_label').values_list('class_label', flat=True).distinct()
        self.fields['class_label'].choices = [('', 'All classes'), (MISSING, 'Class not set')] + [(name, name) for name in labels]
        self.fields['status'].choices = [('', 'All tests'), ('outstanding', 'Still to complete'), ('completed', 'Completed'), ('overdue', 'Overdue')]
        if not user.is_staff:
            self.fields['status'].choices += [('not_started', 'Not started'), ('in_progress', 'In progress')]
