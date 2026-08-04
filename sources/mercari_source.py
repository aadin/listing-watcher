import asyncio

from mercapi import Mercapi
from mercapi.requests import SearchRequestData

KEYWORD = "メタルファイト"  # narrows within the category to the "Metal Fight" era specifically
CATEGORY_IDS = [10817]  # こま (spinning tops) — the category m93948632826 lives in
BRAND_IDS = [10490]     # TAKARA TOMY
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


def _on_sale_status_filter():
    # Try to find the "on sale only" status enum value defensively, since we
    # can't confirm the exact member name without a live environment.
    status_enum = getattr(SearchRequestData, "Status", None)
    if status_enum is None:
        return []
    for attr in ("ON_SALE", "STATUS_ON_SALE", "SELLING"):
        val = getattr(status_enum, attr, None)
        if val is not None:
            return [val]
    return []


async def _fetch():
    m = Mercapi()

    all_items = []
    page_token = None
    status_filter = _on_sale_status_filter()

    for page_num in range(1, MAX_PAGES + 1):
        results = await m.search(
            KEYWORD,
            categories=CATEGORY_IDS,
            brands=BRAND_IDS,
            sort_by=SearchRequestData.SortBy.SORT_CREATED_TIME,
            sort_order=SearchRequestData.SortOrder.ORDER_DESC,
            status=status_filter,
            page_token=page_token,
        )

        page_items = results.items
        print(f"[+] Page {page_num}: {len(page_items)} items")

        for item in page_items:
            status = getattr(item, "status", None)
            status_str = str(status).lower() if status is not None else ""
            if "sold" in status_str or "trading" in status_str:
                continue

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
    print(f"Category: {CATEGORY_IDS}  Brand: {BRAND_IDS}")
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