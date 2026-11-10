from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import re
import html

try:
    from gnews_decoder import decode
except ImportError:
    decode = None


# =========================================================
# NEWS SOURCES
# =========================================================

NEWS_FEEDS = {
    "PUNCH": "https://rss.punchng.com/v1/category/latest_news",
    "Daily Post": "https://dailypost.ng/feed/",
    "Premium Times": "https://www.premiumtimesng.com/feed/",
    "Legit.ng": "https://www.legit.ng/rss/all.rss"
}


# =========================================================
# NEWS CATEGORIES
# =========================================================

CATEGORY_FEEDS = {

    "politics": {
        "search": "Nigeria politics",
        "keywords": [
            "politics", "political", "election", "INEC",
            "Tinubu", "APC", "PDP", "ADC", "governor",
            "senate", "senator", "minister", "president",
            "lawmakers", "political party",
            "House of Representatives",
            "Atiku", "Peter Obi", "electoral", "ballot",
            "political campaign", "National Assembly"
        ],
        "exclude": [
            "britannica",
            "history of nigeria",
            "geography of nigeria"
        ]
    },

    "sports": {
        "search": "Nigeria sports football",
        "keywords": [
            "football", "Super Eagles", "NPFL", "NFF",
            "FIFA", "CAF", "AFCON", "Premier League",
            "sports", "athlete", "athletics", "coach",
            "footballer", "tournament", "Olympics",
            "basketball", "tennis", "boxing",
            "sports development"
        ],
        "exclude": [
            "sports betting",
            "sports bettors",
            "betking",
            "betting guide",
            "betting tips"
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


# =========================================================
# PERFORMANCE SETTINGS
# =========================================================

REQUEST_TIMEOUT = (3, 5)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NaijaNews/1.0)"
}


# =========================================================
# FETCH RSS FEEDS
# =========================================================

def fetch_feed(url, timeout=REQUEST_TIMEOUT):

    """
    Download and parse an RSS feed quickly.

    Short timeouts prevent slow external websites
    from holding up the homepage.
    """

    try:

        response = requests.get(
            url,
            timeout=timeout,
            headers=HEADERS
        )

        response.raise_for_status()

        return feedparser.parse(response.content)

    except requests.RequestException as error:

        print(f"Feed download failed: {error}")

        return feedparser.parse("")

    except Exception as error:

        print(f"RSS parsing failed: {error}")

        return feedparser.parse("")


# =========================================================
# GOOGLE NEWS LINK DECODER
# =========================================================

def get_direct_link(link):

    """
    Convert Google News links into direct publisher links.

    If decoding fails, retain the original link.
    """

    if not link or "news.google.com" not in link:
        return link

    if decode is None:
        return link

    try:

        direct_link = decode(link)

        if (
            isinstance(direct_link, str)
            and direct_link.startswith(("https://", "http://"))
        ):
            return direct_link

    except Exception as error:

        print(f"Google News decoding failed: {error}")

    return link


# =========================================================
# EXTRACT IMAGES FROM RSS ONLY
# =========================================================

def get_article_image(item, fetch_publisher=False):

    """
    Extract images already supplied by RSS feeds.

    Does not download publisher webpages.
    Does not search Wikimedia.
    """

    # 1. Media content and thumbnails

    for field in ("media_content", "media_thumbnail"):

        for media in item.get(field, []):

            image_url = media.get("url", "")

            if (
                image_url
                and image_url.startswith(("https://", "http://"))
                and "punch-logo" not in image_url.lower()
            ):

                return html.unescape(image_url)

    # 2. Image enclosures

    for enclosure in item.get("enclosures", []):

        image_url = (
            enclosure.get("href", "")
            or enclosure.get("url", "")
        )

        if (
            image_url
            and enclosure.get("type", "").startswith("image/")
            and "punch-logo" not in image_url.lower()
        ):

            return html.unescape(image_url)

    # 3. Image links

    for link in item.get("links", []):

        if link.get("type", "").startswith("image/"):

            image_url = link.get("href", "")

            if (
                image_url
                and "punch-logo" not in image_url.lower()
            ):

                return html.unescape(image_url)

    # 4. Images embedded in RSS descriptions

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

            if (
                image_url.startswith(("https://", "http://"))
                and "punch-logo" not in image_url.lower()
            ):

                return image_url

    # No RSS image available.
    # The website template can display its default image.

    return ""


# =========================================================
# COMPATIBILITY FUNCTION
# =========================================================

def remove_repeated_images(*groups):

    """
    Kept for compatibility with app.py.

    Image fingerprinting has been disabled because
    downloading and comparing images was causing
    Render worker timeouts.

    Existing RSS images are preserved.
    """

    return None


# =========================================================
# ARTICLE DATE
# =========================================================

def get_article_date(item):

    published = (
        item.get("published_parsed")
        or item.get("updated_parsed")
    )

    if not published:
        return None

    try:

        return datetime(
            *published[:6],
            tzinfo=timezone.utc
        )

    except (TypeError, ValueError):

        return None


# =========================================================
# CHECK WHETHER NEWS IS RECENT
# =========================================================

def is_recent(item, days=7):

    article_date = get_article_date(item)

    if not article_date:
        return False

    now = datetime.now(timezone.utc)

    cutoff = now - timedelta(days=days)

    return cutoff <= article_date <= now


# =========================================================
# CATEGORY KEYWORD MATCHING
# =========================================================

def matches_category(item, keywords, excluded):

    title = item.get("title", "").lower()

    summary = item.get("summary", "").lower()

    text = title + " " + summary

    if any(word.lower() in text for word in excluded):
        return False

    if any(word.lower() in text for word in keywords):
        return True

    return False


# =========================================================
# FETCH LATEST NEWS
# =========================================================

def fetch_news(limit=10):

    articles = []

    seen_titles = set()

    seen_links = set()

    # Fetch all publisher feeds concurrently.

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

                title = item.get(
                    "title",
                    "No title"
                ).strip()

                article_link = item.get(
                    "link",
                    ""
                ).strip()

                if not article_link:
                    continue

                normalized_title = " ".join(
                    title.lower().split()
                )

                normalized_link = (
                    article_link.rstrip("/").lower()
                )

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

                    "published": item.get(
                        "published",
                        ""
                    ),

                    "source": source,

                    "image": get_article_image(
                        item,
                        fetch_publisher=False
                    ),

                    "_date": get_article_date(item)

                })

    # Sort by publication date.

    articles.sort(
        key=lambda article: (
            article["_date"]
            or datetime.min.replace(
                tzinfo=timezone.utc
            )
        ),
        reverse=True
    )

    # Remove internal sorting data.

    for article in articles:

        article.pop("_date", None)

    return articles[:limit]


