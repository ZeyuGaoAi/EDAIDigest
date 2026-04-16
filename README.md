# AI Early Cancer Digest

Lightweight local pipeline for a human-reviewed digest covering:

- papers
- funding calls
- job opportunities

The intended workflow is:

1. A scheduled Codex automation runs the local ingest commands.
2. Codex reads the review queue and drafts a daily newsletter in Markdown.
3. A human reviewer checks the draft and tells Codex whether to revise or approve it.
4. Sending is handled later, after approval.

## Why this shape

This repo deliberately avoids direct API calls to OpenAI. The automation uses Codex itself for selection and drafting, while the local Python code handles deterministic tasks:

- fetching feeds
- storing items in SQLite
- deduplicating by URL
- assigning a heuristic relevance score
- exporting a review queue
- generating a fallback draft template

## Project layout

- [digest/cli.py](/Users/gao05/Documents/Playground/ai-early-cancer-digest/digest/cli.py)
- [digest/fetch.py](/Users/gao05/Documents/Playground/ai-early-cancer-digest/digest/fetch.py)
- [digest/drafts.py](/Users/gao05/Documents/Playground/ai-early-cancer-digest/digest/drafts.py)
- [digest/site.py](/Users/gao05/Documents/Playground/ai-early-cancer-digest/digest/site.py)
- [data/sources.json](/Users/gao05/Documents/Playground/ai-early-cancer-digest/data/sources.json)
- [drafts](/Users/gao05/Documents/Playground/ai-early-cancer-digest/drafts)
- [site](/Users/gao05/Documents/Playground/ai-early-cancer-digest/site)

## Local commands

Initialize the database:

```bash
python3 -m digest.cli init-db
```

Fetch new items from configured feeds:

```bash
python3 -m digest.cli ingest
```

Export the reviewer queue for Codex and the human reviewer:

```bash
python3 -m digest.cli export-review
```

Generate a fallback draft template:

```bash
python3 -m digest.cli generate-draft
```

Build the static history page:

```bash
python3 -m digest.cli build-site
```

Update an item's workflow status:

```bash
python3 -m digest.cli set-status 12 approved
```

## Review states

- `new`: newly fetched and not yet reviewed
- `reviewed`: accepted into the review pool
- `drafted`: already used in a draft
- `approved`: approved by the human reviewer
- `sent`: already distributed
- `rejected`: not relevant

## How the automation should behave

The scheduled automation should:

1. Run `python3 -m digest.cli run-daily`
2. Read [review_queue.md](/Users/gao05/Documents/Playground/ai-early-cancer-digest/review_queue.md)
3. Rewrite `drafts/YYYY-MM-DD.md` into a short human-ready newsletter draft with:
   - a concise subject line
   - top papers
   - top funding calls
   - top jobs
   - a short editor note
4. Refresh the static site in [site/index.html](/Users/gao05/Documents/Playground/ai-early-cancer-digest/site/index.html)
5. Keep factual statements tied to the linked sources
6. Avoid sending anything automatically

## Notes on source quality

- The default `paper` feeds are live and validated.
- The default `funding` feed currently uses Cancer Research UK news as a placeholder source stream.
- The default `job` source is [data/manual_jobs.json](/Users/gao05/Documents/Playground/ai-early-cancer-digest/data/manual_jobs.json) so the pipeline can already run before a site-specific scraper is added.
- Heuristic relevance is intentionally strict for `paper` items to avoid false positives like generic AI screening papers that are unrelated to cancer.

## If you move the folder

If you relocate the project directory later, the code will still work as long as you run commands from the new repo root, because paths are resolved relative to the package root.

The one thing that must be updated after a move is the Codex automation `cwd`. Once you tell me the new path, I can update that scheduled job in one step.

## Publishing on GitHub Pages

The repo includes [pages.yml](/Users/gao05/Documents/Playground/ai-early-cancer-digest/.github/workflows/pages.yml), which deploys the prebuilt `site/` directory to GitHub Pages on pushes to `main`.

Typical flow:

```bash
python3 -m digest.cli run-daily
git add .
git commit -m "Update digest and site"
git push origin main
```

If the repository is connected to GitHub and Pages is enabled for GitHub Actions, the history page will publish automatically.

## Next practical steps

- Replace or expand the default feed list with your real target sources.
- Tighten the keyword-based relevance rules in [digest/relevance.py](/Users/gao05/Documents/Playground/ai-early-cancer-digest/digest/relevance.py).
- Add source-specific scrapers for important funding and jobs pages that do not expose RSS.
- Add a separate approve-and-send step only after the draft review process is stable.
