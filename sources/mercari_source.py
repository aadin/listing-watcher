import asyncio

from mercapi import Mercapi
from mercapi.requests import SearchRequestData

KEYWORD = "beyblade metal fight"


async def _fetch():
    m = Mercapi()

    results = await m.search(
        KEYWORD,
        sort_by=SearchRequestData.SortBy.SORT_CREATED_TIME,
        sort_order=SearchRequestData.SortOrder.ORDER_DESC,
    )

    items = []
    for item in results.items:
        item_id = getattr(item, "id_", None) or getattr(item, "id", None)
        items.append({
            "id": item_id,
            "title": item.name,
            "url": f"https://jp.mercari.com/item/{item_id}",
            "image": item.thumbnails[0] if item.thumbnails else "",
            "price": item.price,
        })

    return items


def fetch_listings():
    print("=" * 60)
    print("Starting fetch...")
    print(f"Keyword: {KEYWORD}")
    print("=" * 60)

    try:
        items = asyncio.run(_fetch())
    except Exception as e:
        print(f"[!] Request failed: {e}")
        return []

    print(f"[+] Got {len(items)} listings")
    print("=" * 60)

    return items


if __name__ == "__main__":
    fetch_listings()
