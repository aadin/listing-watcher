import requests

SEARCH_URL = "https://jp.mercari.com/en/search?keyword=beyblade%20metal%20fight"

HEADERS = {
    "User-Agent": "listing-watcher/1.0"
}

def fetch_listings():
    # TODO:
    # 1. Request the search page or official API.
    # 2. Parse the response.
    # 3. Convert each result into the normalized format below.

    response = requests.get(
        SEARCH_URL,
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()

    # Replace this with parsed results.
    raw_items = []

    listings = []

    for item in raw_items:
        listings.append({
            "id": item["id"],
            "title": item["title"],
            "price": item["price"],
            "url": item["url"],
            "image": item["image"],
        })

    return listings