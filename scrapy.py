import argparse
import json
import re
import sys
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

MANGADEX_ID_RE = re.compile(
    r"/title/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


def first_match(soup, candidates):
    
    for selector, attr in candidates:
        el = soup.select_one(selector)
        if not el:
            continue
        if attr == "text":
            text = el.get_text(strip=True)
            if text:
                return text
        else:
            val = el.get(attr)
            if val:
                return val.strip()
    return None


def extract_post_content_items(soup):
    data = {}
    for item in soup.select(".post-content_item"):
        heading = item.select_one(".summary-heading")
        content = item.select_one(".summary-content")
        if not (heading and content):
            continue
        key = heading.get_text(strip=True).lower()
        links = [a.get_text(strip=True) for a in content.select("a") if a.get_text(strip=True)]
        if links:
            value = links[0] if len(links) == 1 else links
        else:
            value = content.get_text(strip=True)
        if value:
            data[key] = value
    return data


def parse_json_ld(soup):
    info = {}
    for script in soup.select('script[type="application/ld+json"]'):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type", "")
            if isinstance(item_type, list):
                item_type = ",".join(item_type)
            if any(t in str(item_type) for t in ("Book", "CreativeWork", "Comic", "Article")):
                info.setdefault("title", item.get("name"))
                info.setdefault("description", item.get("description"))
                image = item.get("image")
                if isinstance(image, dict):
                    image = image.get("url")
                if isinstance(image, list) and image:
                    image = image[0]
                info.setdefault("image", image)
    return info



class MangaScraper:
    def __init__(self, timeout=20):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.timeout = timeout

    def fetch_html(self, url):
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def fetch_json(self, url, params=None):
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def scrape(self, url):
        domain = urlparse(url).netloc.lower()
        if "mangadex.org" in domain:
            return self.scrape_mangadex(url)
        return self.scrape_generic(url)

    def scrape_mangadex(self, url):
        match = MANGADEX_ID_RE.search(url)
        if not match:
            raise ValueError(
                "Couldn't find a MangaDex manga ID in that URL. "
                "Expected something like https://mangadex.org/title/<uuid>/<slug>"
            )
        manga_id = match.group(1)

        data = self.fetch_json(
            f"https://api.mangadex.org/manga/{manga_id}",
            params={"includes[]": ["author", "artist", "cover_art"]},
        )["data"]
        attrs = data["attributes"]

        title = attrs["title"].get("en") or next(iter(attrs["title"].values()), "Unknown")
        alt_titles = [next(iter(t.values())) for t in attrs.get("altTitles", []) if t]
        description = (
            attrs.get("description", {}).get("en")
            or next(iter(attrs.get("description", {}).values()), None)
        )
        genres = [t["attributes"]["name"].get("en") for t in attrs.get("tags", [])]

        authors, artists, cover_filename = [], [], None
        for rel in data.get("relationships", []):
            if rel["type"] == "author":
                name = rel.get("attributes", {}).get("name")
                if name:
                    authors.append(name)
            elif rel["type"] == "artist":
                name = rel.get("attributes", {}).get("name")
                if name:
                    artists.append(name)
            elif rel["type"] == "cover_art":
                cover_filename = rel.get("attributes", {}).get("fileName")

        cover_image = (
            f"https://uploads.mangadex.org/covers/{manga_id}/{cover_filename}"
            if cover_filename else None
        )

        chapters = []
        try:
            agg = self.fetch_json(
                f"https://api.mangadex.org/manga/{manga_id}/aggregate",
                params={"translatedLanguage[]": ["en"]},
            )
            for vol_key, vol in agg.get("volumes", {}).items():
                for ch_key, ch in vol.get("chapters", {}).items():
                    chapters.append({
                        "volume": vol_key,
                        "chapter": ch_key,
                        "id": ch.get("id"),
                    })
        except requests.exceptions.RequestException:
            pass 

        return {
            "source": "MangaDex",
            "url": url,
            "title": title,
            "alternative_titles": alt_titles or None,
            "description": description,
            "status": attrs.get("status"),
            "type": "manga",
            "release_year": attrs.get("year"),
            "genres": genres or None,
            "authors": authors or None,
            "artists": artists or None,
            "rating": None,  # not exposed on this endpoint
            "cover_image": cover_image,
            "total_chapters_found": len(chapters),
            "chapters": chapters,
        }

    def scrape_generic(self, url):
        soup = self.fetch_html(url)
        post_items = extract_post_content_items(soup)
        json_ld = parse_json_ld(soup)

        title = first_match(soup, [
            ("div.post-title h1", "text"),
            ("h1.entry-title", "text"),
            ('h1[itemprop="name"]', "text"),
            ('meta[property="og:title"]', "content"),
        ]) or json_ld.get("title") or (soup.title.get_text(strip=True) if soup.title else None)

        description = first_match(soup, [
            ("div.description-summary div.summary__content", "text"),
            ("div.summary__content", "text"),
            ("#editdescription", "text"),
            ('meta[property="og:description"]', "content"),
            ('meta[name="description"]', "content"),
        ]) or json_ld.get("description")

        cover_image = first_match(soup, [
            ("div.summary_image img", "data-src"),
            ("div.summary_image img", "src"),
            ('meta[property="og:image"]', "content"),
        ]) or json_ld.get("image")

        alt_titles = author = artist = genres = status = manga_type = None
        release_year = rating = None

        for key, value in post_items.items():
            if "alt" in key:
                alt_titles = value
            elif "author" in key:
                author = value
            elif "artist" in key:
                artist = value
            elif "genre" in key:
                genres = value
            elif "status" in key:
                status = value
            elif "type" in key:
                manga_type = value
            elif "release" in key:
                release_year = value
            elif "rat" in key:
                rating = value

        if not genres:
            found = [a.get_text(strip=True) for a in soup.select(".genres-content a")]
            genres = found or None

        if not rating:
            rating = first_match(soup, [
                ("#averagerate", "text"),
                (".post-rating .score", "text"),
                ('[itemprop="ratingValue"]', "text"),
            ])

        chapters = []
        for li in soup.select("li.wp-manga-chapter"):
            a = li.select_one("a")
            date_el = li.select_one(".chapter-release-date")
            if a:
                chapters.append({
                    "title": a.get_text(strip=True),
                    "url": a.get("href"),
                    "release_date": date_el.get_text(strip=True) if date_el else None,
                })

        if not chapters:
            for a in soup.select(".chapter-list a, .listing-chapters_wrap a, .version-chap a"):
                href = a.get("href")
                text = a.get_text(strip=True)
                if href and text:
                    chapters.append({"title": text, "url": href, "release_date": None})

        return {
            "source": "generic/madara",
            "url": url,
            "title": title,
            "alternative_titles": alt_titles,
            "description": description,
            "status": status,
            "type": manga_type,
            "release_year": release_year,
            "genres": genres,
            "authors": author,
            "artists": artist,
            "rating": rating,
            "cover_image": cover_image,
            "total_chapters_found": len(chapters),
            "chapters": chapters,
        }

def main():
    parser = argparse.ArgumentParser(
        description="Scrape manga / manhwa / manhua details from a URL."
    )
    parser.add_argument("url", help="URL of the manga/manhwa/manhua page")
    parser.add_argument("-o", "--output", help="Save the result as a JSON file")
    parser.add_argument(
        "--max-chapters", type=int, default=None,
        help="Limit the number of chapters included in the output"
    )
    args = parser.parse_args()

    scraper = MangaScraper()
    try:
        result = scraper.scrape(args.url)
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error fetching the page (site may be blocking scrapers): {e}", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Network error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.max_chapters is not None and result.get("chapters"):
        result["chapters"] = result["chapters"][: args.max_chapters]

    output = json.dumps(result, indent=2, ensure_ascii=False)
    print(output)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\nSaved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()