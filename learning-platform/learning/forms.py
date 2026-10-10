from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Assignment, Course, Submission, TestAssignment
from .scoring import questions, number


class StudentMetadataFields:
    @staticmethod
    def fields():
        return {
            'major': forms.CharField(max_length=120, required=False, label='Major', widget=forms.TextInput(attrs={'list': 'major-options', 'placeholder': 'For example, Accounting'})),
            'teaching_group': forms.CharField(max_length=80, required=False, label='Teaching group', widget=forms.TextInput(attrs={'list': 'group-options', 'placeholder': 'For example, Year 2 · Group A'})),
        }


class StudentForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, label='Student name')
    email = forms.EmailField(required=False, label='Email address')
    major = StudentMetadataFields.fields()['major']
    teaching_group = StudentMetadataFields.fields()['teaching_group']
    courses = forms.ModelMultipleChoiceField(queryset=Course.objects.none(), widget=forms.CheckboxSelectMultiple, required=False, label='Enrolled courses')

    class Meta:
        model = User
        fields = ['username', 'first_name', 'email', 'major', 'teaching_group', 'password1', 'password2', 'courses']

    def __init__(self, teacher, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['courses'].queryset = Course.objects.filter(teacher=teacher)
        self.fields['courses'].help_text = 'Select the courses this student is taking for homework tests and saved practice. Course information is public.'


class StudentAccessForm(forms.Form):
    courses = forms.ModelMultipleChoiceField(queryset=Course.objects.none(), widget=forms.CheckboxSelectMultiple, required=False, label='Enrolled courses')

    def __init__(self, teacher, *args, course_options=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['courses'].queryset = Course.objects.filter(teacher=teacher).order_by('title')
        if course_options is not None:
            self.fields['courses'].choices = [(c.pk, c.title) for c in course_options]


class StudentDetailsForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, label='Student name')
    email = forms.EmailField(required=False, label='Email address')
    major = StudentMetadataFields.fields()['major']
    teaching_group = StudentMetadataFields.fields()['teaching_group']

    class Meta:
        model = User
        fields = ['first_name', 'email', 'major', 'teaching_group']


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ['course', 'title', 'instructions', 'due_at']
        widgets = {'instructions': forms.Textarea(attrs={'rows': 6}), 'due_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')}

    def __init__(self, teacher, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course'].queryset = Course.objects.filter(teacher=teacher)
        self.fields['due_at'].help_text = 'Optional. China time (UTC+8). Late submissions remain accepted and are labelled.'


class SubmissionForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = ['answer']
        widgets = {'answer': forms.Textarea(attrs={'rows': 10})}


class FeedbackForm(forms.ModelForm):
    score = forms.IntegerField(min_value=0, max_value=100, required=False, label='Score out of 100 (optional)')

    class Meta:
        model = Submission
        fields = ['feedback', 'score']
        widgets = {'feedback': forms.Textarea(attrs={'rows': 5})}


class TestAssignmentForm(forms.ModelForm):
    question_ids = forms.MultipleChoiceField(label='Questions', widget=forms.CheckboxSelectMultiple)
    week = forms.TypedChoiceField(choices=[('', 'Choose a week (optional)')] + [(n, f'Week {n}') for n in range(1, 17)], coerce=int, empty_value=None, required=False)

    class Meta:
        model = TestAssignment
        fields = ['course', 'week', 'class_label', 'title', 'instructions', 'due_at']
        widgets = {'instructions': forms.Textarea(attrs={'rows': 3}), 'due_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')}

    def __init__(self, teacher, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course'].queryset = Course.objects.filter(teacher=teacher, slug='statistics')
        self.fields['course'].help_text = 'Assigned to every student enrolled in this course, including students added later.'
        self.fields['week'].help_text = 'Groups tests by teaching week. If left blank, a single week is inferred from the selected questions.'
        self.fields['class_label'].label = 'Class / session (optional)'
        self.fields['class_label'].help_text = 'For example, Class A or Class 3. Use the same label to keep tests together.'
        self.fields['class_label'].widget.attrs.update({'list': 'class-options', 'placeholder': 'For example, Class A'})
        self.fields['due_at'].help_text = 'Optional. China time (UTC+8). Late completions are accepted and labelled.'
        self.fields['question_ids'].choices = [(q['id'], q['title']) for q in questions().values()]

    def clean_question_ids(self):
        ids = list(dict.fromkeys(self.cleaned_data['question_ids']))
        if len(ids) > 50:
            raise forms.ValidationError('Choose up to 50 questions per test.')
        return ids

    def save(self, commit=True):
        assignment = super().save(commit=False)
        assignment.question_snapshot = [questions()[ident] for ident in self.cleaned_data['question_ids']]
        weeks = {q.get('week') for q in assignment.question_snapshot}
        if assignment.week is None and len(weeks) == 1:
            assignment.week = next(iter(weeks))
        if commit:
            assignment.save()
        return assignment


class TestOrganisationForm(forms.ModelForm):
    week = forms.TypedChoiceField(choices=[('', 'No week specified')] + [(n, f'Week {n}') for n in range(1, 17)], coerce=int, empty_value=None, required=False)

    class Meta:
        model = TestAssignment
        fields = ['week', 'class_label']
        labels = {'class_label': 'Class / session (optional)'}
        widgets = {'class_label': forms.TextInput(attrs={'list': 'class-options', 'placeholder': 'For example, Class A'})}


class TestAnswersForm(forms.Form):
    """Only trusted snapshot fields become form inputs; the browser supplies no grades."""
    def __init__(self, snapshot, *args, answers=None, submitting=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.snapshot, self.submitting, self.mapping = snapshot, submitting, []
        answers = answers or {}
        for qi, question in enumerate(snapshot):
            fields = []
            for fi, field in enumerate(question['fields']):
                name = f'q{qi}_f{fi}'
                options = {'label': field.get('label', 'Answer'), 'required': submitting, 'initial': answers.get(question['id'], {}).get(field['id'], '')}
                if field['kind'] == 'choice':
                    self.fields[name] = forms.ChoiceField(choices=[('', 'Choose an answer')] + [(o['value'], o['label']) for o in field['options']], **options)
                else:
                    self.fields[name] = forms.CharField(max_length=200, **options)
                    self.fields[name].help_text = 'Enter a number' + (f" rounded to {field.get('decimals', 0)} decimal places." if not field.get('exact') else '.')
                fields.append((name, field))
            self.mapping.append((question, fields))

    def clean(self):
        cleaned = super().clean()
        if self.submitting:
            for _, fields in self.mapping:
                for name, field in fields:
                    if name in cleaned and field['kind'] == 'number' and number(cleaned[name], field.get('allowPercent', False)) is None:
                        self.add_error(name, 'Enter a valid number or fraction.')
        return cleaned

    def answer_data(self):
        return {q['id']: {field['id']: self.cleaned_data[name] for name, field in fields} for q, fields in self.mapping}

    def question_rows(self):
        # Do not pass answer keys, hints or solutions into the student template.
        return [{'number': i + 1, 'title': q['title'], 'prompt': q['promptHtml'], 'fields': [self[name] for name, _ in fields]} for i, (q, fields) in enumerate(self.mapping)]
