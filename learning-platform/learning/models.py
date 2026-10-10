from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.urls import reverse
from pathlib import Path
from urllib.parse import urlsplit
import uuid


class PrivateContentStorage(FileSystemStorage):
    @property
    def base_location(self):
        return str(Path(settings.DATA_DIR) / 'content-files')

    @property
    def location(self):
        return str((Path(settings.DATA_DIR) / 'content-files').resolve())


def content_file_storage():
    """Private files are served only by an authorised Django view."""
    return PrivateContentStorage()


def content_upload_path(instance, filename):
    return f'{instance.course_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class Course(models.Model):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=120)
    image = models.CharField(max_length=100)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='taught_courses')
    content_imported = models.BooleanField(default=False)

    def __str__(self):
        return self.title


class LessonPractice(models.Model):
    """Resumable formative answers, separate from assigned and graded homework."""
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    lesson_key = models.CharField(max_length=32)
    session_id = models.UUIDField(default=uuid.uuid4, editable=False)
    question_snapshot = models.JSONField(default=list)
    answers = models.JSONField(default=dict)
    last_results = models.JSONField(default=list)
    checked_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['student', 'course', 'lesson_key'], name='one_lesson_practice')]


class Enrollment(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['student', 'course'], name='one_enrollment')]


class StudentRegistration(models.Model):
    """Keep a teacher's student directory independent of current course access."""
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='teacher_registrations')
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='student_registrations')
    major = models.CharField(max_length=120, blank=True)
    teaching_group = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['student', 'teacher'], name='one_student_registration')]


class Assignment(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    title = models.CharField(max_length=160)
    instructions = models.TextField(max_length=10000)
    due_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Submission(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    answer = models.TextField(max_length=20000)
    submitted_at = models.DateTimeField(auto_now=True)
    feedback = models.TextField(blank=True, max_length=10000)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['assignment', 'student'], name='one_submission'), models.CheckConstraint(condition=models.Q(score__lte=100) | models.Q(score__isnull=True), name='score_out_of_100')]


class PracticeResult(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    session_id = models.UUIDField()
    question_id = models.CharField(max_length=100)
    objective_ids = models.JSONField(default=list)
    first_correct = models.BooleanField()
    first_assisted = models.BooleanField()
    latest_correct = models.BooleanField()
    answers = models.JSONField()
    checked_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['student', 'session_id', 'question_id'], name='one_first_attempt')]


class LoginThrottle(models.Model):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField()


class TestAssignment(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    title = models.CharField(max_length=160)
    instructions = models.TextField(blank=True, max_length=3000)
    week = models.PositiveSmallIntegerField(blank=True, null=True)
    class_label = models.CharField(max_length=80, blank=True)
    due_at = models.DateTimeField(blank=True, null=True)
    # Freeze prompts and marking rules so later bank edits do not alter assigned work.
    question_snapshot = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class TestAttempt(models.Model):
    assignment = models.ForeignKey(TestAssignment, on_delete=models.CASCADE, related_name='attempts')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    answers = models.JSONField(default=dict)
    started_at = models.DateTimeField(auto_now_add=True)
    saved_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
    correct_count = models.PositiveSmallIntegerField(blank=True, null=True)
    results = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['assignment', 'student'], name='one_test_attempt')]

    @property
    def percentage(self):
        total = len(self.assignment.question_snapshot)
        return round(100 * self.correct_count / total) if total and self.correct_count is not None else None


