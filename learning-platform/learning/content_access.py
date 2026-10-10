"""Keep material visibility consistent with legacy lesson and test entry points."""
from django.http import Http404
from .content import content_visible, visible_items
from .models import ContentItem


def test_is_visible(assignment, user):
    material = ContentItem.objects.filter(test=assignment).select_related('course', 'parent').first()
    return material is None or content_visible(material, user)


def hidden_test_ids(user):
    items = list(ContentItem.objects.filter(kind='test', course__enrollment__student=user).select_related('course'))
    visible = {item.pk for item in visible_items(items, user)}
    return [item.test_id for item in items if item.pk not in visible]


def require_lesson_visible(course, key, user):
    folder = ContentItem.objects.filter(course=course, source_key=f'class:{key}').select_related('course', 'parent').first()
    if folder and not content_visible(folder, user):
        raise Http404
    return folder


def legacy_material(course, key, index, user):
    item = ContentItem.objects.filter(course=course, source_key=f'material:{key}:{index}').select_related('course', 'parent').first()
    if item and not content_visible(item, user):
        raise Http404
    return item
