import hashlib
import json
import re
import uuid
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Sum
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .forms import AssignmentForm, FeedbackForm, StudentForm, StudentAccessForm, StudentDetailsForm, SubmissionForm, TestAssignmentForm, TestAnswersForm, TestOrganisationForm
from .models import Assignment, Course, Enrollment, LoginThrottle, PracticeResult, StudentRegistration, Submission, TestAssignment, TestAttempt
from .filters import MISSING, StudentDirectoryFilters, TestListFilters, metadata_options
from .reporting import directory_students, teacher_tests, student_tests
from .scoring import bank, questions, score
from .students import teacher_students, set_course_access
from .planner import pending_tasks, task_rows
from .objectives import objective_evidence


class PlatformLoginView(LoginView):
    template_name = 'login.html'
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session.set_expiry(60 * 60 * 24 * 14 if self.request.POST.get('remember') == 'on' else 0)
        return response

    def post(self, request, *args, **kwargs):
        # Per-IP bucket limits password guessing across usernames on this local prototype.
        key = hashlib.sha256(request.META.get('REMOTE_ADDR', '').encode()).hexdigest()
        row, _ = LoginThrottle.objects.get_or_create(key=key, defaults={'window_start': timezone.now()})
        if row.window_start < timezone.now() - timedelta(minutes=15):
            row.failures = 0
            row.window_start = timezone.now()
        if row.failures >= 10:
            return render(request, self.template_name, {'form': self.get_form(), 'throttled': True}, status=429)
        response = super().post(request, *args, **kwargs)
        row.failures = 0 if request.user.is_authenticated else row.failures + 1
        row.save()
        return response


def teacher_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden('Teacher access required.')
        return view(request, *args, **kwargs)
    return wrapped


def my_courses(user):
    if user.is_superuser:
        return Course.objects.all()
    return Course.objects.filter(teacher=user) if user.is_staff else Course.objects.filter(enrollment__student=user)


def progress_rows(results):
    rows = {}
    labels = {o['id']: o['label'] for o in bank()['objectives']}
    for result in results:
        for ident in result.objective_ids:
            row = rows.setdefault(ident, {'id': ident, 'label': labels.get(ident, ident), 'attempted': 0, 'independent': 0, 'assisted': 0})
            row['attempted'] += 1
            row['independent'] += int(result.first_correct and not result.first_assisted)
            row['assisted'] += int(result.first_correct and result.first_assisted)
    return sorted(rows.values(), key=lambda r: r['id'])


@login_required
def dashboard(request):
    courses = my_courses(request.user).select_related('teacher').annotate(member_count=Count('enrollment')).order_by('title')
    if request.user.is_staff:
        from .gradebook import gradebook_data
        totals = teacher_tests(request.user).aggregate(enrolled=Sum('enrolled_total'), completed=Sum('completed_total'))
        completed = totals['completed'] or 0
        grade_params = request.GET.copy()
        grade_params.pop('page', None)
        grade_params.pop('test_page', None)
        if 'course' not in grade_params:
            preferred = courses.filter(slug='statistics').first() or courses.first()
            if preferred:
                grade_params['course'] = str(preferred.pk)
        deadlines = teacher_tests(request.user).filter(due_at__gte=timezone.now()).order_by('due_at')[:5]
        return render(request, 'teacher_overview.html', {'student_count': teacher_students(request.user).count(), 'pending': (totals['enrolled'] or 0) - completed, 'completed': completed, 'courses': courses, 'grade_preview': gradebook_data(request.user, grade_params, student_limit=4, test_limit=3), 'deadlines': deadlines})
    work = student_tests(request.user)
    completed = work.filter(is_completed=True).count()
    from .planner import calendar_month
    from .models import LessonPractice
    from .curriculum import get_lesson
    _, recommendations = objective_evidence(request.user, courses)
    recent_lesson = LessonPractice.objects.filter(student=request.user, course__in=courses, answers__isnull=False).exclude(answers={}).select_related('course').order_by('-updated_at').first()
    continuing = get_lesson(recent_lesson.course.slug, recent_lesson.lesson_key) if recent_lesson else None
    recent_results = TestAttempt.objects.filter(student=request.user, assignment__course__in=courses, submitted_at__isnull=False).select_related('assignment__course').order_by('-submitted_at')[:4]
    return render(request, 'student_overview.html', {'completed': completed, 'outstanding': work.count() - completed, 'attempts': PracticeResult.objects.filter(student=request.user, course__in=courses).count(), 'upcoming': task_rows(pending_tasks(request.user)[:5]), 'overdue': work.filter(is_completed=False, due_at__lt=timezone.now()).count(), 'courses': courses, 'recommendation': recommendations[0] if recommendations else None, 'continuing': continuing, 'recent_lesson': recent_lesson, 'recent_results': recent_results, 'mini_calendar': calendar_month(request.user, timezone.localdate().strftime('%Y-%m'))})


