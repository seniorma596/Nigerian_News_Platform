
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from io import BytesIO
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

import feedparser
import re
import html
import requests
import imagehash

from PIL import Image
from gnews_decoder import decode


NEWS_FEEDS = {
    "PUNCH": "https://rss.punchng.com/v1/category/latest_news",
    "Daily Post": "https://dailypost.ng/feed/",
    "Premium Times": "https://www.premiumtimesng.com/feed/",
    "Legit.ng": "https://www.legit.ng/rss/all.rss"
}


CATEGORY_FEEDS = {
    "politics": {
        "search": "Nigeria politics",
        "keywords": [
            "politics", "political", "election", "INEC",
            "Tinubu", "APC", "PDP", "ADC", "governor",
            "senate", "senator", "minister", "president",
            "lawmakers", "political party", "House of Representatives",
            "Atiku", "Peter Obi", "electoral", "ballot",
            "political campaign", "National Assembly"
        ],
        "exclude": [
            "britannica", "history of nigeria", "geography of nigeria"
        ]
    },

    "sports": {
        "search": "Nigeria sports football",
        "keywords": [
            "football", "Super Eagles", "NPFL", "NFF",
            "FIFA", "CAF", "AFCON", "Premier League",
            "sports", "athlete", "athletics", "coach",
            "footballer", "tournament", "Olympics",
            "basketball", "tennis", "boxing", "sports development"
        ],
        "exclude": [
            "sports betting", "sports bettors", "betking",
            "betting guide", "betting tips"
        ]
    },

    "business": {
        "search": "Nigeria business economy finance",
        "keywords": [
            "business", "economy", "economic", "naira",
            "inflation", "investment", "bank", "finance",
            "market", "trade", "company", "entrepreneur",
            "revenue", "budget", "oil price", "SME",
            "business growth", "stock market", "tax",
            "business funding", "financial"
        ],
        "exclude": []
    },

    "entertainment": {
        "search": "Nigeria entertainment Nollywood music",
        "keywords": [
            "entertainment", "music", "musician", "singer",
            "Nollywood", "actor", "actress", "film",
            "movie", "celebrity", "album", "concert",
            "BBNaija", "reality show", "comedian",
            "gospel singer", "artist", "showbiz"
        ],
        "exclude": []
    },

    "technology": {
        "search": "Nigeria technology tech innovation",
        "keywords": [
            "technology", "tech", "artificial intelligence",
            "AI", "software", "cybersecurity", "digital",
            "startup", "innovation", "telecom", "internet",
            "gadget", "smartphone", "app", "ICT", "NITDA",
            "drone", "robotics", "data science", "fintech"
        ],
        "exclude": []
    }
}


def fetch_feed(url, timeout=(4, 10)):
    """
    Download an RSS feed with a timeout.
    This prevents slow feeds from holding up the homepage.
    """

    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        return feedparser.parse(response.content)

    except requests.RequestException as error:
        print(f"Feed download failed: {error}")
        return feedparser.parse("")


def get_direct_link(link):
    """
    Convert Google News links into direct publisher links.
    Keep the original link if decoding fails.
    """

    if not link or "news.google.com" not in link:
        return link

    try:
        direct_link = decode(link)

        if (
            isinstance(direct_link, str)
            and direct_link.startswith(("https://", "http://"))
        ):
            return direct_link

    except Exception as error:
        print(f"Google News link decoding failed: {error}")

    return link


