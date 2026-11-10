
from flask import Flask, render_template, request
from news import (
    fetch_news,
    fetch_category_news,
    search_news,
    remove_repeated_images
)
from threading import Lock, Thread
import time

app = Flask(__name__)

# Homepage news cache: 5 minutes
HOME_CACHE = {
    "expires_at": 0,
    "articles": [],
    "categories": {}
}

HOME_CACHE_LOCK = Lock()
REFRESH_LOCK = Lock()


def refresh_home_news():
    """
    Fetch fresh homepage news in the background.
    Keep existing cached news if refreshing fails.
    """

    try:
        articles = fetch_news(10)
        categories = fetch_category_news(10)

        # Remove visually repeated images
        remove_repeated_images(articles, categories)

        # Update the cache safely
        with HOME_CACHE_LOCK:
            HOME_CACHE["articles"] = articles
            HOME_CACHE["categories"] = categories
            HOME_CACHE["expires_at"] = time.monotonic() + 300

        print("Background news refresh completed successfully.")

    except Exception as error:
        print(f"Background news refresh failed: {error}")

        # Retry after 60 seconds instead of repeatedly requesting publishers
        with HOME_CACHE_LOCK:
            HOME_CACHE["expires_at"] = time.monotonic() + 60

    finally:
        REFRESH_LOCK.release()


def get_home_news():
    """
    Return cached news immediately when available.
    Refresh expired news in the background.
    """

    needs_refresh = False

    with HOME_CACHE_LOCK:

        # Return fresh cached news
        if time.monotonic() < HOME_CACHE["expires_at"]:
            return HOME_CACHE["articles"], HOME_CACHE["categories"]

        # If cached news already exists, serve it immediately
        if HOME_CACHE["articles"] or HOME_CACHE["categories"]:
            articles = HOME_CACHE["articles"]
            categories = HOME_CACHE["categories"]
            needs_refresh = True

        else:
            # First homepage visit: fetch news normally
            articles = fetch_news(10)
            categories = fetch_category_news(10)

            remove_repeated_images(articles, categories)

            HOME_CACHE["articles"] = articles
            HOME_CACHE["categories"] = categories
            HOME_CACHE["expires_at"] = time.monotonic() + 300

            return articles, categories

    # Refresh expired news without delaying visitors
    if needs_refresh and REFRESH_LOCK.acquire(blocking=False):

        try:
            Thread(
                target=refresh_home_news,
                daemon=True
            ).start()

        except Exception as error:
            REFRESH_LOCK.release()
            print(f"Could not start background refresh: {error}")

    return articles, categories


@app.route("/")
def home():
    search_term = request.args.get("q", "").strip()

    page = request.args.get("page", 1, type=int)
    per_page = 5

    # Get homepage news from cache
    articles, categories = get_home_news()

    search_results = []
    total_results = 0
    total_pages = 0

    if search_term:
        all_search_results = search_news(search_term, limit=20)

        total_results = len(all_search_results)
        total_pages = (total_results + per_page - 1) // per_page

        if total_pages > 0:
            page = max(1, min(page, total_pages))
        else:
            page = 1

        start = (page - 1) * per_page
        end = start + per_page

        search_results = all_search_results[start:end]

    return render_template(
        "index.html",
        articles=articles,
        categories=categories,
        search_term=search_term,
        search_results=search_results,
        page=page,
        total_pages=total_pages,
        total_results=total_results
    )


if __name__ == "__main__":
    app.run(debug=True)
