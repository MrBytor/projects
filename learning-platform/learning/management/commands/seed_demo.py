import secrets
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from learning.models import Course, Enrollment, StudentRegistration, TestAssignment
from learning.scoring import questions


class Command(BaseCommand):
    help = 'Create local test accounts, course enrolments and a sample homework test.'

    @transaction.atomic
    def handle(self, *args, **kwargs):
        credentials = []
        users = {}
        for username, name, staff in [('teacher-demo', 'Jacob', True), ('student-demo', 'Demo student', False)]:
            user, created = User.objects.get_or_create(username=username, defaults={'first_name': name, 'is_staff': staff})
            if created:
                password = secrets.token_urlsafe(18)
                user.set_password(password)
                user.save()
                credentials.append(f'{name}\nUsername: {username}\nPassword: {password}\n')
            users[username] = user
        _, new_registration = StudentRegistration.objects.get_or_create(student=users['student-demo'], teacher=users['teacher-demo'])
        for slug, title, image in [('statistics', 'Statistics', 'statistics.jpg'), ('corporate-finance', 'Corporate Finance', 'finance.jpg'), ('project-management', 'Project Management', 'project-management.jpg')]:
            course, _ = Course.objects.get_or_create(slug=slug, defaults={'title': title, 'image': image, 'teacher': users['teacher-demo']})
            if new_registration:
                Enrollment.objects.get_or_create(student=users['student-demo'], course=course)
        TestAssignment.objects.get_or_create(course=Course.objects.get(slug='statistics'), title='Demo test · Statistics foundations', defaults={'week': 1, 'instructions': 'A five-question sample to try the homework workflow. Save your progress or submit all answers to see your score.', 'question_snapshot': [q for q in questions().values() if q['week'] == 1][:5]})
        if credentials:
            path = settings.DATA_DIR / 'local-credentials.txt'
            with path.open('a', encoding='utf8') as file:
                file.write('Local teaching platform: http://127.0.0.1:8765/\n\n' + '\n'.join(credentials) + '\n')
            self.stdout.write(f'Credentials saved privately on this computer: {path}')
        self.stdout.write('Local demo ready. Existing passwords and student work were preserved.')
