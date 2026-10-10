"""Server-side practice checking. These are formative attempts, not exam grades."""
import json
import math
import re
from functools import lru_cache
from django.conf import settings


@lru_cache(maxsize=1)
def bank():
    return json.loads((settings.SITE_DIR / 'assets/statistics-question-bank.json').read_text(encoding='utf8'))


@lru_cache(maxsize=1)
def questions():
    return {q['id']: q for q in bank()['questions']}


def number(raw, allow_percent=False):
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if raw.endswith('%'):
        if not allow_percent:
            return None
        raw = raw[:-1].strip()
    parts = raw.split('/')
    pattern = r'[+-]?(?:(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d*)?|\.\d+)'
    if len(parts) > 2 or any(not re.fullmatch(pattern, p.strip(), re.ASCII) for p in parts):
        return None
    values = [float(p.strip().replace(',', '')) for p in parts]
    if not all(math.isfinite(v) for v in values) or (len(values) == 2 and values[1] == 0):
        return None
    result = values[0] if len(values) == 1 else values[0] / values[1]
    return result if math.isfinite(result) else None


def score(question, answers):
    valid, correct = True, True
    for field in question['fields']:
        raw = answers.get(field['id'], '')
        if not isinstance(raw, str) or len(raw) > 200:
            return False, False
        if field['kind'] == 'choice':
            ok = any(option['value'] == raw for option in field['options'])
            match = ok and raw == field['answer']
        else:
            value = number(raw, field.get('allowPercent', False))
            ok = value is not None
            tolerance = 0 if field.get('exact') else 0.5 * 10 ** -field.get('decimals', 0)
            expected = field['answer']
            epsilon = 2.220446049250313e-16 * max(1, abs(value or 0), abs(expected)) * 8
            match = ok and (not field.get('integer') or value.is_integer()) and abs(value - expected) <= tolerance + epsilon
        valid = valid and ok
        correct = correct and match
    return valid, correct
