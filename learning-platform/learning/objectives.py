"""Learning evidence kept separate from grades and activity completion."""
import re
from functools import lru_cache
from html.parser import HTMLParser
from urllib.parse import urlencode
from django.conf import settings
from .models import PracticeResult, TestAttempt
from .scoring import bank, score


def question_objectives(question):
    return set(filter(None, [question.get('primaryObjective')])) | {ident for field in question.get('fields', []) for ident in field.get('objectiveIds', [])}


class PublishedObjectives(HTMLParser):
    """Read the existing class objectives, without inventing course content."""
    def __init__(self):
        super().__init__()
        self.items = []
        self.current = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        ident = dict(attrs).get('id', '')
        if tag == 'li' and re.fullmatch(r'objective-\d+-\d+', ident):
            self.current = ident
            self.parts = []

    def handle_data(self, data):
        if self.current:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'li' and self.current:
            ident = self.current.removeprefix('objective-').replace('-', '.')
            text = ' '.join(' '.join(self.parts).split())
            self.items.append({'id': ident, 'label': text.removeprefix(ident).strip(), 'anchor': self.current})
            self.current = None


@lru_cache(maxsize=1)
def finance_objectives():
    items = []
    for week in range(1, 17):
        path = settings.SITE_DIR / f'corporate-finance-week-{week:02}.html'
        if not path.is_file():
            continue
        parser = PublishedObjectives()
        parser.feed(path.read_text(encoding='utf8'))
        items.extend({**item, 'week': week, 'class': f'Class {week:02}',
                      'lesson_url': f'/courses/corporate-finance/classes/{week}-main/#{item["anchor"]}'} for item in parser.items)
    return items


def objective_evidence(student, courses):
    courses = list(courses)
    course_by_id = {c.pk: c for c in courses}
    rows = {}
    catalogs = {'statistics': {o['id']: o for o in bank()['objectives']},
                'corporate-finance': {o['id']: o for o in finance_objectives()}}
    available = {ident for q in bank()['questions'] for ident in question_objectives(q)}

    def row_for(course_id, ident):
        key = (course_id, ident)
        if key not in rows:
            slug = course_by_id[course_id].slug
            objective = catalogs.get(slug, {}).get(ident, {})
            row = {'id': ident, 'course': course_by_id[course_id], 'label': objective.get('label', ident),
                   'week': objective.get('week'), 'class': objective.get('class', ''), 'attempted': 0,
                   'independent': 0, 'assisted': 0, 'latest': 0, 'tested': 0, 'test_correct': 0, 'questions': set()}
            match = re.fullmatch(r'(\d+)([A-Z])\.(\d+)', ident)
            if objective.get('lesson_url'):
                row['lesson_url'] = objective['lesson_url']
            elif objective and match and slug == 'statistics':
                row['lesson_url'] = f'/courses/statistics/classes/{int(match[1])}-{match[2].lower()}/#objective-{match[1]}{match[2].lower()}-{match[3]}'
            if objective and ident in available and slug == 'statistics':
                row['practice_url'] = '/courses/statistics/practice/?' + urlencode({'objective': ident})
            rows[key] = row
        return rows[key]

    for course in courses:
        for ident in catalogs.get(course.slug, {}):
            row_for(course.pk, ident)
    for result in PracticeResult.objects.filter(student=student, course__in=courses).only('course_id', 'objective_ids', 'question_id', 'first_correct', 'first_assisted', 'latest_correct'):
        for ident in set(result.objective_ids):
            row = row_for(result.course_id, ident)
            row['attempted'] += 1
            row['independent'] += int(result.first_correct and not result.first_assisted)
            row['assisted'] += int(result.first_correct and result.first_assisted)
            row['latest'] += int(result.latest_correct)
            row['questions'].add(result.question_id)
    for attempt in TestAttempt.objects.filter(student=student, assignment__course__in=courses, submitted_at__isnull=False).select_related('assignment').only('answers', 'assignment__course_id', 'assignment__question_snapshot'):
        for question in attempt.assignment.question_snapshot:
            answers = attempt.answers.get(question.get('id'), {})
            if not isinstance(answers, dict):
                continue
            for ident in question_objectives(question):
                fields = question.get('fields', []) if ident == question.get('primaryObjective') else [f for f in question.get('fields', []) if ident in f.get('objectiveIds', [])]
                if not fields:
                    continue
                valid, correct = score({'fields': fields}, answers)
                if valid:
                    row = row_for(attempt.assignment.course_id, ident)
                    row['tested'] += 1
                    row['test_correct'] += int(correct)
                    row['questions'].add(question['id'])
    for row in rows.values():
        total = row['attempted'] + row['tested']
        correct = row['independent'] + row['test_correct']
        row['evidence_count'] = total
        row['unique_questions'] = len(row.pop('questions'))
        row['percentage'] = 100 * correct / total if total else None
        row['needs_review'] = bool(total and correct < total)
        row['status'] = 'Not yet practised' if not total else 'Practise next' if row['needs_review'] else 'Consistent results' if row['unique_questions'] >= 3 else 'Building evidence'
    ordered = sorted(rows.values(), key=lambda r: (r['course'].title, r['week'] or 99, r['class'], int(r['id'].split('.')[-1]) if r['id'].split('.')[-1].isdigit() else 0, r['id']))
    recommendations = sorted((r for r in ordered if r['needs_review'] and r.get('practice_url')), key=lambda r: (r['percentage'], -r['evidence_count']))[:4]
    if len(recommendations) < 4:
        recommendations += [r for r in ordered if not r['evidence_count'] and r.get('practice_url')][:4 - len(recommendations)]
    return ordered, recommendations
