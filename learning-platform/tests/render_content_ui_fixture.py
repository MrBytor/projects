"""Render synthetic UI fixtures using an in-memory DB; never contact the running site."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(output):
    with TemporaryDirectory(prefix='teaching-content-ui-') as private:
        os.environ['TEACHING_DATA_DIR'] = private
        os.environ['DJANGO_SETTINGS_MODULE'] = 'platform_config.settings'
        from django.conf import settings
        settings.DATABASES['default']['NAME'] = ':memory:'
        settings.ALLOWED_HOSTS = ['testserver']
        import django
        django.setup()
        from django.core.management import call_command
        call_command('migrate', verbosity=0)
        from django.contrib.auth.models import User
        from django.core.files.base import ContentFile
        from django.test import Client
        from django.urls import reverse
        from learning.models import Course, ContentItem, Enrollment
        teacher = User.objects.create_user('preview-teacher', first_name='Alex', last_name='Morgan', is_staff=True)
        student = User.objects.create_user('preview-student', first_name='Jordan')
        course = Course.objects.create(slug='statistics', title='Statistics', image='statistics.jpg', teacher=teacher, content_imported=True)
        Enrollment.objects.create(student=student, course=course)
        module = ContentItem.objects.create(course=course, kind='folder', title='Module 1 · Foundations', position=10, color='blue')
        course_page = ContentItem.objects.create(course=course, kind='page', title='Course reference guide', position=20)
        next_module = ContentItem.objects.create(course=course, kind='folder', title='Module 2: Working with data', position=30, color='purple')
        only_folder = ContentItem.objects.create(course=course, parent=next_module, kind='folder', title='Only folder in this module', color='yellow')
        ContentItem.objects.create(course=course, parent=only_folder, kind='page', title='Single-folder lesson notes')
        lesson = ContentItem.objects.create(course=course, parent=module, kind='folder', title='Class 1B · Calculations in context', description='Algebra, equations, and calculations applied to everyday problems.', position=10, color='yellow')
        ContentItem.objects.create(course=course, parent=lesson, kind='page', title='Getting started', description='Read the class goals and try the worked examples.', position=10)
        resources = ContentItem.objects.create(course=course, parent=lesson, kind='folder', title='Extra resources', description='Examples and references for further practice.', position=20, color='green')
        ContentItem.objects.create(course=course, parent=resources, kind='page', title='Practice reference', description='A nested reference for this class.', position=10)
        ContentItem.objects.create(course=course, parent=lesson, kind='link', title='Preparation for next class', url='https://example.com/lesson', availability='draft', position=30)
        hidden = ContentItem.objects.create(course=course, parent=module, kind='folder', title='Teacher planning folder', availability='draft', position=20)
        ContentItem.objects.create(course=course, parent=hidden, kind='page', title='Unreleased answers', availability='published')
        upload_video = ContentItem(course=course, parent=lesson, kind='video', title='Worked example video', position=40, original_name='worked-example.webm')
        upload_video.file.save('worked-example.webm', ContentFile(b'Offline fixture: browser supplies a generated WebM.'), save=False)
        upload_video.save()
        linked_video = ContentItem.objects.create(course=course, parent=lesson, kind='video', title='Linked lesson video', url='https://www.youtube.com/watch?v=dQw4w9WgXcQ', position=50)
        external_video = ContentItem.objects.create(course=course, parent=lesson, kind='video', title='External lesson video', url='https://example.com/video/lesson', position=60)
        client = Client()
        client.force_login(teacher)
        browser_url = reverse('course_workspace', args=[course.slug])
        create_url = reverse('content_create', args=[course.slug])
        fixture = {'browser_url': browser_url, 'routes': {}, 'account_id': teacher.pk,
                   'module_id': module.pk, 'lesson_id': lesson.pk, 'resources_id': resources.pk,
                   'hidden_id': hidden.pk,
                   'next_module_id': next_module.pk, 'course_page_id': course_page.pk,
                   'only_folder_id': only_folder.pk,
                   'root_order': list(ContentItem.objects.filter(course=course, parent=None).order_by('position', 'pk').values_list('pk', flat=True)),
                   'lesson_order': list(ContentItem.objects.filter(course=course, parent=lesson).order_by('position', 'pk').values_list('pk', flat=True)),
                   'success_redirect': browser_url + f'#folder-{lesson.pk}',
                   'student_url': browser_url + '?preview=student'}
        fixture['routes'][browser_url] = client.get(browser_url).content.decode()
        for kind in ('folder', 'file', 'page', 'video', 'link', 'test'):
            url = create_url + f'?kind={kind}&parent={lesson.pk}'
            response = client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            assert response.status_code == 200, (kind, response.status_code)
            fixture['routes'][url] = response.content.decode()
        for key, video_item in [('video_detail_url', upload_video), ('video_embed_url', linked_video), ('video_external_url', external_video)]:
            url = reverse('content_detail', args=[course.slug, video_item.pk])
            response = client.get(url)
            assert response.status_code == 200, (key, response.status_code)
            fixture[key] = url
            fixture['routes'][url] = response.content.decode()
        fixture['video_stream_url'] = reverse('content_video', args=[course.slug, upload_video.pk])
        fixture['video_download_url'] = reverse('content_download', args=[course.slug, upload_video.pk])
        standalone_video_url = create_url + f'?kind=video&parent={lesson.pk}&preview=standalone'
        fixture['standalone_video_url'] = standalone_video_url
        fixture['routes'][standalone_video_url] = client.get(standalone_video_url).content.decode()
        folder_url = create_url + f'?kind=folder&parent={lesson.pk}'
        invalid = client.post(folder_url, {'title': '', 'color': 'blue', 'availability': 'published', 'account_id': teacher.pk}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        fixture['invalid_folder_html'] = invalid.content.decode()
        scheduled = client.post(folder_url, {'title': 'Scheduled folder', 'color': 'blue', 'availability': 'scheduled', 'account_id': teacher.pk}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        fixture['invalid_scheduled_html'] = scheduled.content.decode()
        client.force_login(student)
        fixture['routes'][fixture['student_url']] = client.get(browser_url).content.decode()
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(fixture), encoding='utf-8')
        print('Rendered isolated teacher/student course trees, six dialogs, and video player fixtures.')


if __name__ == '__main__':
    main(sys.argv[1])
