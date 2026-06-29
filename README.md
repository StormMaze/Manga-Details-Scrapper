# General Purpose Website Scraper

Scrapes any (server-rendered) webpage for its content like metadata, headings, links, images, tables, structured data, a best guess "main content" extraction for articles/blog posts. You can also pull your own custom fields with CSS selectors, and optionally crawl multiple pages on the same domain.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

Scrape a single page:

```bash
python general_scraper.py "https://example.com/some-page"
```

Save to a file:

```bash
python general_scraper.py "<url>" -o result.json
```

### Custom fields (works on literally any layout)

Use `--select "name=css_selector"` to pull out specific values as handy for things like prices, ratings, names and anything not covered by the generic fields below. Repeat the flag for multiple fields.

```bash
python general_scraper.py "https://shop.example.com/product/123" \
  --select "price=.product-price" \
  --select "rating=.stars@data-rating" \
  --select "image=.gallery img@src"
```

- `name=selector` → grabs the element's text
- `name=selector@attribute` → grabs that attribute instead (e.g. `@href`,
  `@src`, `@data-price`)
- If a selector matches multiple elements, you get a list back; if it matches one, you get a single value.

### Crawling multiple pages

```bash
python general_scraper.py "<url>" --crawl --max-pages 20 --delay 1.5
```

This does a breadth first crawl following same domain links found on each page, up to `--max-pages`, waiting `--delay` seconds between requests. It checks `robots.txt` before fetching each page unless you pass `--ignore-robots`.

## What you get back

For each page:

```json
{
  "url": "...",
  "title": "...",
  "language": "en",
  "meta_description": "...",
  "meta_keywords": "...",
  "canonical_url": "...",
  "open_graph": { "title": "...", "image": "..." },
  "twitter_card": { "card": "..." },
  "json_ld": [ /* raw schema.org blocks, whatever type they are */ ],
  "headings": [ {"level": 1, "text": "..."} ],
  "main_content": "best-guess article/body text",
  "links": [ {"text": "...", "url": "...", "internal": true} ],
  "images": [ {"src": "...", "alt": "..."} ],
  "tables": [ /* each table as a list of row objects or row arrays */ ],
  "custom_fields": { "price": "19.99" }
}
```

When `--crawl` is used, the output is a list of these objects, one per page visited.
Missing fields come back as `null` rather than crashing the run.

## Limitations

- **JavaScript-rendered sites**: this fetches raw HTML, it doesn't run a browser. If a site builds its content client-side and the raw response is mostly empty `<div>`s, this won't see that content.

- **Cloudflare / anti-bot protection**: some sites block plain HTTP clients outright. A 403 here usually means that.

- **`main_content` is a heuristic**, not perfect extraction and it checks a handful of common containers (`article`, `main`, `.post-content`, etc.) and falls back to all `<p>` text. Good for typical blogs/news/docs pages so less reliable on heavily custom layouts.