def get_wikimedia_image(headline):
    """
    Find a relevant, openly licensed Wikimedia image.
    Compare image titles and descriptions with the news headline.
    """

    if not headline:
        return ""

    api_url = "https://commons.wikimedia.org/w/api.php"

    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": headline,
        "gsrnamespace": 6,
        "gsrlimit": 15,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 800,
        "format": "json"
    }

    stopwords = {
        "the", "and", "for", "with", "from", "that", "this",
        "into", "over", "under", "after", "before", "about",
        "how", "why", "what", "when", "where", "who", "are",
        "was", "were", "has", "have", "had", "its", "his",
        "her", "their", "they", "them", "will", "would",
        "could", "should", "can", "may", "not", "but",
        "new", "says", "said", "latest", "news"
    }

    def get_keywords(value):
        words = re.findall(r"[a-z0-9]+", value.lower())
        return {
            word for word in words
            if len(word) >= 3 and word not in stopwords
        }

    headline_words = get_keywords(headline)

    if len(headline_words) < 2:
        return ""

    try:
        response = requests.get(
            api_url,
            params=params,
            headers={"User-Agent": "NaijaNews/1.0 (news website)"},
            timeout=10
        )

        response.raise_for_status()

        pages = response.json().get("query", {}).get("pages", {})

        allowed_licenses = (
            "CC0",
            "Public domain",
            "CC BY",
            "CC BY-SA"
        )

        best_image = ""
        best_score = 0

        for page in pages.values():
            title = page.get("title", "").lower()

            if not title.endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue

            image_info = page.get("imageinfo", [{}])[0]
            metadata = image_info.get("extmetadata", {})

            license_name = metadata.get(
                "LicenseShortName", {}
            ).get("value", "")

            if not any(
                license_name.startswith(license_type)
                for license_type in allowed_licenses
            ):
                continue

            description = metadata.get(
                "ImageDescription", {}
            ).get("value", "")

            object_name = metadata.get(
                "ObjectName", {}
            ).get("value", "")

            searchable_text = " ".join([
                title,
                description,
                object_name
            ])

            searchable_text = html.unescape(
                re.sub(r"<[^>]+>", " ", searchable_text)
            )

            image_words = get_keywords(searchable_text)
            matching_words = headline_words.intersection(image_words)

            if len(matching_words) < 2:
                continue

            score = len(matching_words) / len(headline_words)

            if score > best_score:
                image_url = image_info.get("thumburl", "")

                if image_url.startswith("https://"):
                    best_score = score
                    best_image = image_url

        if best_score >= 0.20:
            return best_image

    except (requests.RequestException, ValueError, KeyError, IndexError) as error:
        print(f"Wikimedia image search failed: {error}")

    return ""

def get_article_image(item, fetch_publisher=True):
    """
    Extract article images from RSS metadata and publisher pages.
    """

    # 1. Check media content and thumbnails.
    for field in ("media_content", "media_thumbnail"):
        for media in item.get(field, []):
            image_url = media.get("url", "")

            if image_url and "punch-logo" not in image_url.lower():
                return html.unescape(image_url)

    # 2. Check image enclosures.
    for enclosure in item.get("enclosures", []):
        image_url = enclosure.get("href", "") or enclosure.get("url", "")

        if (
            image_url
            and enclosure.get("type", "").startswith("image/")
            and "punch-logo" not in image_url.lower()
        ):
            return html.unescape(image_url)

    # 3. Check RSS links.
    for link in item.get("links", []):
        if link.get("type", "").startswith("image/"):
            image_url = link.get("href", "")

            if image_url and "punch-logo" not in image_url.lower():
                return html.unescape(image_url)

    # 4. Check RSS content and descriptions.
    contents = [
        content_item.get("value", "")
        for content_item in item.get("content", [])
    ]

    contents.extend([
        item.get("summary", ""),
        item.get("description", "")
    ])

    for content in contents:
        match = re.search(
            r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']',
            content or "",
            re.IGNORECASE
        )

        if match:
            image_url = html.unescape(match.group(1))

            if "punch-logo" not in image_url.lower():
                return image_url

    if not fetch_publisher:
        return ""

    # 5. Retrieve the publisher's Open Graph image.
    article_url = get_direct_link(item.get("link", ""))

    if article_url:
        try:
            response = requests.get(
                article_url,
                timeout=5,
                headers={"User-Agent": "Mozilla/5.0"}
            )

            response.raise_for_status()

            meta_tags = re.findall(
                r'<meta\b[^>]*>',
                response.text,
                re.IGNORECASE
            )

            for tag in meta_tags:
                if not re.search(
                    r'(?:property|name)=["\']og:image["\']',
                    tag,
                    re.IGNORECASE
                ):
                    continue

                image_match = re.search(
                    r'content=["\']([^"\']+)["\']',
                    tag,
                    re.IGNORECASE
                )

                if image_match:
                    image_url = html.unescape(image_match.group(1))

                    if image_url.startswith(("https://", "http://")):
                        if "punch-logo" not in image_url.lower():
                            return image_url

        except requests.RequestException as error:
            print(f"Publisher image fetch failed: {error}")

    return ""


