# Academic static preview

A small static personal teaching website for Jacob Mlynarski, adapted from the purchased WP-Academic 2.4.3 theme.

The theme's supplied CSS and Bootstrap CSS are used with static HTML and a small client navigation script. This is an adaptation of the public layouts rather than a WordPress or Elementor export. WordPress, PHP, Tutor LMS, accounts, checkout and database features are not present.

## Pages

- `index.html`: homepage with links to courses, publications and the professional profile.
- `statistics.html`: Statistics course details, 12 weeks and 36 A/B/C classes.
- `courses.html`: course selection.
- `publications.html`: four publications, research summaries and BibTeX.
- `about-me.html`: professional profile, CV portrait, education, professional qualifications and six appointments.
- `statistics-practice.html`: exam-practice holding page; the question generator is not implemented yet.
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
