
import argparse
import json
import sys
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

MAIN_CONTENT_SELECTORS = [
    "article",
    "main",
    '[role="main"]',
    "#content",
    ".content",
    ".post-content",
    ".entry-content",
    ".article-content",
    ".article-body",
    "#main-content",
]



def get_meta_tags(soup):
    meta = {}
    og = {}
    twitter = {}
    for tag in soup.find_all("meta"):
        key = tag.get("name") or tag.get("property")
        content = tag.get("content")
        if not key or content is None:
            continue
        if key.startswith("og:"):
            og[key[3:]] = content
        elif key.startswith("twitter:"):
            twitter[key[8:]] = content
        else:
            meta[key] = content
    return meta, og, twitter


def get_json_ld(soup):
    blocks = []
    for script in soup.select('script[type="application/ld+json"]'):
        if not script.string:
            continue
        try:
            blocks.append(json.loads(script.string))
        except (json.JSONDecodeError, TypeError):
            continue
    return blocks


def get_headings(soup):
    headings = []
    for level in range(1, 7):
        for tag in soup.find_all(f"h{level}"):
            text = tag.get_text(strip=True)
            if text:
                headings.append({"level": level, "text": text})
    return headings


def get_links(soup, base_url):
    base_domain = urlparse(base_url).netloc
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("javascript:") or href.startswith("#"):
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append({
            "text": a.get_text(strip=True),
            "url": absolute,
            "internal": urlparse(absolute).netloc == base_domain,
        })
    return links


def get_images(soup, base_url):
    images = []
    seen = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        absolute = urljoin(base_url, src)
        if absolute in seen:
            continue
        seen.add(absolute)
        images.append({"src": absolute, "alt": img.get("alt", "").strip() or None})
    return images


def get_tables(soup):
    tables = []
    for table in soup.find_all("table"):
        header_cells = table.select_one("thead tr") or table.find("tr")
        headers = (
            [th.get_text(strip=True) for th in header_cells.find_all(["th", "td"])]
            if header_cells else []
        )

        rows = []
        body_rows = table.select("tbody tr") or table.find_all("tr")
        for tr in body_rows:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if not cells or cells == headers:
                continue
            rows.append(cells)

        if headers and rows and all(len(r) == len(headers) for r in rows):
            tables.append([dict(zip(headers, row)) for row in rows])
        else:
            tables.append(([headers] if headers else []) + rows)
    return tables


def extract_main_content(soup, min_length=200):
    best_text = ""
    for selector in MAIN_CONTENT_SELECTORS:
        el = soup.select_one(selector)
        if not el:
            continue
        text = " ".join(el.get_text(separator=" ", strip=True).split())
        if len(text) > len(best_text):
            best_text = text

    if len(best_text) >= min_length:
        return best_text

    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    fallback_text = " ".join(t for t in paragraphs if t)
    return fallback_text if len(fallback_text) > len(best_text) else (best_text or None)


def parse_select_arg(spec):
    if "=" not in spec:
        raise ValueError(f"Invalid --select value '{spec}', expected name=selector")
    name, rest = spec.split("=", 1)
    if "@" in rest:
        selector, attr = rest.rsplit("@", 1)
    else:
        selector, attr = rest, None
    return name.strip(), selector.strip(), (attr.strip() if attr else None)


def extract_custom_fields(soup, select_specs, base_url):
    results = {}
    for spec in select_specs:
        name, selector, attr = parse_select_arg(spec)
        values = []
        for el in soup.select(selector):
            if attr:
                val = el.get(attr)
                if val and attr in ("src", "href"):
                    val = urljoin(base_url, val)
            else:
                val = el.get_text(strip=True)
            if val:
                values.append(val)
        results[name] = values[0] if len(values) == 1 else (values or None)
    return results


class GeneralScraper:
    def __init__(self, timeout=20, respect_robots=True):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.timeout = timeout
        self.respect_robots = respect_robots
        self._robots_cache = {}

    def _robots_allowed(self, url):
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._robots_cache.get(origin)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.set_url(urljoin(origin, "/robots.txt"))
                rp.read()
            except Exception:
                rp = None 
            self._robots_cache[origin] = rp
        if rp is None:
            return True
        try:
            return rp.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def fetch(self, url):
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def scrape_page(self, url, select_specs=None):
        soup = self.fetch(url)
        meta, og, twitter = get_meta_tags(soup)

        result = {
            "url": url,
            "title": soup.title.get_text(strip=True) if soup.title else None,
            "language": soup.html.get("lang") if soup.html else None,
            "meta_description": meta.get("description"),
            "meta_keywords": meta.get("keywords"),
            "canonical_url": (soup.select_one('link[rel="canonical"]') or {}).get("href")
                if soup.select_one('link[rel="canonical"]') else None,
            "open_graph": og or None,
            "twitter_card": twitter or None,
            "json_ld": get_json_ld(soup) or None,
            "headings": get_headings(soup),
            "main_content": extract_main_content(soup),
            "links": get_links(soup, url),
            "images": get_images(soup, url),
            "tables": get_tables(soup),
        }

        if select_specs:
            result["custom_fields"] = extract_custom_fields(soup, select_specs, url)

        result["_internal_link_urls"] = [
            l["url"] for l in result["links"] if l["internal"]
        ]
        return result

    def crawl(self, start_url, max_pages=5, delay=1.0, select_specs=None):
        visited = set()
        queue = [start_url]
        pages = []

        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            normalized = url.split("#")[0]
            if normalized in visited:
                continue
            visited.add(normalized)

            if not self._robots_allowed(url):
                continue
            try:
                page = self.scrape_page(url, select_specs=select_specs)
            except requests.exceptions.RequestException:
                continue

            new_links = page.pop("_internal_link_urls", [])
            pages.append(page)
            for link in new_links:
                clean = link.split("#")[0]
                if clean not in visited and clean not in queue:
                    queue.append(clean)

            if queue and len(pages) < max_pages:
                time.sleep(delay)
        return pages

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("-o", "--output")
    parser.add_argument("--select", action="append", default=[])
    parser.add_argument("--crawl", action="store_true")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--ignore-robots", action="store_true")
    args = parser.parse_args()

    scraper = GeneralScraper(respect_robots=not args.ignore_robots)

    try:
        if args.crawl:
            result = scraper.crawl(
                args.url, max_pages=args.max_pages, delay=args.delay,
                select_specs=args.select,
            )
        else:
            result = scraper.scrape_page(args.url, select_specs=args.select)
            result.pop("_internal_link_urls", None)
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error fetching the page (site may be blocking scrapers): {e}", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Network error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    output = json.dumps(result, indent=2, ensure_ascii=False)
    print(output)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\nSaved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()