"""Course-owned folders and materials, with small server-validated dialogs."""
import mimetypes
import re
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_safe

from .content import ancestors, can_manage_course, content_visible, ensure_course_content, folders_for_move, visible_items
from .content_forms import ContentItemForm
from .curriculum import cached_fingerprint, cached_preview, get_lesson, trusted_material
from .models import ContentItem, Course, TestAssignment
from .scoring import questions
from .views import my_courses
from .video import video_embed
from .video_streaming import video_response


def course_for(request, slug, *, manage=False):
    course = get_object_or_404(my_courses(request.user).select_related('teacher'), slug=slug)
    if manage and not can_manage_course(request.user, course):
        raise PermissionError
    ensure_course_content(course)
    return course


def item_for(request, course, pk):
    item = get_object_or_404(ContentItem.objects.select_related('course', 'parent', 'test'), course=course, pk=pk)
    if not content_visible(item, request.user):
        raise Http404
    return item


def folder_url(course, folder=None):
    """Return to the folder in the course tree after an authoring action."""
    url = reverse('course_workspace', args=[course.slug])
    return f'{url}#folder-{folder.pk}' if folder else url


def parent_from(request, course):
    raw = request.GET.get('parent')
    if not raw:
        return None
    if not raw.isdigit():
        raise Http404
    return get_object_or_404(ContentItem, course=course, pk=raw, kind='folder')


def protect_mutation(request):
    return request.method != 'POST' or request.POST.get('account_id') == str(request.user.pk)


def browser(request, course, folder=None):
    # Filter the complete tree before attaching children: hidden ancestors must
    # never expose their materials through an expanded student folder.
    rows = visible_items(ContentItem.objects.filter(course=course).select_related('course'), request.user)
    nodes = {row.pk: row for row in rows}
    roots = []
    for row in rows:
        row.tree_children = []
        row.open_url = row.get_absolute_url()
        row.lesson = get_lesson(course.slug, row.lesson_key) if row.kind == 'folder' and row.lesson_key else None
    for row in rows:
        if row.parent_id == (folder.pk if folder else None):
            roots.append(row)
        parent = nodes.get(row.parent_id)
        if parent and parent.kind == 'folder':
            parent.tree_children.append(row)
    for row in rows:
        row.child_count = len(row.tree_children)
    crumbs = [*ancestors(folder), folder] if folder else []
    lesson = get_lesson(course.slug, folder.lesson_key) if folder and folder.lesson_key else None
    return render(request, 'content_browser.html', {
        'workspace_course': course, 'current_folder': folder, 'breadcrumbs': crumbs,
        'items': roots, 'can_manage': can_manage_course(request.user, course), 'lesson': lesson,
        'folder_storage_key': f'lms-folders:{request.user.pk}:{course.pk}',
    })


@login_required
def content_folder(request, slug, pk):
    course = course_for(request, slug)
    folder = item_for(request, course, pk)
    if folder.kind != 'folder':
        raise Http404
    return browser(request, course, folder)


class MaterialTestForm(ContentItemForm):
    """Existing tests can be placed, or a bank snapshot created in the same dialog."""
    question_ids = forms.MultipleChoiceField(required=False, label='Or choose questions from the bank', widget=forms.CheckboxSelectMultiple)
    due_at = forms.DateTimeField(required=False, label='Due date (optional)', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['question_ids'].choices = [(q['id'], f"Week {q['week']} · {q['title']}") for q in questions().values()] if self.instance.course.slug == 'statistics' else []
        self.fields['question_ids'].help_text = 'Choose up to 50 questions. New tests are assigned to enrolled students when published.'
        self.fields['due_at'].help_text = 'China time (UTC+8). Applies to a new test.'
        if self.instance.pk:
            # Relinking could expose the old test as an unplaced assignment and
            # confuse existing attempts. Edit questions through a new test instead.
            self.fields['test'].disabled = True
            self.fields.pop('question_ids')
            self.fields.pop('due_at')
        elif not self.fields['question_ids'].choices:
            self.fields.pop('question_ids')
            self.fields.pop('due_at')
        self.order_fields(['title', 'description', 'test', 'question_ids', 'due_at', 'availability', 'available_from', 'available_until'])

    def clean(self):
        data = super().clean()
        selected = list(dict.fromkeys(data.get('question_ids', [])))
        data['question_ids'] = selected
        if len(selected) > 50:
            self.add_error('question_ids', 'Choose up to 50 questions.')
        if data.get('test') and selected:
            self.add_error(None, 'Choose an existing test or bank questions, not both.')
        if not data.get('test') and not selected:
            self.add_error('test', 'Choose an existing test or select questions from the Statistics bank.')
        return data


def dialog(request, course, form, title, action, cancel_url, submit='Save changes'):
    return render(request, 'content_dialog.html', {
        'workspace_course': course, 'form': form, 'dialog_title': title, 'dialog_action': action,
        'cancel_url': cancel_url, 'submit_label': submit,
        'dialog_fragment': request.headers.get('X-Requested-With') == 'XMLHttpRequest',
    })


def saved(request, url, message):
    messages.success(request, message)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'redirect': url})
    return redirect(url)


