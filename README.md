# Manga / Manhwa / Manhua Scraper

Scrapes details for a manga, manhwa or manhua from a URL: title, alternate titles, author(s), artist(s), genres, status, type, description, cover image, rating and the chapter list.

## Setup

```bash
pip install -r requirement.txt
```

## Usage

```bash
python scrapy.py "https://example-manga-site.com/manga/some-title/"
```

Save the result to a file instead of just printing it:

```bash
python scrapy.py "https://example-manga-site.com/manga/some-title/" -o result.json
```

Limit how many chapters are included (useful for very long series):

```bash
python scrapy.py "https://example-manga-site.com/manga/some-title/" --max-chapters 20
```

## What it supports

- **MangaDex** (`mangadex.org/title/...`) — uses MangaDex's official public API, since the website itself is a JavaScript app and has no scrapable HTML.

- **"Madara" theme sites** — a WordPress theme used by a large number of independent manga/manhwa/manhua reader sites. The scraper's selectors target this theme's markup (`.post-content_item`, `.summary-content`, `.wp-manga-chapter`, etc.), so it should work out-of-the-box on many sites without per-site configuration.

- **Anything else** — falls back to Open Graph meta tags (`og:title` ,`og:description`, `og:image`) and schema.org JSON-LD data, so you'll still get a basic title/description/cover even on unsupported layouts.

## Output format

```json
{
  "source": "generic/madara",
  "url": "...",
  "title": "...",
  "alternative_titles": "...",
  "description": "...",
  "status": "...",
  "type": "...",
  "release_year": "...",
  "genres": ["...", "..."],
  "authors": "...",
  "artists": "...",
  "rating": "...",
  "cover_image": "https://...",
  "total_chapters_found": 0,
  "chapters": [
    {"title": "Chapter 1", "url": "https://...", "release_date": "..."}
  ]
}
```

Any field the page doesn't have or that the scraper couldn't find, comes back as `null` rather than crashing the whole run.

## Limitations

- **JavaScript rendered sites**: this uses plain HTTP requests, not a browser, so sites that build the page entirely client side (no content in the raw HTML) won't work. MangaDex is handled specially for this reason.

- **Cloudflare / anti-bot protection** : some sites will block or challenge plain `requests` traffic. If you get a 403 or similar error, that site likely needs more advanced handling like `cloudscraper` or a headless browser like Playwright.

## Files

- `scrapy.py` — the scraper itself (CLI tool)
- `requirement.txt` — Python dependencies
