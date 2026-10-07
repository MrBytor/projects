"""Render the Week 2 pilot using the existing lesson content and site shell."""

import html
import re


PILOT_WEEK = 2
PILOT_CLASSES = "ABC"


def text(value):
    return html.escape(str(value), quote=True)


def is_weekly(lesson):
    return lesson["week"] == PILOT_WEEK and lesson["letter"] in PILOT_CLASSES


def lesson_url(lesson):
    if is_weekly(lesson):
        return f"statistics-week-02.html#class-{lesson['letter'].lower()}"
    return f"statistics-week-{lesson['week']:02d}-{lesson['letter'].lower()}.html"


def redirect_html(lesson):
    target = lesson_url(lesson)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Week 2 · Class {lesson['letter']} · Statistics</title>
<meta http-equiv="refresh" content="0; url={target}">
<link rel="canonical" href="statistics-week-02.html">
</head><body><main><p>Class {lesson['letter']} is now included on the Week 2 page.</p>
<p><a href="{target}">Open Week 2 · Class {lesson['letter']}</a></p></main></body></html>
'''


def resource(item, title, context):
    if not item or not item.get("href"):
        status = item.get("label", "Not available yet") if item else "Not available yet"
        return f'<div class="week-download week-download-pending"><span>{text(title)}</span><small>{text(status)}</small></div>'
    details = " · ".join(str(item[key]) for key in ("format", "size") if item.get(key))
    return (f'<a class="week-download" href="{text(item["href"])}" download '
            f'aria-label="Download {text(context)} {text(title)}">'
            f'<span>{text(title)}</span><small>{text(details)}</small>'
            '<span class="week-download-arrow" aria-hidden="true">↓</span></a>')


def render_week(lessons, weekly, head, header, footer):
    classes = [lesson for lesson in lessons if is_weekly(lesson)]
    title = classes[0]["weekTitle"]
    description = weekly["description"]
    rendered_head = re.sub(r"<title>.*?</title>",
        f"<title>Week 2 · {text(title)} · Statistics · Jacob Mlynarski</title>", head, flags=re.S)
    rendered_head = re.sub(r'<meta name="description" content="[^"]*">',
        f'<meta name="description" content="{text(description)}">', rendered_head)
    rendered_head = rendered_head.replace("</head>",
        '  <link rel="stylesheet" href="assets/statistics-week.css?v=20261007a">\n</head>')
    rendered_header = header.replace('<body>', '<body class="statistics-week-page">')
    rendered_header = rendered_header.replace('<a href="courses.html">Courses</a>',
        '<a href="courses.html" aria-current="page">Courses</a>')
    sections, objective_groups = [], []
    for lesson in classes:
        letter = lesson["letter"]
        anchor = f'class-{letter.lower()}'
        materials = []
        for role, label in (("slides", "PowerPoint"), ("handout", "Handout")):
            item = next((m for m in lesson["materials"] if m["role"] == role), None)
            materials.append(resource(item, label, f"Week 2 Class {letter}"))
        coverage = ''.join(f'<li>{text(point)}</li>' for point in lesson["coverage"])
        sections.append(f'''<section class="week-class" id="{anchor}" aria-labelledby="{anchor}-heading">
  <div class="week-class-heading"><div><p class="week-kicker">Class {letter} <span>90 minutes</span></p>
    <h2 id="{anchor}-heading">{text(lesson['title'])}</h2></div>
    <a class="week-objectives-link" href="#objectives-{letter.lower()}">Learning objectives <span aria-hidden="true">↓</span></a></div>
  <div class="week-class-layout"><div class="week-class-copy">
    <p class="week-class-description">{text(lesson['description'])}</p>
    <h3>What this class covers</h3><ul class="week-coverage">{coverage}</ul>
  </div><aside class="week-class-materials" aria-labelledby="{anchor}-materials">
    <h3 id="{anchor}-materials">Class {letter} materials</h3>{''.join(materials)}
    <p>Use the weekly vocabulary sheet alongside this class.</p>
  </aside></div>
</section>''')
        items = ''.join(f'<li id="objective-2{letter.lower()}-{i}"><span class="week-objective-code">2{letter}.{i}</span><span>{text(point)}</span></li>'
            for i, point in enumerate(lesson["objectives"], 1))
        objective_groups.append(f'''<section class="week-objective-group" id="objectives-{letter.lower()}" aria-labelledby="objectives-{letter.lower()}-heading">
  <div><h3 id="objectives-{letter.lower()}-heading">Class {letter}</h3><p>{text(lesson['title'])}</p><a href="#{anchor}">Back to class <span aria-hidden="true">↑</span></a></div>
  <ol class="week-objectives-list">{items}</ol></section>''')
    glossary = resource(weekly["vocabulary"], "Vocabulary & terms", "Week 2")
    return f'''{rendered_head}
{rendered_header}
<main id="main">
  <section class="course-banner lesson-banner week-banner"><div class="container">
    <p class="breadcrumbs"><a href="index.html">Home</a> / <a href="courses.html">Courses</a> / <a href="statistics.html">Statistics</a> / Week 2</p>
    <p class="eyebrow">Statistics with Project Skills · Week 02</p>
    <h1>{text(title)}</h1>
    <p class="week-overview">{text(description)}</p>
    <p class="lesson-meta"><span>Classes A, B &amp; C</span><span>90 minutes per class</span><span>Foundation · Business &amp; Science</span></p>
  </div></section>
  <nav class="week-jump-nav" aria-label="Week 2 sections"><div class="container">
    <span class="week-jump-label">Jump to</span><a href="#class-a">Class A</a><a href="#class-b">Class B</a><a href="#class-c">Class C</a><a href="#learning-objectives">Learning objectives</a>
    <a class="week-outline-link" href="statistics.html#week-2">All weeks <span aria-hidden="true">↗</span></a>
  </div></nav>
  <div class="container week-body">
    <section class="week-shared-resource" aria-labelledby="week-vocabulary-heading">
      <div><p class="week-kicker">For the whole week</p><h2 id="week-vocabulary-heading">One reference for all three classes</h2>
      <p>Key terms, sampling methods and formulas, with examples. Keep this two-page sheet with your class handouts.</p></div>
      {glossary}
    </section>
    {''.join(sections)}
    <section class="week-objectives" id="learning-objectives" aria-labelledby="week-objectives-heading">
      <p class="week-kicker">Learning objectives</p><h2 id="week-objectives-heading">What you should be able to do</h2>
      <p class="week-objectives-intro">Use these objectives to check your understanding after each class. For example, <strong>2B.1</strong> means Week 2, Class B, objective 1.</p>
      {''.join(objective_groups)}
    </section>
    <p class="week-tutorial">Also this week: <a href="statistics-week-02-d.html">Class D · Tutorial: review, repair and prepare <span aria-hidden="true">→</span></a></p>
    <nav class="lesson-navigation" aria-label="Week navigation">
      <a class="lesson-previous" href="statistics.html#week-1"><small>Previous week</small><span>Week 1</span><strong>Mathematical foundations</strong></a>
      <a class="lesson-next" href="statistics.html#week-3"><small>Next week</small><span>Week 3</span><strong>Descriptive statistics</strong></a>
    </nav>
  </div>
</main>
{footer}
'''
