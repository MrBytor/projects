"""Teacher material forms. Descriptions are plain text, escaped by templates."""
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from django import forms
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db.models import Q
from .models import ContentItem, TestAssignment
from .video import valid_video_container


MAX_UPLOAD_SIZE = 50 * 1024 * 1024
MAX_VIDEO_UPLOAD_SIZE = 100 * 1024 * 1024
VIDEO_EXTENSIONS = {'.mp4', '.webm'}
ALLOWED_EXTENSIONS = {'.pptx', '.pdf', '.docx', '.xlsx', '.png', '.jpg', '.jpeg'}


def validate_video_upload(upload):
    extension = Path(upload.name).suffix.lower()
    if extension not in VIDEO_EXTENSIONS:
        raise forms.ValidationError('Choose an MP4 or WebM video.')
    if upload.size > MAX_VIDEO_UPLOAD_SIZE:
        raise forms.ValidationError('Videos must be 100 MB or smaller.')
    if not upload.size:
        raise forms.ValidationError('This video is empty.')
    try:
        upload.seek(0)
        if not valid_video_container(upload, extension):
            raise forms.ValidationError('The contents do not match a valid MP4 or WebM video.')
    except (OSError, ValueError, OverflowError):
        raise forms.ValidationError('This video could not be read. Choose a valid MP4 or WebM file.')
    finally:
        upload.seek(0)
    return upload


