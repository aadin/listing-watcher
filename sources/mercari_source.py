import asyncio

from mercapi import Mercapi
from mercapi.requests import SearchRequestData

KEYWORD = "beyblade metal fight"
MAX_PAGES = 3  # ~120 items per page -> up to ~360 items per run


def _find_next_page_token(results):
    # Different mercapi versions have exposed this under slightly different
    # names, so check a few possibilities defensively rather than assuming one.
    meta = getattr(results, "meta", None)
    if meta is None:
        return None
    for attr in ("next_page_token", "nextPageToken", "page_token", "pageToken"):
        token = getattr(meta, attr, None)
        if token:
            return token
    return None


async def _fetch():
    m = Mercapi()

    all_items = []
    page_token = None

    for page_num in range(1, MAX_PAGES + 1):
        results = await m.search(
            KEYWORD,
            sort_by=SearchRequestData.SortBy.SORT_CREATED_TIME,
            sort_order=SearchRequestData.SortOrder.ORDER_DESC,
            page_token=page_token,
        )

        page_items = results.items
        print(f"[+] Page {page_num}: {len(page_items)} items")

        for item in page_items:
            item_id = getattr(item, "id_", None) or getattr(item, "id", None)
            all_items.append({
                "id": item_id,
                "title": item.name,
                "url": f"https://jp.mercari.com/item/{item_id}",
                "image": item.thumbnails[0] if item.thumbnails else "",
                "price": item.price,
            })

        page_token = _find_next_page_token(results)
        if not page_token or not page_items:
            break

    return all_items


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

    print(f"[+] Got {len(items)} listings total")
    print("=" * 60)

    return items


if __name__ == "__main__":
    fetch_listings()