def teacher_test_rows(teacher):
    return [{'assignment': a, 'total': a.enrolled_total, 'completed': a.completed_total} for a in teacher_tests(teacher)]


def student_test_rows(student, assignments=None):
    assignments = list(student_tests(student) if assignments is None else assignments)
    attempts = {a.assignment_id: a for a in TestAttempt.objects.filter(student=student, assignment__in=assignments).select_related('assignment')}
    return [test_status(a, student, attempts.get(a.pk)) for a in assignments]


@login_required
def assigned_tests(request):
    form = TestListFilters(request.user, request.GET)
    tests = teacher_tests(request.user) if request.user.is_staff else student_tests(request.user)
    if form.is_valid():
        values = form.cleaned_data
        if values['course']:
            tests = tests.filter(course=values['course'])
        if values['week']:
            tests = tests.filter(week__isnull=True) if values['week'] == MISSING else tests.filter(week=int(values['week']))
        if values['class_label']:
            tests = tests.filter(class_label='' if values['class_label'] == MISSING else values['class_label'])
        state = values['status']
        if request.user.is_staff:
            if state == 'completed':
                tests = tests.filter(enrolled_total__gt=0, completed_total=F('enrolled_total'))
            elif state in {'outstanding', 'overdue'}:
                tests = tests.filter(completed_total__lt=F('enrolled_total'))
        else:
            if state == 'completed':
                tests = tests.filter(is_completed=True)
            elif state in {'outstanding', 'overdue', 'not_started', 'in_progress'}:
                tests = tests.filter(is_completed=False)
                if state == 'not_started':
                    tests = tests.filter(has_attempt=False)
                elif state == 'in_progress':
                    tests = tests.filter(has_attempt=True)
        if state == 'overdue':
            tests = tests.filter(due_at__lt=timezone.now())
        order = values['sort']
    else:
        tests, order = tests.none(), ''
    if order == 'newest':
        tests = tests.order_by('-created_at', '-pk')
    elif order == 'due':
        tests = tests.order_by(F('due_at').asc(nulls_last=True), '-pk')
    else:
        tests = tests.order_by('course__title', F('week').asc(nulls_last=True), 'class_label', '-created_at', '-pk')
    page = Paginator(tests, 20).get_page(request.GET.get('page'))
    rows = [{'assignment': a, 'total': a.enrolled_total, 'completed': a.completed_total} for a in page.object_list] if request.user.is_staff else student_test_rows(request.user, page.object_list)
    groups = {}
    for row in rows:
        assignment = row['assignment']
        course = groups.setdefault(assignment.course_id, {'course': assignment.course, 'classes': {}})
        key = (assignment.week, assignment.class_label)
        label = ' · '.join(filter(None, [f'Week {assignment.week}' if assignment.week else '', assignment.class_label])) or 'General tests'
        group = course['classes'].setdefault(key, {'label': label, 'rows': []})
        group['rows'].append(row)
    course_groups = [{'course': g['course'], 'classes': list(g['classes'].values())} for g in groups.values()]
    return render(request, 'assigned_tests.html', {'filter_form': form, 'course_groups': course_groups, 'page': page, 'page_query': pagination_query(request), 'groups_open': sum(len(g['classes']) for g in course_groups) <= 3})


def pagination_query(request):
    query = request.GET.copy()
    query.pop('page', None)
    return query.urlencode()


def directory_url(request):
    from django.urls import reverse
    query = request.GET.urlencode()
    return reverse('student_directory') + ('?' + query if query else '')


@login_required
def student_courses(request):
    return render(request, 'my_courses.html', {'courses': my_courses(request.user).select_related('teacher').annotate(member_count=Count('enrollment')).order_by('title')})


