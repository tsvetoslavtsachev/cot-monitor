# GitHub Pages Setup

## Fastest publishing path

If you already have an existing static dashboard file such as `cot-positioning-dashboard.html`, the fastest path is:

1. Rename it to `index.html` or place it under `/docs/index.html`.
2. Commit the repository.
3. In GitHub repo settings, enable **GitHub Pages**.
4. Choose the branch/folder that contains the static site.
5. Confirm that the dashboard can fetch `data/manifest.json` and the market files.

## Recommended transition path

### Phase 1
Use the existing static HTML dashboard and generated JSON files.

### Phase 2
Migrate the UI to a static-exported **Next.js / React** app while preserving the data contract:

- `data/manifest.json`
- `data/markets/*.json`
- `data/derived/watchlist.json`
- `data/derived/weekly_changes.json`
- `data/derived/narratives.json`

This mirrors the static-site philosophy used by `proprietary/cftc-cot-viewer`, which is built as a static client-side COT viewer. [Source](https://github.com/proprietary/cftc-cot-viewer)

## Release cadence note

COT data is generally released on Friday and reflects Tuesday positions, so your workflow should run **after** the normal Friday release time. [Source](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)

## Practical checklist

- Confirm repository is public if you want free GitHub Pages hosting
- Confirm all JSON files are committed after workflow run
- Confirm relative paths work on GitHub Pages
- Confirm dashboard renders if there is no fresh update for a holiday week
- Add a visible `Last updated` and `As of Tuesday` badge in the UI