class ContentItem(models.Model):
    """A course's editable folder tree and the materials inside it."""
    KINDS = [('folder', 'Folder'), ('file', 'File / presentation'), ('video', 'Video'), ('page', 'Page'), ('link', 'Link'), ('test', 'Quiz / test')]
    COLORS = [(color, color.title()) for color in ('blue', 'yellow', 'green', 'purple', 'red', 'gray')]
    AVAILABILITIES = [('published', 'Published'), ('draft', 'Draft'), ('scheduled', 'Scheduled')]
    MAX_DEPTH = 20

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='content_items')
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='children')
    kind = models.CharField(max_length=12, choices=KINDS)
    title = models.CharField(max_length=160)
    description = models.TextField(max_length=10000, blank=True)
    color = models.CharField(max_length=12, choices=COLORS, default='blue')
    availability = models.CharField(max_length=12, choices=AVAILABILITIES, default='published')
    available_from = models.DateTimeField(null=True, blank=True)
    available_until = models.DateTimeField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0)
    lesson_key = models.CharField(max_length=32, blank=True)
    source_key = models.CharField(max_length=160, null=True, blank=True)
    source_path = models.CharField(max_length=500, blank=True)
    file = models.FileField(storage=content_file_storage, upload_to=content_upload_path, blank=True)
    original_name = models.CharField(max_length=255, blank=True)
    url = models.URLField(max_length=2000, blank=True)
    test = models.OneToOneField(TestAssignment, on_delete=models.PROTECT, null=True, blank=True, related_name='content_item')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['position', 'pk']
        constraints = [models.UniqueConstraint(fields=['course', 'source_key'], name='one_imported_content_source')]
        indexes = [models.Index(fields=['course', 'parent', 'position'], name='course_content_order')]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        self.source_key = self.source_key or None
        errors = {}
        depth, seen = 0, {self.pk} if self.pk else set()
        parent = self.parent if self.parent_id else None
        while parent is not None:
            depth += 1
            if parent.pk in seen:
                errors['parent'] = 'A folder cannot be placed inside itself or one of its subfolders.'
                break
            seen.add(parent.pk)
            if parent.course_id != self.course_id or parent.kind != 'folder':
                errors['parent'] = 'Choose a folder in this course.'
                break
            if depth >= self.MAX_DEPTH:
                errors['parent'] = f'Use fewer than {self.MAX_DEPTH} nested folders.'
                break
            parent = parent.parent
        # Moving a folder must also leave enough space for its existing descendants.
        if self.pk and self.kind == 'folder' and 'parent' not in errors:
            frontier, visited, descendant_depth = [self.pk], {self.pk}, 0
            while frontier:
                children = list(type(self).objects.filter(parent_id__in=frontier).values_list('pk', flat=True))
                if not children:
                    break
                if visited.intersection(children):
                    errors['parent'] = 'This folder contains an invalid circular structure.'
                    break
                visited.update(children)
                descendant_depth += 1
                if depth + descendant_depth >= self.MAX_DEPTH:
                    errors['parent'] = f'This move would exceed {self.MAX_DEPTH} folder levels.'
                    break
                frontier = children
        if self.availability == 'scheduled' and not self.available_from:
            errors['available_from'] = 'Choose when this material becomes available.'
        if self.available_from and self.available_until and self.available_until <= self.available_from:
            errors['available_until'] = 'The end must be later than the start.'
        if self.url and (urlsplit(self.url).scheme.lower() not in {'http', 'https'} or not urlsplit(self.url).netloc):
            errors['url'] = 'Use a complete http:// or https:// address.'
        if self.kind == 'link' and not self.url:
            errors['url'] = 'Enter a link.'
        if self.kind == 'video' and bool(self.file) == bool(self.url):
            errors['__all__'] = 'Choose either an uploaded video or a video link.'
        if self.kind == 'video' and self.source_path:
            errors['source_path'] = 'Upload a video file or enter a video link.'
        if self.test_id and (self.test.course_id != self.course_id or self.kind != 'test'):
            errors['test'] = 'Choose a test from this course.'
        if self.source_path:
            source = (settings.SITE_DIR / self.source_path).resolve()
            if not source.is_relative_to((settings.SITE_DIR / 'materials').resolve()):
                errors['source_path'] = 'Choose an existing course material.'
        if errors:
            raise ValidationError(errors)

    def get_absolute_url(self):
        if self.kind == 'folder':
            return reverse('course_workspace', args=[self.course.slug]) + f'#folder-{self.pk}'
        return reverse('content_detail', args=[self.course.slug, self.pk])