@login_required
def learning_progress(request):
    if request.user.is_staff:
        return redirect('dashboard')
    courses = list(my_courses(request.user).order_by('title'))
    course_id = request.GET.get('course')
    selected = get_object_or_404(my_courses(request.user), pk=course_id) if course_id and course_id.isdigit() else None
    if course_id and not selected:
        raise Http404
    results = PracticeResult.objects.filter(student=request.user, course__in=[selected] if selected else courses)
    evidence, recommendations = objective_evidence(request.user, [selected] if selected else courses)
    summary = {'objectives': len(evidence), 'observed': sum(bool(r['evidence_count']) for r in evidence),
               'review': sum(r['needs_review'] for r in evidence)}
    state = request.GET.get('status', '')
    if state == 'review':
        evidence = [r for r in evidence if r['needs_review']]
    elif state == 'unattempted':
        evidence = [r for r in evidence if not r['evidence_count']]
    elif state == 'practised':
        evidence = [r for r in evidence if r['evidence_count']]
    elif state:
        raise Http404
    page = Paginator(evidence, 20).get_page(request.GET.get('page'))
    return render(request, 'learning_progress.html', {'progress': page.object_list, 'recommendations': recommendations, 'courses': courses, 'selected_course': selected, 'progress_status': state, 'attempts': results.count(), 'page': page, 'page_query': pagination_query(request), 'has_evidence': bool(summary['observed']), 'summary': summary})


def render_student_directory(request, bound_student=None, bound_form=None):
    form = StudentDirectoryFilters(request.user, request.GET)
    valid = form.is_valid()
    students = directory_students(request.user, form.cleaned_data['course'] if valid else None)
    if valid:
        values = form.cleaned_data
        for name in ('major', 'teaching_group'):
            if values[name]:
                students = students.filter(**{name: '' if values[name] == MISSING else values[name]})
        if values['course']:
            students = students.filter(enrollment__course=values['course'])
        state = values['status']
        if state == 'overdue':
            students = students.filter(overdue_count__gt=0)
        elif state == 'outstanding':
            students = students.filter(assigned_count__gt=F('completed_count'))
        elif state == 'completed':
            students = students.filter(assigned_count__gt=0, completed_count=F('assigned_count'))
        elif state == 'no_tests':
            students = students.filter(assigned_count=0)
        elif state == 'no_courses':
            students = students.filter(has_courses=False)
    else:
        students = students.none()
    page = Paginator(students, 25).get_page(request.GET.get('page'))
    students = list(page.object_list)
    enrolled = {student.pk: [] for student in students}
    for student_id, course_id in Enrollment.objects.filter(student__in=students, course__teacher=request.user).values_list('student_id', 'course_id'):
        enrolled[student_id].append(course_id)
    courses = list(Course.objects.filter(teacher=request.user).order_by('title'))
    rows = []
    for student in students:
        access = bound_form if student.pk == bound_student else StudentAccessForm(request.user, initial={'courses': enrolled[student.pk]}, auto_id=f'student-{student.pk}-%s', course_options=courses)
        rows.append({'student': student, 'assigned': student.assigned_count, 'completed': student.completed_count, 'overdue': student.overdue_count, 'form': access})
    return render(request, 'students.html', {'rows': rows, 'filter_form': form, 'page': page, 'registered_count': teacher_students(request.user).count(), 'page_query': pagination_query(request), 'directory_query': request.GET.urlencode()})


@teacher_required
def student_directory(request):
    return render_student_directory(request)


@teacher_required
@require_POST
def update_student_access(request, pk):
    student = get_object_or_404(teacher_students(request.user), pk=pk)
    form = StudentAccessForm(request.user, request.POST, auto_id=f'student-{pk}-%s')
    if form.is_valid():
        set_course_access(request.user, student, form.cleaned_data['courses'])
        messages.success(request, f'Courses updated for {student.first_name or student.username}.')
        return redirect(directory_url(request))
    return render_student_directory(request, bound_student=student.pk, bound_form=form)


@teacher_required
def edit_student(request, pk):
    student = get_object_or_404(teacher_students(request.user), pk=pk)
    registration = StudentRegistration.objects.filter(teacher=request.user, student=student).first()
    initial = {'major': registration.major, 'teaching_group': registration.teaching_group} if registration else {}
    form = StudentDetailsForm(request.POST if request.method == 'POST' else None, instance=student, initial=initial)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            StudentRegistration.objects.update_or_create(teacher=request.user, student=student, defaults={name: form.cleaned_data[name] for name in ('major', 'teaching_group')})
        messages.success(request, 'Student details updated.')
        return redirect(directory_url(request))
    return render(request, 'form.html', {'form': form, 'title': 'Edit student details', 'button': 'Save details', 'back_url': directory_url(request), 'back_label': 'Students', **metadata_options(request.user)})


