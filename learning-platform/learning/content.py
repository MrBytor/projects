"""Editable course material trees, imported once from the public curriculum."""
import re
from django.db import transaction
from django.utils import timezone
from .curriculum import outline
from .models import ContentItem, Course, Enrollment, TestAssignment


def can_manage_course(user, course):
    return bool(user.is_authenticated and user.is_active and (user.is_superuser or (user.is_staff and course.teacher_id == user.pk)))


def ancestors(item):
    """Return root-to-parent ancestors; malformed historic trees fail closed."""
    result, seen = [], {item.pk} if item.pk else set()
    parent = item.parent
    while parent is not None:
        if parent.pk in seen or len(result) >= ContentItem.MAX_DEPTH or parent.course_id != item.course_id or parent.kind != 'folder':
            raise ValueError('Invalid content folder structure.')
        seen.add(parent.pk)
        result.append(parent)
        parent = parent.parent
    return list(reversed(result))


def _available(item, now):
    return (item.availability in {'published', 'scheduled'}
            and not (item.availability == 'scheduled' and not item.available_from)
            and not (item.available_from and item.available_from > now)
            and not (item.available_until and item.available_until <= now))


def content_visible(item, user):
    if can_manage_course(user, item.course):
        return True
    if not user.is_authenticated or not user.is_active or not Enrollment.objects.filter(course_id=item.course_id, student_id=user.pk).exists():
        return False
    try:
        now = timezone.now()
        return all(_available(node, now) for node in [*ancestors(item), item])
    except ValueError:
        return False


def visible_items(queryset, user):
    """Return ordered visible items, including each item's inherited visibility."""
    items = list(queryset)
    if not user.is_authenticated or not user.is_active:
        return []
    # Parent caches avoid a query for each ancestor of every material.
    nodes = {node.pk: node for node in ContentItem.objects.filter(course_id__in={item.course_id for item in items}).select_related('course')}
    for node in nodes.values():
        if node.parent_id is None or node.parent_id in nodes:
            node._state.fields_cache['parent'] = nodes.get(node.parent_id)
    enrolled = set(Enrollment.objects.filter(student_id=user.pk, course_id__in={item.course_id for item in items}).values_list('course_id', flat=True))
    now, result = timezone.now(), []
    for item in items:
        node = nodes[item.pk]
        if can_manage_course(user, node.course):
            result.append(item)
        elif node.course_id in enrolled:
            try:
                if all(_available(part, now) for part in [*ancestors(node), node]):
                    result.append(item)
            except ValueError:
                pass
    return result


def folders_for_move(course, item=None):
    """Selectable destinations, excluding the moved folder and its descendants."""
    folders = list(ContentItem.objects.filter(course=course, kind='folder').order_by('position', 'pk'))
    blocked = {item.pk} if item and item.pk else set()
    changed = True
    while changed:
        additions = {folder.pk for folder in folders if folder.parent_id in blocked} - blocked
        changed = bool(additions)
        blocked.update(additions)
    return [folder for folder in folders if folder.pk not in blocked]


def _test_parent(assignment, lessons):
    label = re.sub(r'[^a-z0-9]', '', assignment.class_label.lower().removeprefix('class').strip())
    if not label:
        return None
    for lesson in lessons:
        key = lesson.lesson_key
        week, letter = key.split('-', 1)
        normalized = week + ('' if letter == 'main' else letter)
        if label == normalized or (assignment.week == int(week) and label == letter):
            return lesson
    return None


@transaction.atomic
def ensure_course_content(course):
    """Import only once. Reopening a course never overwrites teacher edits."""
    locked = Course.objects.select_for_update().get(pk=course.pk)
    if locked.content_imported:
        course.content_imported = True
        return 0
    created_count, lesson_folders = 0, []
    for module_index, module in enumerate(outline(course.slug)):
        parent, created = ContentItem.objects.get_or_create(course=locked, source_key=f'module:{module["number"]}', defaults={
            'kind': 'folder', 'title': module['title'][:160], 'position': module_index, 'color': 'blue',
        })
        created_count += created
        for lesson_index, lesson in enumerate(module['lessons']):
            folder, created = ContentItem.objects.get_or_create(course=locked, source_key=f'class:{lesson["key"]}', defaults={
                'parent': parent, 'kind': 'folder', 'title': f'{lesson["label"]} · {lesson["title"]}'[:160],
                'description': lesson['description'][:10000], 'position': lesson_index, 'color': 'yellow', 'lesson_key': lesson['key'],
            })
            created_count += created
            lesson_folders.append(folder)
            for material_index, material in enumerate(lesson['materials']):
                _, created = ContentItem.objects.get_or_create(course=locked, source_key=f'material:{lesson["key"]}:{material_index}', defaults={
                    'parent': folder, 'kind': 'file', 'title': material.get('label', material['name'])[:160],
                    'position': material_index, 'source_path': material['path'], 'original_name': material['name'],
                })
                created_count += created
    for assignment in TestAssignment.objects.filter(course=locked).order_by('created_at', 'pk'):
        if ContentItem.objects.filter(test=assignment).exists():
            continue
        parent = _test_parent(assignment, lesson_folders)
        _, created = ContentItem.objects.get_or_create(course=locked, source_key=f'test:{assignment.pk}', defaults={
            'parent': parent, 'kind': 'test', 'title': assignment.title, 'description': assignment.instructions,
            'test': assignment, 'position': ContentItem.objects.filter(course=locked, parent=parent).count(),
        })
        created_count += created
    locked.content_imported = True
    locked.save(update_fields=['content_imported'])
    course.content_imported = True
    return created_count