def add_validation_errors(form, error):
    for name, errors in getattr(error, 'message_dict', {'__all__': error.messages}).items():
        form.add_error(name if name in form.fields else None, errors)


def save_item(request, course, item=None):
    kind = item.kind if item else request.GET.get('kind', 'folder')
    if kind not in {'folder', 'file', 'page', 'link', 'test', 'video'}:
        raise Http404
    parent = item.parent if item else parent_from(request, course)
    form_class = MaterialTestForm if kind == 'test' else ContentItemForm
    form = form_class(request.POST if request.method == 'POST' else None, request.FILES if request.method == 'POST' else None,
                      course=course, kind=kind, parent=parent, instance=item)
    target = folder_url(course, parent)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                # Serialize hierarchy edits, including validation against current parents.
                Course.objects.select_for_update().get(pk=course.pk)
                entry = form.save(commit=False)
                if not entry.pk:
                    entry.position = (ContentItem.objects.filter(course=course, parent=parent).aggregate(value=Max('position'))['value'] or 0) + 1
                if kind == 'test' and not entry.test_id:
                    snapshot = [questions()[ident] for ident in form.cleaned_data['question_ids']]
                    lesson_folder = next((f for f in ([parent] + list(reversed(ancestors(parent)))) if f and f.lesson_key), None) if parent else None
                    lesson = get_lesson(course.slug, lesson_folder.lesson_key) if lesson_folder else None
                    weeks = {q['week'] for q in snapshot}
                    entry.test = TestAssignment.objects.create(course=course, title=entry.title, instructions=entry.description,
                        question_snapshot=snapshot, due_at=form.cleaned_data.get('due_at'),
                        week=lesson['week'] if lesson else next(iter(weeks)) if len(weeks) == 1 else None,
                        class_label=f"Class {lesson['letter'].upper()}" if lesson and course.slug == 'statistics' else '')
                entry.full_clean()
                entry.save()
                if kind == 'file' and 'file' in request.FILES:
                    from .presentation_jobs import queue_presentation_preview
                    transaction.on_commit(lambda: queue_presentation_preview(entry))
                if entry.test_id:
                    # The question snapshot and existing attempts never change on material edits.
                    TestAssignment.objects.filter(pk=entry.test_id).update(title=entry.title)
        except ValidationError as error:
            add_validation_errors(form, error)
        except IntegrityError:
            form.add_error(None, 'This material changed while you were editing. Reload the folder and try again.')
        else:
            return saved(request, target, 'Material updated.' if item else 'Folder created.' if kind == 'folder' else 'Material added.')
    labels = {'folder': 'folder', 'file': 'file or presentation', 'page': 'lesson page', 'link': 'link', 'test': 'quiz / test', 'video': 'video'}
    return dialog(request, course, form, ('Edit ' if item else 'Add ') + labels[kind], request.get_full_path(), target,
                  'Save changes' if item else 'Create folder' if kind == 'folder' else 'Add material')


@login_required
def content_create(request, slug):
    try:
        course = course_for(request, slug, manage=True)
    except PermissionError:
        return HttpResponseForbidden('Teacher access required.')
    if not protect_mutation(request):
        return HttpResponseForbidden('Account changed. Reload before saving.')
    return save_item(request, course)


@login_required
def content_edit(request, slug, pk):
    try:
        course = course_for(request, slug, manage=True)
    except PermissionError:
        return HttpResponseForbidden('Teacher access required.')
    if not protect_mutation(request):
        return HttpResponseForbidden('Account changed. Reload before saving.')
    return save_item(request, course, item_for(request, course, pk))


