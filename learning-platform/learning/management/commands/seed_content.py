from django.core.management.base import BaseCommand, CommandError
from learning.content import ensure_course_content
from learning.models import Course


class Command(BaseCommand):
    help = 'Import existing course outlines into editable folders once, preserving later teacher edits.'

    def add_arguments(self, parser):
        parser.add_argument('--course', help='Import just this course slug.')

    def handle(self, *args, **options):
        courses = Course.objects.all().order_by('pk')
        if options['course']:
            courses = courses.filter(slug=options['course'])
            if not courses.exists():
                raise CommandError('Course not found.')
        for course in courses:
            count = ensure_course_content(course)
            self.stdout.write(f'{course.title}: {count} materials/folders imported. Existing content preserved.')
