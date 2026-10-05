# Academic static preview

A small static personal teaching website for Jacob Mlynarski, adapted from the purchased WP-Academic 2.4.3 theme.

The theme's supplied CSS and Bootstrap CSS are used with static HTML and a small client navigation script. This is an adaptation of the public layouts rather than a WordPress or Elementor export. WordPress, PHP, Tutor LMS, accounts, checkout and database features are not present.

## Pages

- `index.html`: homepage with links to courses, publications and the professional profile.
- `statistics.html`: Statistics course details: 12 weeks, 36 A/B/C classes and four Class D tutorials in Weeks 2, 5, 8 and 11; 40 classes of 90 minutes, totalling 60 contact hours.
- `courses.html`: course selection.
- `publications.html`: four publications, full abstracts, dated journal metrics and BibTeX.
- `about-me.html`: professional profile, CV portrait, education, professional qualifications and six appointments.
- `statistics-practice.html`: interactive Weeks 1–4 prototype with one fixed example per question type, topic selection, mixed practice, answer checking, hints, worked solutions and session results.
- `corporate-finance.html`: Corporate Finance overview.
- `project-management.html`: Project Management topics.

All site assets are hosted locally. The header uses a trial Eurasia text wordmark. Internal navigation replaces the main content while retaining the header, updates the URL and supports browser Back/Forward. Subtle content fades use the Web Animations API with reduced-motion support; the navigation remains interactive throughout. Individual HTML URLs also work when opened directly or with JavaScript disabled. The Statistics guide link has been removed.

## Publishing

These files live in `academic-preview/` inside the `MrBytor/projects` repository. GitHub Pages publishes the repository's `main` branch. The expected site URL is `https://mrbytor.github.io/projects/academic-preview/`.

## Editing

Edit the HTML files for text, `assets/preview.css` for custom layout, and `assets/preview.js` for navigation. No build step is required. Theme assets remain subject to the purchased theme's applicable licence; this repository is not a theme redistribution package.

Local fonts are Karla and Montserrat, distributed under the SIL Open Font License. Their licence files are in `assets/fonts/`.

## Photo credits

Photos used under the [Unsplash License](https://unsplash.com/license): [Zoshua Colah — library](https://unsplash.com/photos/Of-W1y-rLoQ), [Carlos Muza — statistics](https://unsplash.com/photos/hpjSkU2UYSU), and [Kelly Sikkema — finance](https://unsplash.com/photos/_1QHMYHNeN0).

Publication metadata comes from supplied CV context and public publisher/university records. The Sustainability paper is indexed under the publisher’s 2023 volume (published online in 2022). No example-template publications are attributed to Jacob.

## Publication and contact updates

All four abstract panels contain the original full abstracts from publisher or author-provided versions. Publisher, DOI (where assigned), Abstract and BibTeX controls share one row; expandable text appears below. Panel toggles and citation copying use delegated events so they continue to work after client navigation.

The current Springer citation for “Outsiders within” records publication on 13 August 2026, but does not yet assign volume, issue or pages; these are deliberately omitted from the displayed citation and BibTeX. Higher Education Forum volume 23, pages 183–208 includes DOI `10.15027/0002041831`.

Journal impact factors are taken from the publisher’s 2025 figures. SJR quartiles for Higher Education and Higher Education Forum are reproduced by Research Journal Rank and cross-checked against other journal records. Sustainability’s JCR and Scopus CiteScore classifications come from MDPI. Each journal uses one subdued line for impact factor (where verified), one quartile and Scopus indexing. The year stays visible; the classification category is available in a tooltip. The metric labels link directly to their publisher or quartile source; no separate source disclosure is shown. The additional Sustainability CiteScore classification is omitted from the publication listing. A JCR impact factor is not supplied for Higher Education Forum because no official value was verified; journal indicators do not apply to the book chapter.

The About Me introduction uses the first person. Contact information follows the supplied CV. LinkedIn `jacobmlynarski` and ResearchGate `Jacob-Mlynarski-3` match the name, university and published work. The social SVG glyphs come from [Simple Icons](https://github.com/simple-icons/simple-icons), distributed under CC0; brand rights remain with their respective owners.

The About Me sidebar presents Email and its address on one row, followed by Phone and its number on a second row. Its portrait retains its original size, and the profile container is slightly wider so the sidebar sits farther left. The labels and values stay aligned in two columns on smaller screens; long email addresses can wrap within the value column.

## Statistics practice prototype

The reviewed examples live in `assets/statistics-question-bank.json`. These are fixed questions for content and usability feedback; repeated practice currently reuses the examples rather than generating new numbers. The interface and answer checking are implemented in `assets/statistics-practice.js`, with pure marking and selection helpers in `assets/statistics-practice-core.mjs`. Run the automated checks with `node --test tests/statistics-practice.test.mjs`.

The shared navigation script initializes practice on direct loads and after client navigation. Session answers remain in memory while navigating within the site; refreshing the page resets the prototype. No student accounts, external service, AI API or persistent progress database is used. Each question specifies its rounding and method, and worked solutions can be revealed on demand.

## Statistics lesson pages

The 40 class pages use assets/statistics-lessons.json and scripts/build-statistics-lessons.py. Run the generator after content changes. Weeks 1–4 have summaries and objectives based on the available teaching materials. The first release includes PDF handouts and the Week 4C student workbook. PowerPoint uploads and individual lesson-plan downloads remain pending. Week 2C’s inconsistent handout is withheld; Week 4A/B worksheets are marked as earlier versions. Week 2D has no source files yet.
