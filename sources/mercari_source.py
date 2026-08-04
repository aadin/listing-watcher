import asyncio

from mercapi import Mercapi
from mercapi.requests import SearchRequestData

# Multiple search queries to cast a wider net.  Each query is run
# independently and results are merged & deduplicated by item ID.
#
# Why multiple queries?
#   - Brand filter excluded listings where sellers didn't tag TAKARA TOMY.
#   - Category filter excluded mis-categorised listings.
#   - A single keyword missed related product lines (e.g. Super Control).
SEARCH_QUERIES = [
    {
        # Broad "Metal Fight Beyblade" search — NO category/brand restriction
        # so we catch mis-categorised or unbranded listings.
        "keyword": "メタルファイトベイブレード",
        "categories": [],
        "brands": [],
    },
    {
        # "Metal Fight" within spinning-tops category, without brand filter.
        # Catches items that only say "メタルファイト" without "ベイブレード"
        # in the title, while the category keeps results relevant.
        "keyword": "メタルファイト",
        "categories": [10817],  # こま (spinning tops)
        "brands": [],
    },
    {
        # Related product lines like the Super Control Beyblade RC toys,
        # which don't include "メタルファイト" in their title.
        "keyword": "スーパーコントロールベイブレード",
        "categories": [],
        "brands": [],
    },
]

MAX_PAGES = 3  # per query — ~120 items per page -> up to ~360 items per query


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


async def _run_single_query(m, query, status_filter):
    """Run one search query across up to MAX_PAGES pages."""
    keyword = query["keyword"]
    categories = query.get("categories", [])
    brands = query.get("brands", [])

    items = []
    page_token = None

    for page_num in range(1, MAX_PAGES + 1):
        search_kwargs = dict(
            sort_by=SearchRequestData.SortBy.SORT_CREATED_TIME,
            sort_order=SearchRequestData.SortOrder.ORDER_DESC,
            status=status_filter,
            page_token=page_token,
        )
        if categories:
            search_kwargs["categories"] = categories
        if brands:
            search_kwargs["brands"] = brands

        results = await m.search(keyword, **search_kwargs)

        page_items = results.items
        print(f"  [+] Page {page_num}: {len(page_items)} items")

        for item in page_items:
            status = getattr(item, "status", None)
            status_str = str(status).lower() if status is not None else ""
            if "sold" in status_str or "trading" in status_str:
                continue

            item_id = getattr(item, "id_", None) or getattr(item, "id", None)
            items.append({
                "id": item_id,
                "title": item.name,
                "url": f"https://jp.mercari.com/item/{item_id}",
                "image": item.thumbnails[0] if item.thumbnails else "",
                "price": item.price,
            })

        page_token = _find_next_page_token(results)
        if not page_token or not page_items:
            break

    return items


async def _fetch():
    m = Mercapi()
    status_filter = _on_sale_status_filter()

    seen_ids = set()
    all_items = []

    for idx, query in enumerate(SEARCH_QUERIES, 1):
        keyword = query["keyword"]
        categories = query.get("categories", [])
        brands = query.get("brands", [])
        print(f"\n[Query {idx}/{len(SEARCH_QUERIES)}] "
              f"keyword={keyword}  categories={categories}  brands={brands}")

        query_items = await _run_single_query(m, query, status_filter)

        new_count = 0
        for item in query_items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                all_items.append(item)
                new_count += 1

        print(f"  [+] {len(query_items)} results, {new_count} new (after dedup)")

    return all_items


def fetch_listings():
    print("=" * 60)
    print("Starting fetch...")
    print(f"Running {len(SEARCH_QUERIES)} search queries")
    print("=" * 60)

    try:
        items = asyncio.run(_fetch())
    except Exception as e:
        print(f"[!] Request failed: {e}")
        return []

    print(f"\n[+] Got {len(items)} unique listings total")
    print("=" * 60)

    return items


if __name__ == "__main__":
    fetch_listings()