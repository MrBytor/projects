"""Authenticated course workspaces and formative lesson checks."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.conf import settings
from .curriculum import outline, get_lesson, quick_questions, presentation_preview
from .forms import TestAnswersForm
from .models import LessonPractice, PracticeResult, TestAssignment, TestAttempt
from .objectives import question_objectives
from .planner import pending_tasks, task_rows
from .scoring import score
from .views import my_courses


def authorised_lesson(request, slug, key):
    course = get_object_or_404(my_courses(request.user).select_related('teacher'), slug=slug)
    from .content import ensure_course_content
    from .content_access import require_lesson_visible
    ensure_course_content(course)
    require_lesson_visible(course, key, request.user)
    lesson = get_lesson(slug, key)
    if not lesson:
        raise Http404
    return course, lesson


@login_required
def course_workspace(request, slug):
    from .material_views import browser, course_for
    return browser(request, course_for(request, slug))


@login_required
def course_practice(request):
    course = get_object_or_404(my_courses(request.user).select_related('teacher'), slug='statistics')
    return render(request, 'course_practice.html', {'workspace_course': course})


@login_required
def course_lesson(request, slug, key):
    course, lesson = authorised_lesson(request, slug, key)
    from .content_access import legacy_material, require_lesson_visible, hidden_test_ids
    from .content import can_manage_course
    folder = require_lesson_visible(course, key, request.user)
    # Work on a copy: the curriculum parser's cached source remains immutable.
    lesson = {**lesson, 'materials': list(lesson['materials'])}
    if folder:
        lesson['description'] = folder.description
    visible_materials = []
    for material in lesson['materials']:
        try:
            entry = legacy_material(course, key, material['index'], request.user)
        except Http404:
            continue
        # A replaced source is opened through its new private material viewer.
        if entry and entry.file:
            continue
        visible_materials.append(material)
    lesson['materials'] = visible_materials
    snapshot = quick_questions(slug, lesson)
    practice = None
    if snapshot and not request.user.is_staff:
        practice, _ = LessonPractice.objects.get_or_create(student=request.user, course=course, lesson_key=key, defaults={'question_snapshot': snapshot})
        snapshot = practice.question_snapshot
    checking = request.method == 'POST' and request.POST.get('action') == 'check'
    form = TestAnswersForm(snapshot, request.POST if request.method == 'POST' else None, answers=practice.answers if practice else {}, submitting=checking)
    feedback = []
    if request.method == 'POST':
        if request.user.is_staff:
            return HttpResponseForbidden('Teacher preview does not save student practice.')
        if not practice or request.POST.get('action') not in {'save', 'check'}:
            return HttpResponseForbidden('No lesson practice is available.')
        if request.POST.get('account_id') != str(request.user.pk):
            return HttpResponseForbidden('Account changed. Reload this lesson before saving.')
        if form.is_valid():
            answers = form.answer_data()
            with transaction.atomic():
                # Lock the saved session so concurrent checks retain the first attempt.
                practice = LessonPractice.objects.select_for_update().get(pk=practice.pk)
                practice.answers = answers
                if checking:
                    results = []
                    for question in snapshot:
                        valid, correct = score(question, answers[question['id']])
                        result, created = PracticeResult.objects.get_or_create(student=request.user, course=course, session_id=practice.session_id, question_id=question['id'], defaults={'objective_ids': sorted(question_objectives(question)), 'first_correct': correct, 'first_assisted': False, 'latest_correct': correct, 'answers': answers[question['id']]})
                        if not created:
                            result.latest_correct, result.answers = correct, answers[question['id']]
                            result.save(update_fields=['latest_correct', 'answers', 'updated_at'])
                        results.append({'title': question['title'], 'correct': correct})
                    practice.last_results = results
                    practice.checked_at = timezone.now()
                else:
                    # Draft changes invalidate displayed feedback, not historic learning evidence.
                    practice.last_results = []
                practice.save()
            messages.success(request, 'Answers checked and progress saved.' if checking else 'Draft saved. You can continue this lesson later.')
            return redirect('course_lesson', slug=slug, key=key)
    if practice and request.method != 'POST':
        feedback = practice.last_results
    rows = form.question_rows()
    for i, row in enumerate(rows):
        row['feedback'] = feedback[i] if len(feedback) == len(rows) else None
    ppt = next((m for m in lesson['materials'] if m['kind'] == 'PPTX'), None)
    preview = presentation_preview(ppt) if ppt else None
    slides = [{'number': n, 'url': f"{lesson['url']}slides/{ppt['index']}/{n}/"} for n in range(1, preview['count'] + 1)] if preview else []
    assigned = TestAssignment.objects.filter(course=course, week=lesson['week']).defer('question_snapshot')
    if slug == 'statistics':
        assigned = assigned.filter(class_label__iexact=f"Class {lesson['letter'].upper()}")
    if not request.user.is_staff:
        assigned = assigned.exclude(pk__in=hidden_test_ids(request.user))
    return render(request, 'course_lesson.html', {'workspace_course': course, 'lesson': lesson, 'ppt': ppt, 'slides': slides, 'quick_form': form, 'question_rows': rows, 'practice': practice, 'lesson_tests': assigned[:5], 'content_folder': folder, 'can_manage': can_manage_course(request.user, course)})


@login_required
def lesson_material(request, slug, key, index):
    course, lesson = authorised_lesson(request, slug, key)
    from .content_access import legacy_material
    entry = legacy_material(course, key, index, request.user)
    if entry and entry.file:
        return redirect('content_download', slug=slug, pk=entry.pk)
    if index >= len(lesson['materials']):
        raise Http404
    material = lesson['materials'][index]
    response = FileResponse((settings.SITE_DIR / material['path']).open('rb'), as_attachment=True, filename=material['name'])
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def lesson_slide(request, slug, key, index, number):
    course, lesson = authorised_lesson(request, slug, key)
    from .content_access import legacy_material
    entry = legacy_material(course, key, index, request.user)
    if entry and entry.file:
        return redirect('content_slide', slug=slug, pk=entry.pk, number=number)
    if index >= len(lesson['materials']) or lesson['materials'][index]['kind'] != 'PPTX':
        raise Http404
    preview = presentation_preview(lesson['materials'][index])
    if not preview or not 1 <= number <= preview['count']:
        raise Http404
    target = preview['folder'] / f'Slide{number}.PNG'
    if not target.is_file():
        raise Http404
    response = FileResponse(target.open('rb'), content_type='image/png')
    response['Cache-Control'] = 'private, no-store'
    return response