@lru_cache(maxsize=500)
def image_fingerprint(image_url):
    """
    Generate a perceptual hash for an article image.
    Cache results to avoid processing the same URL repeatedly.
    """

    response = None

    try:
        response = requests.get(
            image_url,
            timeout=(2, 4),
            headers={"User-Agent": "Mozilla/5.0"},
            stream=True
        )

        response.raise_for_status()

        content_type = response.headers.get(
            "Content-Type", ""
        ).lower()

        if not content_type.startswith("image/"):
            return None

        image_data = response.raw.read(5 * 1024 * 1024)

        if not image_data:
            return None

        with Image.open(BytesIO(image_data)) as img:
            img = img.convert("RGB")
            img.thumbnail((300, 300))

            return imagehash.phash(img)

    except Exception:
        return None

    finally:
        if response is not None:
            response.close()


def remove_repeated_images(*groups):
    """
    Remove visually repeated images across homepage article groups.
    The first occurrence keeps its image.
    """

    articles = []

    for group in groups:
        if isinstance(group, dict):
            for category_articles in group.values():
                articles.extend(category_articles)
        else:
            articles.extend(group)

    image_urls = list(dict.fromkeys(
        article.get("image", "")
        for article in articles
        if article.get("image")
    ))

    with ThreadPoolExecutor(max_workers=8) as executor:
        fingerprints = dict(
            zip(
                image_urls,
                executor.map(image_fingerprint, image_urls)
            )
        )

    seen_fingerprints = []

    for article in articles:
        image_url = article.get("image", "")

        if not image_url:
            continue

        fingerprint = fingerprints.get(image_url)

        if fingerprint is None:
            continue

        if any(
            fingerprint - previous <= 6
            for previous in seen_fingerprints
        ):
            article["image"] = ""
        else:
            seen_fingerprints.append(fingerprint)