class MoveForm(forms.Form):
    parent = forms.TypedChoiceField(label='Destination folder', required=False, empty_value=None, coerce=int)

    def __init__(self, course, item, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['parent'].choices = [('', f'{course.title} — course materials')] + [(f.pk, ' / '.join(a.title for a in [*ancestors(f), f])) for f in folders_for_move(course, item)]
        self.fields['parent'].initial = item.parent_id


@login_required
def content_move(request, slug, pk):
    try:
        course = course_for(request, slug, manage=True)
    except PermissionError:
        return HttpResponseForbidden('Teacher access required.')
    if not protect_mutation(request):
        return HttpResponseForbidden('Account changed. Reload before saving.')
    item = item_for(request, course, pk)
    target = folder_url(course, item.parent)
    form = MoveForm(course, item, request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                Course.objects.select_for_update().get(pk=course.pk)
                item.refresh_from_db()
                item.parent = get_object_or_404(ContentItem, course=course, pk=form.cleaned_data['parent'], kind='folder') if form.cleaned_data['parent'] else None
                item.position = (ContentItem.objects.filter(course=course, parent=item.parent).aggregate(value=Max('position'))['value'] or 0) + 1
                item.full_clean()
                item.save()
        except ValidationError as error:
            add_validation_errors(form, error)
        else:
            return saved(request, folder_url(course, item.parent), 'Material moved.')
    return dialog(request, course, form, f'Move: {item.title}', request.get_full_path(), target, 'Move here')


@login_required
@require_POST
def content_reorder(request, slug, pk):
    try:
        course = course_for(request, slug, manage=True)
    except PermissionError:
        return HttpResponseForbidden('Teacher access required.')
    if not protect_mutation(request):
        return HttpResponseForbidden('Account changed. Reload before saving.')
    item = item_for(request, course, pk)
    if 'order' in request.POST:
        return reorder_dragged_folder(request, course, item)
    direction = request.POST.get('direction')
    if direction not in {'up', 'down'}:
        return HttpResponseForbidden('Choose up or down.')
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=course.pk)
        siblings = list(ContentItem.objects.filter(course=course, parent=item.parent).order_by('position', 'pk'))
        index = next(i for i, s in enumerate(siblings) if s.pk == item.pk)
        dest = index + (-1 if direction == 'up' else 1)
        if 0 <= dest < len(siblings):
            siblings[index], siblings[dest] = siblings[dest], siblings[index]
            for position, sibling in enumerate(siblings, 1):
                sibling.position = position
            ContentItem.objects.bulk_update(siblings, ['position'])
    return redirect(folder_url(course, item.parent))


def reorder_dragged_folder(request, course, item):
    """Persist one complete sibling order without moving or overwriting content."""
    def identifiers(value):
        if len(value) > 100000:
            raise ValueError
        parts = value.split(',')
        if len(parts) > 10000 or not all(re.fullmatch(r'[1-9][0-9]{0,18}', part) for part in parts):
            raise ValueError
        result = [int(part) for part in parts]
        if len(set(result)) != len(result):
            raise ValueError
        return result

    if item.kind != 'folder':
        return JsonResponse({'error': 'Use a folder drag handle to change the order.'}, status=400)
    try:
        ordered_ids = identifiers(request.POST.get('order', ''))
        expected_ids = identifiers(request.POST.get('expected_order', ''))
    except ValueError:
        return JsonResponse({'error': 'The folder order is invalid. Refresh the page and try again.'}, status=400)
    with transaction.atomic():
        Course.objects.select_for_update().get(pk=course.pk)
        item.refresh_from_db()
        if request.POST.get('parent') != (str(item.parent_id) if item.parent_id else ''):
            return JsonResponse({'error': 'This folder has moved. Refresh the page before reordering it.'}, status=409)
        siblings = list(ContentItem.objects.filter(course=course, parent_id=item.parent_id).order_by('position', 'pk'))
        current_ids = [sibling.pk for sibling in siblings]
        if expected_ids != current_ids:
            return JsonResponse({'error': 'The materials changed since this page opened. Refresh the page and try again.'}, status=409)
        if set(ordered_ids) != set(current_ids):
            return JsonResponse({'error': 'Only reorder the materials in this folder.'}, status=400)
        if ordered_ids != current_ids:
            positions = {ident: index for index, ident in enumerate(ordered_ids, 1)}
            for sibling in siblings:
                sibling.position = positions[sibling.pk]
            ContentItem.objects.bulk_update(siblings, ['position'])
    return JsonResponse({'order': ordered_ids, 'parent': item.parent_id})


@login_required
@require_POST
def content_visibility(request, slug, pk):
    try:
        course = course_for(request, slug, manage=True)
    except PermissionError:
        return HttpResponseForbidden('Teacher access required.')
    if not protect_mutation(request):
        return HttpResponseForbidden('Account changed. Reload before saving.')
    item = item_for(request, course, pk)
    state = request.POST.get('availability') or ('published' if item.availability == 'draft' else 'draft')
    if state not in {'draft', 'published'}:
        return HttpResponseForbidden('Invalid visibility.')
    item.availability = state
    item.available_from = item.available_until = None
    item.save(update_fields=['availability', 'available_from', 'available_until', 'updated_at'])
    return saved(request, folder_url(course, item.parent), 'Published to enrolled students.' if state == 'published' else 'Hidden from students, including contents of this folder.')


def material_path(item):
    if item.kind not in {'file', 'video'} or (item.kind == 'video' and not item.file):
        raise Http404
    if item.file:
        path = Path(item.file.path).resolve()
        if not path.is_relative_to((settings.DATA_DIR / 'content-files').resolve()) or not path.is_file():
            raise Http404
        return path
    material = trusted_material(item.source_path)
    if not material:
        raise Http404
    return settings.SITE_DIR / material['path']


def file_preview(item):
    path = material_path(item)
    if path.suffix.lower() != '.pptx':
        return None
    stat = path.stat()
    fingerprint = cached_fingerprint(path, stat.st_mtime_ns, stat.st_size)
    folder = settings.DATA_DIR / 'slide-previews' / fingerprint
    try:
        stat = (folder / 'manifest.json').stat()
        return cached_preview(folder, stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError, TypeError, KeyError):
        return None


@login_required
def content_detail(request, slug, pk):
    course = course_for(request, slug)
    item = item_for(request, course, pk)
    if item.kind == 'folder':
        return redirect(folder_url(course, item))
    if item.kind == 'test':
        if not item.test_id:
            raise Http404
        return redirect('test_roster' if can_manage_course(request.user, course) else 'take_test', pk=item.test_id)
    preview = file_preview(item) if item.kind == 'file' else None
    slides = [{'number': n, 'url': reverse('content_slide', args=[slug, pk, n])} for n in range(1, preview['count'] + 1)] if preview else []
    file_url = reverse('content_download', args=[slug, pk]) if item.kind == 'file' or (item.kind == 'video' and item.file) else ''
    extension = material_path(item).suffix.lower() if item.kind == 'file' else ''
    video = None
    if item.kind == 'video':
        if item.file:
            extension = material_path(item).suffix.lower()
            if extension not in {'.mp4', '.webm'}:
                raise Http404
            video = {'kind': 'upload', 'src': reverse('content_video', args=[slug, pk]),
                     'mime': 'video/mp4' if extension == '.mp4' else 'video/webm'}
        else:
            linked = video_embed(item.url)
            video = {'kind': linked['kind'], 'src': linked['url'], 'mime': linked['mime_type'],
                     'provider': linked['provider'], 'url': item.url}
    lesson_folder = next((a for a in reversed(ancestors(item)) if a.lesson_key), None)
    return render(request, 'content_detail.html', {
        'workspace_course': course, 'item': item, 'breadcrumbs': ancestors(item),
        'can_manage': can_manage_course(request.user, course), 'file_url': file_url,
        'preview_pdf': extension == '.pdf', 'preview_image': extension in {'.png', '.jpg', '.jpeg'},
        'slides': slides, 'ppt': extension == '.pptx',
        'video': video,
        'lesson': get_lesson(slug, lesson_folder.lesson_key) if lesson_folder else None,
    })


@login_required
def content_download(request, slug, pk):
    course = course_for(request, slug)
    item = item_for(request, course, pk)
    path = material_path(item)
    inline = request.GET.get('inline') == '1' and path.suffix.lower() in {'.pdf', '.png', '.jpg', '.jpeg'}
    response = FileResponse(path.open('rb'), as_attachment=not inline, filename=item.original_name or path.name,
                            content_type=mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    if inline:
        response['X-Frame-Options'] = 'SAMEORIGIN'
    return response


@login_required
@require_safe
def content_video(request, slug, pk):
    """Serve video bytes only after checking current course and folder access."""
    course = course_for(request, slug)
    item = item_for(request, course, pk)
    if item.kind != 'video' or not item.file:
        raise Http404
    path = material_path(item)
    if path.suffix.lower() not in {'.mp4', '.webm'}:
        raise Http404
    return video_response(request, path)


@login_required
def content_slide(request, slug, pk, number):
    course = course_for(request, slug)
    item = item_for(request, course, pk)
    preview = file_preview(item)
    if not preview or not 1 <= number <= preview['count']:
        raise Http404
    path = preview['folder'] / f'Slide{number}.PNG'
    if not path.is_file():
        raise Http404
    response = FileResponse(path.open('rb'), content_type='image/png')
    response['Cache-Control'] = 'private, no-store'
    return response
