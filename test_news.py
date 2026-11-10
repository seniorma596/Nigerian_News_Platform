import feedparser

url = "https://rss.punchng.com/v1/category/latest_news"

feed = feedparser.parse(url)

print("News source:", feed.feed.get("title", "PUNCH"))
print("Number of articles found:", len(feed.entries))

for article in feed.entries[:5]:
    print("\nTitle:", article.title)
    print("Link:", article.link)