def fetch_news(limit=10):
    articles = []
    seen_titles = set()
    seen_links = set()

    # Fetch publisher feeds concurrently.
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            source: executor.submit(fetch_feed, url)
            for source, url in NEWS_FEEDS.items()
        }

        for source, future in futures.items():
            try:
                feed = future.result()

            except Exception as error:
                print(f"Could not fetch {source}: {error}")
                continue

            for item in feed.entries:
                title = item.get("title", "No title").strip()
                article_link = item.get("link", "").strip()

                if not article_link:
                    continue

                normalized_title = " ".join(title.lower().split())
                normalized_link = article_link.rstrip("/").lower()

                if (
                    normalized_title in seen_titles
                    or normalized_link in seen_links
                ):
                    continue

                seen_titles.add(normalized_title)
                seen_links.add(normalized_link)

                articles.append({
                    "title": title,
                    "link": article_link,
                    "published": item.get("published", ""),
                    "source": source,
                    "image": get_article_image(
                        item,
                        fetch_publisher=False
                    ),
                    "_date": get_article_date(item)
                })

    articles.sort(
        key=lambda article: (
            article["_date"]
            or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True
    )

    for article in articles:
        article.pop("_date", None)

    return articles[:limit]


def get_article_date(item):
    published = (
        item.get("published_parsed")
        or item.get("updated_parsed")
    )

    if not published:
        return None

    try:
        return datetime(*published[:6], tzinfo=timezone.utc)

    except (TypeError, ValueError):
        return None


def is_recent(item, days=7):
    article_date = get_article_date(item)

    if not article_date:
        return False

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    return cutoff <= article_date <= now


def matches_category(item, keywords, excluded):
    title = item.get("title", "").lower()
    summary = item.get("summary", "").lower()

    text = title + " " + summary

    if any(word.lower() in text for word in excluded):
        return False

    if any(word.lower() in text for word in keywords):
        return True

    return False


def fetch_category_news(limit=10):
    categories = {}

    category_urls = {
        category: (
            "https://news.google.com/rss/search?q="
            + quote(settings["search"] + " when:7d")
            + "&hl=en-NG&gl=NG&ceid=NG:en"
        )
        for category, settings in CATEGORY_FEEDS.items()
    }

    # Fetch all five category feeds concurrently.
    with ThreadPoolExecutor(max_workers=5) as executor:
        feed_results = list(
            executor.map(fetch_feed, category_urls.values())
        )

    feeds = dict(zip(category_urls.keys(), feed_results))

    # Collect selected articles first, without downloading publisher pages.
    for category, settings in CATEGORY_FEEDS.items():
        feed = feeds[category]
        articles = []
        seen_links = set()

        for item in feed.entries:
            if not is_recent(item, days=7):
                continue

            if not matches_category(
                item,
                settings["keywords"],
                settings["exclude"]
            ):
                continue

            link = item.get("link", "")

            if not link or link in seen_links:
                continue

            seen_links.add(link)

            source = item.get("source", {})

            if not isinstance(source, dict):
                source = {}

            articles.append({
                "title": item.get("title", "No title"),
                "link": link,
                "published": item.get("published", ""),
                "source": source.get("title", "Google News"),
                "image": get_article_image(
                    item,
                    fetch_publisher=False
                ),
                "_rss_item": item,
                "date": get_article_date(item)
            })

        articles.sort(
            key=lambda article: (
                article["date"]
                or datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True
        )

        categories[category] = articles[:limit]

    # Fetch missing publisher images concurrently.
    missing_images = []

    for category, articles in categories.items():
        for article in articles[:5]:
            if not article["image"]:
                missing_images.append(article)

    def fetch_missing_image(article):
        article["image"] = get_article_image(
            article["_rss_item"],
            fetch_publisher=True
        )

        if article["image"]:
            return

        headline = article["title"]

        # First attempt: search using the complete headline.
        article["image"] = get_wikimedia_image(headline)

        if article["image"]:
            return

        # Second attempt: search using the main subject words.
        stopwords = {
            "the", "and", "for", "with", "from", "that",
            "this", "into", "over", "after", "before",
            "about", "how", "why", "what", "when",
            "who", "are", "was", "were", "has", "have",
            "its", "his", "her", "their", "will", "says",
            "said", "news", "nigeria", "nigerian"
        }

        words = re.findall(r"[a-zA-Z0-9]+", headline)
        keywords = [
            word for word in words
            if len(word) >= 3 and word.lower() not in stopwords
        ]

        if len(keywords) >= 2:
            shorter_search = " ".join(keywords[:5])
            article["image"] = get_wikimedia_image(shorter_search)

    with ThreadPoolExecutor(max_workers=15) as executor:
        list(executor.map(fetch_missing_image, missing_images))

    # Remove temporary processing data.
    for articles in categories.values():
        for article in articles:
            article.pop("date", None)
            article.pop("_rss_item", None)

    return categories


def search_news(search_term, limit=20):
    """
    Search Google News RSS for articles matching a keyword.
    """

    if not search_term or not search_term.strip():
        return []

    search_url = (
        "https://news.google.com/rss/search?q="
        + quote(search_term.strip())
        + "&hl=en-NG&gl=NG&ceid=NG:en"
    )

    feed = fetch_feed(search_url)

    results = []
    seen_links = set()

    for item in feed.entries:
        link = item.get("link", "")

        if not link or link in seen_links:
            continue

        seen_links.add(link)

        source = item.get("source", {})

        if not isinstance(source, dict):
            source = {}

        results.append({
            "title": item.get("title", "No title"),
            "link": link,
            "published": item.get("published", ""),
            "source": source.get("title", "Google News"),
            "image": get_article_image(item)
        })

        if len(results) >= limit:
            break

    # Decode search result links only, not homepage category links.
    for article in results:
        article["link"] = get_direct_link(article["link"])

    return results
