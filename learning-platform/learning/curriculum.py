"""The published course outlines remain the source of lesson content."""
import hashlib
import json
import re
from functools import lru_cache
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
from django.conf import settings
from django.urls import reverse
from .scoring import bank


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def find(self, tag=None, css=None, ident=None):
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (css is None or css in child.attrs.get('class', '').split()) and (ident is None or child.attrs.get('id') == ident):
                    yield child
                yield from child.find(tag, css, ident)

    def text(self):
        return ' '.join(' '.join(c.text() if isinstance(c, Node) else c for c in self.children).split())


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def first_text(node, tag=None, css=None):
    item = next(node.find(tag, css), None)
    return item.text() if item else ''


def trusted_material(href):
    url = urlsplit(href)
    if url.scheme or url.netloc:
        return None
    relative = unquote(url.path)
    target = (settings.SITE_DIR / relative).resolve()
    root = (settings.SITE_DIR / 'materials').resolve()
    if not target.is_relative_to(root) or not target.is_file() or target.suffix.lower() not in {'.pptx', '.pdf', '.xlsx', '.docx'}:
        return None
    return {'path': relative, 'name': target.name, 'kind': target.suffix[1:].upper()}


@lru_cache(maxsize=8)
def outline(slug):
    if slug not in {'statistics', 'corporate-finance', 'project-management'}:
        return []
    path = settings.SITE_DIR / f'{slug}.html'
    doc = Document(path.read_text(encoding='utf8')).root
    modules = []
    for index, group in enumerate(doc.find('details', 'curriculum-week'), 1):
        summary = next(group.find('summary'), None)
        title = first_text(summary, 'span') if summary else f'Module {index}'
        title = re.sub(r'^Week\s+0*(\d+)', r'Module \1', title)
        module = {'title': title, 'number': index, 'lessons': []}
        for article in group.find('article', 'lesson'):
            label = first_text(article, 'span', 'lesson-letter')
            link = next(article.find('a', 'lesson-title-link'), None)
            href = link.attrs.get('href', '') if link else ''
            match = re.search(r'-week-(\d+)', href)
            week = int(match[1]) if match else int(label) if label.isdigit() else index
            letter = label.lower() if slug == 'statistics' else 'main'
            key = f'{week}-{letter}'
            lesson = {'key': key, 'week': week, 'letter': letter, 'label': f'Class {week}{label}' if slug == 'statistics' else f'Class {week:02}',
                      'title': first_text(article, 'h4').split(' · ', 1)[-1], 'description': first_text(article, 'p'),
                      'duration': first_text(article, 'span', 'lesson-time'), 'materials': [], 'objectives': [], 'coverage': [],
                      'module': title, 'url': reverse('course_lesson', args=[slug, key])}
            if href:
                source = settings.SITE_DIR / urlsplit(href).path
                if source.is_file() and source.parent == settings.SITE_DIR:
                    page = Document(source.read_text(encoding='utf8')).root
                    section = next(page.find('section', 'week-class', f'class-{letter}' if slug == 'statistics' else 'class-content'), None)
                    if section:
                        lesson['title'] = first_text(section, 'h2') or lesson['title']
                        lesson['description'] = first_text(section, 'p', 'week-class-description') or lesson['description']
                        coverage = next(section.find('ul', 'week-coverage'), None)
                        lesson['coverage'] = [li.text() for li in coverage.find('li')] if coverage else []
                        for a in section.find('a', 'week-download'):
                            material = trusted_material(a.attrs.get('href', ''))
                            if material:
                                material['label'] = first_text(a, 'span') or material['kind']
                                material['index'] = len(lesson['materials'])
                                material['url'] = reverse('lesson_material', args=[slug, key, material['index']])
                                lesson['materials'].append(material)
                    # Shared vocabulary belongs to every class in that week.
                    for shared in page.find('section', 'week-shared-resource'):
                        for a in shared.find('a', 'week-download'):
                            material = trusted_material(a.attrs.get('href', ''))
                            if material and not any(m['path'] == material['path'] for m in lesson['materials']):
                                material.update(label=first_text(a, 'span') or material['kind'], index=len(lesson['materials']))
                                material['url'] = reverse('lesson_material', args=[slug, key, material['index']])
                                lesson['materials'].append(material)
                    objectives = next(page.find('section', 'week-objective-group', f'objectives-{letter}'), None) if slug == 'statistics' else next(page.find('section', 'week-objective-group'), None)
                    if objectives:
                        for item in objectives.find('li'):
                            code = first_text(item, 'span', 'week-objective-code')
                            lesson['objectives'].append({'id': code, 'anchor': item.attrs.get('id', ''), 'label': item.text().removeprefix(code).strip()})
            module['lessons'].append(lesson)
        modules.append(module)
    return modules


def get_lesson(slug, key):
    return next((lesson for module in outline(slug) for lesson in module['lessons'] if lesson['key'] == key), None)


def quick_questions(slug, lesson):
    if slug != 'statistics':
        return []
    prefix = f"{lesson['week']}{lesson['letter'].upper()}."
    candidates = [q for q in bank()['questions'] if q.get('primaryObjective', '').startswith(prefix)]
    # One existing question per objective first, then fill to four. No fabricated tests.
    chosen, seen = [], set()
    for question in candidates:
        if question['primaryObjective'] not in seen:
            chosen.append(question)
            seen.add(question['primaryObjective'])
        if len(chosen) == 4:
            break
    chosen += [q for q in candidates if q not in chosen][:4 - len(chosen)]
    return chosen


@lru_cache(maxsize=64)
def cached_fingerprint(path, modified, size):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def material_fingerprint(material):
    path = settings.SITE_DIR / material['path']
    stat = path.stat()
    return cached_fingerprint(path, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=64)
def cached_preview(folder, modified, size):
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf8'))
    count = manifest['count']
    if manifest.get('fingerprint') != folder.name or type(count) is not int or not 1 <= count <= 1000 or any(not (folder / f'Slide{i}.PNG').is_file() for i in range(1, count + 1)):
        return None
    return {'fingerprint': folder.name, 'count': count, 'folder': folder}


def presentation_preview(material):
    folder = settings.DATA_DIR / 'slide-previews' / material_fingerprint(material)
    try:
        stat = (folder / 'manifest.json').stat()
        return cached_preview(folder, stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError, KeyError, TypeError):
        return None