# =========================================================
# FETCH CATEGORY NEWS
# =========================================================

def fetch_category_news(limit=10):

    categories = {}

    # Prepare Google News RSS URLs.

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
            executor.map(
                fetch_feed,
                category_urls.values()
            )
        )

    feeds = dict(
        zip(
            category_urls.keys(),
            feed_results
        )
    )

    # Process each category.

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

                "title": item.get(
                    "title",
                    "No title"
                ),

                "link": link,

                "published": item.get(
                    "published",
                    ""
                ),

                "source": source.get(
                    "title",
                    "Google News"
                ),

                "image": get_article_image(
                    item,
                    fetch_publisher=False
                ),

                "date": get_article_date(item)

            })

        # Sort category articles by date.

        articles.sort(
            key=lambda article: (
                article["date"]
                or datetime.min.replace(
                    tzinfo=timezone.utc
                )
            ),
            reverse=True
        )

        categories[category] = articles[:limit]

    # Remove internal date data.

    for articles in categories.values():

        for article in articles:

            article.pop("date", None)

    return categories


# =========================================================
# SEARCH NEWS
# =========================================================

def search_news(search_term, limit=20):

    """
    Search Google News RSS.

    Uses RSS-provided images only.
    Does not download publisher webpages.
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

            "title": item.get(
                "title",
                "No title"
            ),

            "link": link,

            "published": item.get(
                "published",
                ""
            ),

            "source": source.get(
                "title",
                "Google News"
            ),

            "image": get_article_image(
                item,
                fetch_publisher=False
            )

        })

        if len(results) >= limit:
            break

    # Keep original Google News links if decoding is unavailable
    # or unsuccessful.

    for article in results:

        article["link"] = get_direct_link(
            article["link"]
        )

    return results
