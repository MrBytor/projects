# IFY Statistics with Project Skills

A self-contained course website with expandable topics for all 24 teaching weeks:

- Semester 1: Statistics (Weeks 1–12).
- Semester 2: Project Skills (Weeks 13–24).

## GitHub Pages

The website is ready to be hosted entirely by GitHub Pages, with no ChatGPT connection, account or runtime dependency.

One-time repository setup:

1. Open [Settings → Pages](https://github.com/MrBytor/projects/settings/pages).
2. Under **Build and deployment**, select **Deploy from a branch**.
3. Choose the **main** branch and **/(root)** folder, then select **Save**.
4. Wait for the Pages deployment to finish.

Once enabled, the website will be available at:

- https://mrbytor.github.io/projects/ — opens the course guide.
- https://mrbytor.github.io/projects/ify-statistics-course/ — direct course link.

The root `index.html` redirects to this course folder. The root `.nojekyll` file tells GitHub Pages to publish the static files directly. Future commits to the publishing branch update the GitHub Pages site.

## Open locally

Open this folder's `index.html` in a browser. All styles and the favicon are included in the file. No installation or build step is required.

## Edit the course

Edit the weekly `<details>` sections in `index.html`. The embedded `<style>` block controls the appearance and mobile layout.

The outline is based on the supplied IFY Semester 1 and Semester 2 teaching materials. Weekly content may be adapted in class.
