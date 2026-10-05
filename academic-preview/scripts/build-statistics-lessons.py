#!/usr/bin/env python3
"""Build all Statistics class pages from assets/statistics-lessons.json.

Run from any directory with Python 3 (standard library only):
    python3 scripts/build-statistics-lessons.py

The first run extracts the existing 40-class curriculum if the JSON is absent.
Later runs preserve that JSON and regenerate pages and curriculum title links.
Each lesson accepts week, letter, weekTitle, title, description, coverage[],
objectives[] and materials[]. A material accepts role (slides/handout/lesson-plan),
name, optional label, href, format and size. A missing href means unavailable.
All text is escaped. Only http(s) or relative file links are accepted.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "assets/statistics-lessons.json"
ROLES = {"slides": "Presentation", "handout": "Handouts and activities", "lesson-plan": "Lesson plan"}
TUTORIAL_WEEKS = {2, 5, 8, 11}
SHARED_SCRIPT_VERSION = "20261006b"
LESSON_STYLE_VERSION = "20261006a"
WEEK_PATTERN = r'(<details\b[^>]*\bclass="curriculum-week"[^>]*\bid="week-(\d+)"[^>]*>)(.*?)(</details>)'
ARTICLE_PATTERN = r'(<article\b[^>]*\bclass="lesson"[^>]*>)(.*?)(</article>)'


def text(value: object) -> str:
    return html.escape(str(value), quote=True)


def plain(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup)).strip()


def filename(lesson: dict) -> str:
    return f"statistics-week-{int(lesson['week']):02d}-{lesson['letter'].lower()}.html"


def extract_starter(course: str) -> dict:
    lessons = []
    for week in re.finditer(WEEK_PATTERN, course, re.S):
        number = int(week.group(2))
        label = re.search(r"<summary>\s*<span>(.*?)</span>", week.group(3), re.S)
        week_title = plain(label.group(1)).split("·", 1)[-1].strip() if label else f"Week {number}"
        for article in re.finditer(ARTICLE_PATTERN, week.group(3), re.S):
            body = article.group(2)
            letter = plain(re.search(r'<span class="lesson-letter">(.*?)</span>', body, re.S).group(1))
            heading = plain(re.search(r"<h4>(.*?)</h4>", body, re.S).group(1))
            description = plain(re.search(r"<p>(.*?)</p>", body, re.S).group(1))
            lessons.append({"week": number, "letter": letter, "weekTitle": week_title,
                            "title": heading.split("·", 1)[-1].strip(), "description": description,
                            "coverage": [], "objectives": [], "materials": []})
    return {"version": 1, "lessons": lessons}


def validate(data: dict) -> list[dict]:
    if data.get("version") != 1 or not isinstance(data.get("lessons"), list):
        raise ValueError("Expected version: 1 and a lessons array")
    lessons = data["lessons"]
    expected = {(week, letter) for week in range(1, 13)
                for letter in ("ABCD" if week in TUTORIAL_WEEKS else "ABC")}
    actual = [(lesson.get("week"), lesson.get("letter")) for lesson in lessons]
    if set(actual) != expected or len(actual) != len(expected):
        raise ValueError("The data must include each of the 40 scheduled classes exactly once")
    for lesson in lessons:
        for field in ("title", "description"):
            if not isinstance(lesson.get(field), str) or not lesson[field].strip():
                raise ValueError(f"Missing {field}: {lesson['week']}{lesson['letter']}")
        for field in ("coverage", "objectives", "materials"):
            if not isinstance(lesson.get(field, []), list):
                raise ValueError(f"{field} must be an array")
        for item in lesson.get("materials", []):
            if item.get("role") not in ROLES:
                raise ValueError(f"Unknown material role: {item.get('role')}")
            href = item.get("href")
            if href:
                parsed = urlparse(href)
                if parsed.scheme not in ("", "https", "http") or href.startswith("//"):
                    raise ValueError(f"Unsupported material link: {href}")
                if not parsed.scheme and (parsed.path.startswith("/") or ".." in Path(parsed.path).parts):
                    raise ValueError(f"Material link must be relative to this site: {href}")
    return sorted(lessons, key=lambda item: (item["week"], item["letter"]))


def material_html(material: dict) -> str:
    label = material.get("label") or material.get("name") or ROLES[material["role"]]
    href = material.get("href")
    if not href:
        return f'<li class="lesson-material-unavailable"><span>{text(label)}</span><small>Not available yet</small></li>'
    metadata = " · ".join(str(value) for value in (material.get("format"), material.get("size")) if value)
    # Relative assets are served from the same host and can use native downloads.
    attributes = ' download' if not urlparse(href).scheme else ' target="_blank" rel="noopener noreferrer"'
    return (f'<li><a class="lesson-download" href="{text(href)}"{attributes}>'
            f'<span>{text(label)}</span><small>{text(metadata) if metadata else "Download"}</small>'
            '<span class="lesson-download-arrow" aria-hidden="true">↓</span></a></li>')


def downloads_html(lesson: dict) -> str:
    groups = []
    for role, heading in ROLES.items():
        items = [item for item in lesson.get("materials", []) if item["role"] == role]
        content = ("<ul>" + "".join(material_html(item) for item in items) + "</ul>") if items else '<p class="lesson-unavailable">Not available yet.</p>'
        groups.append(f'<section class="lesson-material-group"><h3>{text(heading)}</h3>{content}</section>')
    any_available = any(item.get("href") for item in lesson.get("materials", []))
    introduction = "Download the materials for this class." if any_available else "The class materials will be added here when available."
    return (f'<aside class="lesson-downloads" aria-labelledby="lesson-materials-heading">'
            '<h2 id="lesson-materials-heading">Class materials</h2>'
            f'<p class="lesson-materials-intro">{introduction}</p>{"".join(groups)}</aside>')


def list_html(items: list[str]) -> str:
    return '<ul class="lesson-points">' + ''.join(f'<li>{text(item)}</li>' for item in items) + '</ul>'


def lesson_html(lesson: dict, previous: dict | None, following: dict | None,
                head: str, header: str, footer: str) -> str:
    page_title = f"Week {lesson['week']} · Class {lesson['letter']} · Statistics · Jacob Mlynarski"
    rendered_head = re.sub(r"<title>.*?</title>", f"<title>{text(page_title)}</title>", head, flags=re.S)
    rendered_head = re.sub(r'<meta name="description" content="[^"]*">',
                           f'<meta name="description" content="{text(lesson["description"])}">', rendered_head)
    rendered_header = header.replace('<body>', '<body class="statistics-lesson-page">')
    rendered_header = rendered_header.replace('<a href="courses.html">Courses</a>', '<a href="courses.html" aria-current="page">Courses</a>')
    coverage = list_html(lesson["coverage"]) if lesson.get("coverage") else f'<p>{text(lesson["description"])}</p>'
    objectives = list_html(lesson["objectives"]) if lesson.get("objectives") else '<p class="lesson-pending">Detailed learning objectives will be added with the class materials.</p>'
    nav_items = []
    for item, label, direction in ((previous, "Previous class", "previous"), (following, "Next class", "next")):
        if item:
            nav_items.append(f'<a class="lesson-{direction}" href="{filename(item)}"><small>{label}</small><span>Week {item["week"]} · Class {item["letter"]}</span><strong>{text(item["title"])}</strong></a>')
    navigation = '<nav class="lesson-navigation" aria-label="Class navigation">' + ''.join(nav_items) + '</nav>'
    return f'''{rendered_head}
{rendered_header}
<main id="main">
  <section class="course-banner lesson-banner"><div class="container">
    <p class="breadcrumbs"><a href="index.html">Home</a> / <a href="courses.html">Courses</a> / <a href="statistics.html">Statistics</a> / Week {lesson['week']} · Class {lesson['letter']}</p>
    <p class="eyebrow">Statistics with Project Skills</p>
    <h1>{text(lesson['title'])}</h1>
    <p class="lesson-meta"><span>Week {lesson['week']:02d} · Class {lesson['letter']}</span><span>90 minutes</span><span>{'Tutorial' if lesson['letter'] == 'D' else 'Foundation · Business &amp; Science'}</span></p>
  </div></section>
  <section class="lesson-section"><div class="container">
    <div class="lesson-content-layout"><div class="lesson-content">
      <p class="lesson-week-title">{text(lesson.get('weekTitle', 'Statistics'))}</p>
      <section aria-labelledby="lesson-coverage-heading"><h2 id="lesson-coverage-heading">What this class covers</h2>{coverage}</section>
      <section aria-labelledby="lesson-objectives-heading"><h2 id="lesson-objectives-heading">Learning objectives</h2>{objectives}</section>
      <p class="lesson-return"><a href="statistics.html#week-{lesson['week']}">← Back to Week {lesson['week']} in the course outline</a></p>
    </div>{downloads_html(lesson)}</div>
    {navigation}
  </div></section>
</main>
{footer}
'''


def link_curriculum(course: str, lessons: list[dict]) -> str:
    by_key = {(lesson["week"], lesson["letter"]): lesson for lesson in lessons}
    def replace_week(match: re.Match) -> str:
        week = int(match.group(2))
        def replace_article(article: re.Match) -> str:
            body = article.group(2)
            letter = plain(re.search(r'<span class="lesson-letter">(.*?)</span>', body, re.S).group(1))
            lesson = by_key[(week, letter)]
            heading = f'<h4><a class="lesson-title-link" href="{filename(lesson)}">Class {letter} · {text(lesson["title"])}</a></h4>'
            body = re.sub(r"<h4>.*?</h4>", heading, body, flags=re.S)
            body = re.sub(r"<p>.*?</p>", lambda _: f'<p>{text(lesson["description"])}</p>', body, count=1, flags=re.S)
            return article.group(1) + body + article.group(3)
        return match.group(1) + re.sub(ARTICLE_PATTERN, replace_article, match.group(3), flags=re.S) + match.group(4)
    return re.sub(WEEK_PATTERN, replace_week, course, flags=re.S)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA, help="Lesson JSON (default: assets/statistics-lessons.json)")
    args = parser.parse_args()
    course_path = ROOT / "statistics.html"
    course = course_path.read_text(encoding="utf-8")
    if args.data.exists():
        data = json.loads(args.data.read_text(encoding="utf-8"))
    else:
        data = extract_starter(course)
        args.data.parent.mkdir(parents=True, exist_ok=True)
        args.data.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lessons = validate(data)
    style_tag = f'  <link rel="stylesheet" href="assets/statistics-lessons.css?v={LESSON_STYLE_VERSION}">'
    course = re.sub(r'\s*<link rel="stylesheet" href="assets/statistics-lessons\.css[^\"]*">', '', course)
    course = course.replace('</head>', f'{style_tag}\n</head>')
    course = link_curriculum(course, lessons)
    course = re.sub(r'assets/preview\.js\?v=[^"\s]+', f'assets/preview.js?v={SHARED_SCRIPT_VERSION}', course)
    course_path.write_text(course, encoding="utf-8")
    head = course[:course.index('</head>') + len('</head>')]
    head = re.sub(r'<style>.*?</style>\s*', '', head, flags=re.S)
    header = course[course.index('<body'):course.index('<main')].strip()
    footer = course[course.index('<footer'):].strip()
    for index, lesson in enumerate(lessons):
        previous = lessons[index - 1] if index else None
        following = lessons[index + 1] if index + 1 < len(lessons) else None
        (ROOT / filename(lesson)).write_text(lesson_html(lesson, previous, following, head, header, footer), encoding="utf-8")
    originals = ('index.html', 'courses.html', 'statistics.html', 'statistics-practice.html',
                 'corporate-finance.html', 'project-management.html', 'publications.html', 'about-me.html')
    for name in originals:
        path = ROOT / name
        content = path.read_text(encoding="utf-8")
        content = re.sub(r'assets/preview\.js\?v=[^"\s]+', f'assets/preview.js?v={SHARED_SCRIPT_VERSION}', content)
        path.write_text(content, encoding="utf-8")
    print(f"Built {len(lessons)} class pages and linked all curriculum titles. Data: {args.data}")


if __name__ == '__main__':
    main()