def test_status(assignment, student, attempt=None):
    completed = bool(attempt and attempt.submitted_at)
    return {'assignment': assignment, 'student': student, 'attempt': attempt, 'status': 'Completed' if completed else ('In progress' if attempt else 'Not started'), 'overdue': bool(not completed and assignment.due_at and timezone.now() > assignment.due_at), 'late': bool(completed and assignment.due_at and attempt.submitted_at > assignment.due_at)}


def test_roster(assignment):
    students = User.objects.filter(enrollment__course=assignment.course, is_staff=False).order_by('first_name', 'username')
    attempts = {}
    for attempt in assignment.attempts.all():
        attempt.assignment = assignment
        attempts[attempt.student_id] = attempt
    return [test_status(assignment, s, attempts.get(s.pk)) for s in students]


@teacher_required
def add_test(request):
    form = TestAssignmentForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        assignment = form.save()
        messages.success(request, 'Test assigned to every student enrolled in this course.')
        return redirect('test_roster', pk=assignment.pk)
    selected = set(request.POST.getlist('question_ids'))
    catalogue = [{'id': q['id'], 'title': q['title'], 'week': q['week'], 'difficulty': q['difficulty'], 'topic': q['topic'], 'prompt': q['promptHtml'], 'selected': q['id'] in selected} for q in questions().values()]
    class_options = TestAssignment.objects.filter(course__teacher=request.user).exclude(class_label='').order_by('class_label').values_list('class_label', flat=True).distinct()
    return render(request, 'test_create.html', {'form': form, 'catalogue': catalogue, 'weeks': sorted({q['week'] for q in catalogue}), 'difficulties': sorted({q['difficulty'] for q in catalogue}), 'class_options': class_options})


@teacher_required
def assignment_roster(request, pk):
    assignment = get_object_or_404(TestAssignment.objects.select_related('course'), pk=pk, course__in=my_courses(request.user))
    roster = test_roster(assignment)
    submitted = [r['attempt'].correct_count for r in roster if r['attempt'] and r['attempt'].submitted_at and r['attempt'].correct_count is not None]
    average = sum(submitted) / len(submitted) if submitted else None
    points = len(assignment.question_snapshot)
    completed = sum(r['status'] == 'Completed' for r in roster)
    state = request.GET.get('status', '')
    filtered = [r for r in roster if not state or r['status'] == {'completed': 'Completed', 'in_progress': 'In progress', 'not_started': 'Not started'}.get(state)]
    page = Paginator(filtered, 25).get_page(request.GET.get('page'))
    return render(request, 'test_roster.html', {'assignment': assignment, 'roster': page.object_list, 'page': page, 'page_query': pagination_query(request), 'roster_status': state, 'enrolled': len(roster), 'completed': completed, 'completion_percentage': 100 * completed / len(roster) if roster else 0, 'average_score': average, 'average_percentage': 100 * average / points if average is not None and points else None, 'points': points})


@teacher_required
def organise_test(request, pk):
    assignment = get_object_or_404(TestAssignment, pk=pk, course__teacher=request.user)
    form = TestOrganisationForm(request.POST if request.method == 'POST' else None, instance=assignment)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Test grouping updated.')
        return redirect('assigned_tests')
    labels = TestAssignment.objects.filter(course__teacher=request.user).exclude(class_label='').order_by('class_label').values_list('class_label', flat=True).distinct()
    return render(request, 'form.html', {'form': form, 'title': f'Organise: {assignment.title}', 'button': 'Save grouping', 'back_url': '/assigned-tests/', 'back_label': 'Assigned tests', 'class_options': labels})