def validate_material_upload(upload):
    extension = Path(upload.name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise forms.ValidationError('Choose a PPTX, PDF, DOCX, XLSX, PNG, or JPG file.')
    if upload.size > MAX_UPLOAD_SIZE:
        raise forms.ValidationError('Files must be 50 MB or smaller.')
    if not upload.size:
        raise forms.ValidationError('This file is empty.')
    try:
        upload.seek(0)
        header = upload.read(16)
        if extension == '.pdf':
            valid = header.startswith(b'%PDF-')
        elif extension == '.png':
            valid = header.startswith(b'\x89PNG\r\n\x1a\n')
        elif extension in {'.jpg', '.jpeg'}:
            valid = header.startswith(b'\xff\xd8\xff')
        else:
            required = {'.pptx': 'ppt/presentation.xml', '.docx': 'word/document.xml', '.xlsx': 'xl/workbook.xml'}[extension]
            with ZipFile(upload) as package:
                entries = package.infolist()
                names = {entry.filename for entry in entries}
                valid = ('[Content_Types].xml' in names and required in names
                         and len(entries) <= 10000
                         and sum(entry.file_size for entry in entries) <= 500 * 1024 * 1024
                         and not any('vbaproject' in name.lower() or name.startswith('/') or '..' in Path(name).parts for name in names))
        if not valid:
            raise forms.ValidationError('The contents do not match this file type, or the file contains unsupported macros.')
    except (BadZipFile, OSError, ValueError):
        raise forms.ValidationError('This file could not be read. Choose a valid file of the indicated type.')
    finally:
        upload.seek(0)
    return upload


class ContentItemForm(forms.ModelForm):
    class Meta:
        model = ContentItem
        fields = ['title', 'description', 'color', 'file', 'url', 'test', 'availability', 'available_from', 'available_until']
        labels = {'description': 'Description', 'file': 'Choose file', 'url': 'Web address', 'test': 'Existing quiz / test',
                  'available_from': 'Available from', 'available_until': 'Available until'}
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'available_from': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'available_until': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'file': forms.FileInput(attrs={'accept': ','.join(sorted(ALLOWED_EXTENSIONS))}),
        }

    def __init__(self, *args, course, kind, parent=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.course = course
        self.instance.kind = kind
        self.instance.parent = parent
        specific = {'folder': {'color'}, 'file': {'file'}, 'video': {'file', 'url'}, 'link': {'url'}, 'page': set(), 'test': {'test'}}
        if kind not in specific:
            raise ValueError('Unsupported material type.')
        for name in {'color', 'file', 'url', 'test'} - specific[kind]:
            del self.fields[name]
        if kind == 'file':
            self.fields['file'].required = not (self.instance.file or self.instance.source_path)
            self.fields['file'].help_text = 'PPTX, PDF, DOCX, XLSX, PNG, or JPG · up to 50 MB.'
        if kind == 'link':
            self.fields['url'].required = True
        if kind == 'video':
            self.fields['video_source'] = forms.ChoiceField(
                label='Video source', choices=[('upload', 'Upload video'), ('link', 'Video link')],
                widget=forms.RadioSelect, initial='link' if self.instance.url else 'upload')
            self.fields['file'].required = False
            self.fields['file'].label = 'Choose video'
            self.fields['file'].widget.attrs['accept'] = 'video/mp4,video/webm,.mp4,.webm'
            self.fields['file'].help_text = 'MP4 or WebM, up to 100 MB per video. MP4 with H.264 video and AAC audio is recommended.'
            self.fields['url'].required = False
            self.fields['url'].label = 'Video link'
            self.fields['url'].help_text = 'YouTube, Vimeo, or a direct MP4 / WebM link. Other websites open using their original link.'
            self.order_fields(['title', 'description', 'video_source', 'file', 'url', 'availability', 'available_from', 'available_until'])
        if kind == 'page':
            self.fields['description'].label = 'Page content'
            self.fields['description'].required = True
            self.fields['description'].widget.attrs['rows'] = 10
        if kind == 'test':
            self.fields['test'].queryset = TestAssignment.objects.filter(course=course).filter(Q(content_item__isnull=True) | Q(content_item=self.instance.pk))
            self.fields['test'].required = False
            self.fields['test'].help_text = 'Choose an existing test, or select bank questions below.'
        self.fields['available_from'].help_text = 'Local course time (China, UTC+8). Required for scheduled materials.'
        self.fields['available_until'].help_text = 'Optional. Students cannot open the material after this time.'

    def clean_file(self):
        upload = self.cleaned_data.get('file')
        # ModelForm returns the existing FieldFile when no replacement was uploaded.
        if upload and 'file' in self.files:
            if self.instance.kind == 'video':
                validate_video_upload(upload)
            else:
                validate_material_upload(upload)
        return upload

    def clean(self):
        cleaned = super().clean()
        if self.instance.kind != 'video':
            return cleaned
        source = cleaned.get('video_source')
        if source == 'upload':
            if not cleaned.get('file') and 'file' not in self.errors:
                self.add_error('file', 'Choose an MP4 or WebM video.')
            cleaned['url'] = ''
        elif source == 'link':
            if not cleaned.get('url') and 'url' not in self.errors:
                self.add_error('url', 'Enter a video link.')
            if 'file' in self.files:
                self.add_error('file', 'Choose Upload video to use this file, or remove it to use a link.')
            cleaned['file'] = None
            self.instance.file = ''
            self.instance.original_name = ''
        self.instance.source_path = ''
        return cleaned

    def _update_errors(self, errors):
        # Parent/course are supplied by the workspace URL rather than visible
        # form controls. Model-level errors still belong inside the dialog.
        if hasattr(errors, 'error_dict'):
            mapped = {}
            for name, messages in errors.error_dict.items():
                target = name if name in self.fields else NON_FIELD_ERRORS
                mapped.setdefault(target, []).extend(messages)
            errors = ValidationError(mapped)
        super()._update_errors(errors)

    def clean_url(self):
        value = self.cleaned_data.get('url', '')
        if value and not value.lower().startswith(('http://', 'https://')):
            raise forms.ValidationError('Use a complete http:// or https:// address.')
        return value

    def save(self, commit=True):
        item = super().save(commit=False)
        if self.cleaned_data.get('file') and 'file' in self.files:
            item.original_name = Path(self.cleaned_data['file'].name).name
            item.source_path = ''
        if item.kind == 'video' and self.cleaned_data.get('video_source') == 'link':
            item.file = ''
            item.original_name = ''
        if commit:
            item.save()
        return item
