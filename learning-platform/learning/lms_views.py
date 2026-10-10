import csv
import io
import secrets
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from openpyxl import Workbook
from .gradebook import gradebook_data
from .planner import PlannerFilters, calendar_month, pending_tasks, task_rows
from .student_import import HEADERS, StudentImportForm, apply_import, parse_upload, validate_rows
from .models import Course
from .views import pagination_query, teacher_required


@teacher_required
def gradebook(request):
    return render(request, 'gradebook.html', gradebook_data(request.user, request.GET))


@login_required
def to_do(request):
    if request.user.is_staff:
        return redirect('dashboard')
    form = PlannerFilters(request.user, request.GET)
    tests = pending_tasks(request.user)
    if form.is_valid():
        tests = pending_tasks(request.user, form.cleaned_data['course'], form.cleaned_data['status'])
    else:
        tests = tests.none()
    page = Paginator(tests, 25).get_page(request.GET.get('page'))
    return render(request, 'to_do.html', {'filter_form': form, 'work': task_rows(page.object_list), 'page': page, 'page_query': pagination_query(request)})


@login_required
def student_calendar(request):
    form = PlannerFilters(request.user, request.GET)
    form.fields.pop('status')
    selected = request.GET.get('month', timezone.localdate().strftime('%Y-%m'))
    context = {'filter_form': form, 'selected_month': selected}
    if form.is_valid():
        try:
            context.update(calendar_month(request.user, selected, form.cleaned_data['course']))
            course = form.cleaned_data['course']
            context['course_query'] = f'&course={course.pk}' if course else ''
            context['undated'] = 0 if request.user.is_staff else pending_tasks(request.user, course).filter(due_at__isnull=True).count()
        except ValidationError as error:
            context['month_error'] = error.messages[0]
    return render(request, 'calendar.html', context)


def import_stage(request):
    stage = request.session.get('student_import')
    if stage and stage.get('teacher') == request.user.pk and stage.get('created', 0) > (timezone.now() - timedelta(minutes=30)).timestamp():
        return stage
    request.session.pop('student_import', None)
    return None


@teacher_required
def import_students(request):
    form = StudentImportForm()
    stage = import_stage(request)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'cancel':
            request.session.pop('student_import', None)
            return redirect('import_students')
        if action == 'apply':
            if not stage or not secrets.compare_digest(stage['token'], request.POST.get('token', '')):
                messages.error(request, 'This import preview expired. Upload your file again.')
                return redirect('import_students')
            try:
                result = apply_import(request.user, stage['rows'])
            except (ValidationError, IntegrityError):
                messages.error(request, 'No changes were saved. The list contains errors or an account changed; review the preview again.')
            else:
                request.session.pop('student_import', None)
                return render(request, 'import_complete.html', result)
        elif action == 'upload':
            request.session.pop('student_import', None)
            stage = None
            form = StudentImportForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    raw_rows = parse_upload(form.cleaned_data['file'])
                except ValidationError as error:
                    form.add_error('file', error)
                else:
                    request.session['student_import'] = {'teacher': request.user.pk, 'created': timezone.now().timestamp(), 'token': secrets.token_urlsafe(32), 'rows': raw_rows}
                    return redirect('import_students')
        else:
            return HttpResponse('Unknown import action.', status=400)
    checked = validate_rows(request.user, stage['rows']) if stage else []
    page = Paginator(checked, 25).get_page(request.GET.get('page'))
    return render(request, 'student_import.html', {'form': form, 'stage': stage, 'preview': page.object_list, 'page': page,
                                                 'errors': sum(bool(row['errors']) for row in checked), 'new_count': sum(not row['existing_id'] for row in checked),
                                                 'update_count': sum(bool(row['existing_id']) for row in checked), 'courses': Course.objects.filter(teacher=request.user).order_by('title')})


@teacher_required
def import_template(request):
    # A blank template never contains existing students or passwords.
    if request.GET.get('format') == 'xlsx':
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Students'
        sheet.append(HEADERS)
        for column in 'ABCDEF':
            sheet.column_dimensions[column].width = 25
        output = io.BytesIO()
        workbook.save(output)
        response = HttpResponse(output.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="student-import-template.xlsx"'
    else:
        output = io.StringIO()
        csv.writer(output).writerow(HEADERS)
        response = HttpResponse('\ufeff' + output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="student-import-template.csv"'
    response['Cache-Control'] = 'no-store'
    return response