@login_required
def take_test(request, pk):
    assignment = get_object_or_404(TestAssignment.objects.select_related('course'), pk=pk, course__in=my_courses(request.user))
    from .content_access import test_is_visible
    if not test_is_visible(assignment, request.user):
        raise Http404
    teacher = request.user.is_staff
    attempt = TestAttempt.objects.filter(assignment=assignment, student=request.user).first()
    if teacher and request.method == 'POST':
        return HttpResponseForbidden('Teacher preview cannot submit a test.')
    if attempt and attempt.submitted_at:
        return render(request, 'test_result.html', {'assignment': assignment, 'attempt': attempt, 'state': test_status(assignment, request.user, attempt)})
    action = request.POST.get('action')
    if request.method == 'POST' and action == 'start':
        TestAttempt.objects.get_or_create(assignment=assignment, student=request.user)
        return redirect('take_test', pk=pk)
    if request.method == 'POST' and action not in {'save', 'submit'}:
        return HttpResponse('Unknown test action.', status=400)
    if request.method == 'POST' and not attempt:
        return HttpResponse('Start this test before answering.', status=400)
    form = TestAnswersForm(assignment.question_snapshot, request.POST if request.method == 'POST' else None, answers=attempt.answers if attempt else {}, submitting=action == 'submit')
    if request.method == 'POST' and form.is_valid():
        answers = form.answer_data()
        updates = {'answers': answers, 'saved_at': timezone.now()}
        if action == 'submit':
            results = {q['id']: score(q, answers[q['id']])[1] for q in assignment.question_snapshot}
            updates.update(submitted_at=timezone.now(), correct_count=sum(results.values()), results=results)
        # A second tab/request cannot overwrite a test once it has been submitted.
        saved = TestAttempt.objects.filter(pk=attempt.pk, submitted_at__isnull=True).update(**updates)
        messages.success(request, ('Test completed. Your teacher can see your result.' if action == 'submit' else 'Progress saved. You can return to this test from your dashboard.') if saved else 'This test has already been submitted.')
        return redirect('take_test', pk=pk)
    return render(request, 'test_take.html', {'assignment': assignment, 'attempt': attempt, 'teacher_preview': teacher, 'form': form, 'question_rows': form.question_rows(), 'state': test_status(assignment, request.user, attempt)})


@teacher_required
def add_student(request):
    form = StudentForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            student = form.save()
            set_course_access(request.user, student, form.cleaned_data['courses'])
            StudentRegistration.objects.filter(teacher=request.user, student=student).update(**{name: form.cleaned_data[name] for name in ('major', 'teaching_group')})
        messages.success(request, f'Account created for {student.first_name}. Give the student their username and password privately.')
        return redirect('student_directory')
    return render(request, 'form.html', {'form': form, 'title': 'Add a student', 'button': 'Create account', 'back_url': '/teacher/students/', 'back_label': 'Students', **metadata_options(request.user)})


@teacher_required
def add_assignment(request):
    form = AssignmentForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Homework published to enrolled students.')
        return redirect('dashboard')
    return render(request, 'form.html', {'form': form, 'title': 'Create homework', 'button': 'Publish homework'})


@login_required
def assignment(request, pk):
    work = get_object_or_404(Assignment, pk=pk, course__in=my_courses(request.user))
    submission = Submission.objects.filter(assignment=work, student=request.user).first()
    form = SubmissionForm(request.POST or None, instance=submission)
    if request.method == 'POST':
        if request.user.is_staff:
            return HttpResponseForbidden('Use a student account to submit homework.')
        if form.is_valid():
            entry = form.save(commit=False)
            entry.assignment = work
            entry.student = request.user
            entry.feedback, entry.score, entry.graded_at = '', None, None
            entry.save()
            messages.success(request, 'Homework submitted. Your teacher can now review it.')
            return redirect('assignment', pk=pk)
    return render(request, 'assignment.html', {'work': work, 'submission': submission, 'form': form, 'late': bool(work.due_at and timezone.now() > work.due_at)})


@teacher_required
def review(request, pk):
    submission = get_object_or_404(Submission.objects.select_related('assignment', 'student'), pk=pk, assignment__course__teacher=request.user)
    form = FeedbackForm(request.POST or None, instance=submission)
    if request.method == 'POST' and form.is_valid():
        entry = form.save(commit=False)
        entry.graded_at = timezone.now()
        entry.save()
        messages.success(request, 'Feedback returned to the student.')
        return redirect('dashboard')
    return render(request, 'review.html', {'submission': submission, 'form': form})


@teacher_required
def student_progress(request, pk):
    student = get_object_or_404(teacher_students(request.user), pk=pk)
    courses = my_courses(request.user).filter(enrollment__student=student)
    results = PracticeResult.objects.filter(student=student, course__in=courses)
    assignments = TestAssignment.objects.filter(course__teacher=request.user, course__enrollment__student=student).select_related('course')
    attempts = {a.assignment_id: a for a in TestAttempt.objects.filter(student=student, assignment__in=assignments).select_related('assignment')}
    evidence, recommendations = objective_evidence(student, courses)
    page = Paginator(evidence, 20).get_page(request.GET.get('page'))
    return render(request, 'progress.html', {'student': student, 'progress': page.object_list, 'recommendations': recommendations, 'attempts': results.count(), 'work': [test_status(a, student, attempts.get(a.pk)) for a in assignments], 'teacher_progress': True, 'page': page, 'page_query': pagination_query(request), 'has_evidence': any(r['evidence_count'] for r in evidence)})


@login_required
def password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, 'Password updated.')
        return redirect('dashboard')
    return render(request, 'form.html', {'form': form, 'title': 'Change password', 'button': 'Save password'})


@require_POST
@login_required
def practice_attempt(request):
    if request.user.is_staff:
        return JsonResponse({'error': 'Use a student account to save practice.'}, status=403)
    course = get_object_or_404(Course, slug='statistics', enrollment__student=request.user)
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        if data.get('account_id') != request.user.pk:
            return JsonResponse({'error': 'Account changed. Reload this page before practising.'}, status=409)
        session_id = uuid.UUID(data['session_id'])
        q = questions()[data['question_id']]
        answers, assisted = data['answers'], data['assisted']
        if not isinstance(answers, dict) or type(assisted) is not bool:
            raise ValueError
        valid, correct = score(q, answers)
        if not valid:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        return JsonResponse({'error': 'Invalid practice answer.'}, status=400)
    answers = {field['id']: answers.get(field['id'], '') for field in q['fields']}
    # Browser cannot supply a score, student identity, or objective mapping.
    objectives = sorted({o for field in q['fields'] for o in field.get('objectiveIds', [])} | set([q['primaryObjective']]))
    with transaction.atomic():
        result, created = PracticeResult.objects.get_or_create(student=request.user, session_id=session_id, question_id=q['id'], defaults={'course': course, 'objective_ids': objectives, 'first_correct': correct, 'first_assisted': assisted, 'latest_correct': correct, 'answers': answers})
        if not created:
            result.latest_correct, result.answers = correct, answers
            result.save(update_fields=['latest_correct', 'answers', 'updated_at'])
    return JsonResponse({'saved': True, 'correct': correct})


@ensure_csrf_cookie
def course_site(request, asset='index.html'):
    if not asset:
        asset = 'index.html'
    target = (settings.SITE_DIR / asset).resolve()
    if not target.is_relative_to(settings.SITE_DIR.resolve()) or any(part.startswith('.') for part in asset.split('/')) or not target.is_file():
        raise Http404
    if target.suffix.lower() not in {'.html', '.css', '.js', '.mjs', '.json', '.png', '.jpg', '.jpeg', '.webp', '.svg', '.woff', '.woff2', '.pdf', '.pptx', '.docx', '.xlsx', '.bib'}:
        raise Http404
    if target.suffix == '.html':
        # Reading course information is public. Interactive practice requires an enrolled account.
        if target.name == 'statistics-practice.html':
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path())
            get_object_or_404(my_courses(request.user), slug='statistics')
        text = target.read_text(encoding='utf8')
        text = text.replace('<html ', '<html data-platform-site="true" ', 1)
        text = text.replace('</head>', '<link rel="stylesheet" href="/platform-assets/header.css"><script src="/platform-assets/account.js" defer></script><script src="/platform-assets/practice-bridge.js" defer></script></head>')
        header = render_to_string('header.html', request=request)
        text = re.sub(r'<header class="site-header">.*?</header>', lambda _: header, text, count=1, flags=re.S)
        if target.name == 'statistics-practice.html':
            banner = '<p id="platform-save-status" class="practice-save-banner" role="status">' + ('Teacher preview · results are not saved' if request.user.is_staff else 'Practice results save to your account') + '</p>'
            text = text.replace('<main id="main">', '<main id="main">' + banner)
        response = HttpResponse(text)
        response['Cache-Control'] = 'no-store'
        return response
    return FileResponse(target.open('rb'))


def session_status(request):
    response = JsonResponse({'account_id': request.user.pk if request.user.is_authenticated else None})
    response['Cache-Control'] = 'no-store'
    return response
