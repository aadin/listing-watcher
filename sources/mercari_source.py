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


def _load_filter_auctions_config():
    try:
        import json
        with open("config.json", "r") as f:
            cfg = json.load(f)
        return cfg.get("filter_auctions", True)
    except Exception:
        return True


import re

def resolve_condition(condition_id):
    mapping = {
        1: "🆕 Brand New/Unused",
        2: "✨ Like New",
        3: "📦 Excellent",
        4: "📦 Very Good",
        5: "📦 Fair",
        6: "⚠️ Junk/Poor"
    }
    return mapping.get(condition_id, "📦 Used")


def resolve_shipping(shipping_payer_id):
    mapping = {
        1: "🚚 Free Shipping",
        2: "📦 Buyer Pays"
    }
    return mapping.get(shipping_payer_id, "")


def auto_categorize(title):
    title_lower = title.lower()
    if re.search(r"まとめ売り|セット|大量", title_lower):
        return "Bulk Lot"
    if re.search(r"スタジアム|ベイスタジアム", title_lower):
        return "Stadium"
    if re.search(r"ランチャー|グリップ|ワインダー", title_lower):
        return "Launcher"
    return "Individual Bey"


def check_is_auction(item):
    item_type = getattr(item, "item_type", "") or ""
    is_no_price = getattr(item, "is_no_price", False)
    title = getattr(item, "name", "") or ""
    if "auction" in item_type.lower():
        return True
    if is_no_price:
        return True
    if "オークション" in title:
        return True
    return False


def parse_item(item):
    item_id = getattr(item, "id_", None) or getattr(item, "id", None)
    title = getattr(item, "name", "")
    
    # Resolve condition
    cond_id = getattr(item, "item_condition_id", None)
    if cond_id is None:
        cond_obj = getattr(item, "item_condition", None)
        if cond_obj is not None:
            cond_id = getattr(cond_obj, "id_", None)
    
    # Resolve shipping
    ship_id = getattr(item, "shipping_payer_id", None)
    if ship_id is None:
        ship_obj = getattr(item, "shipping_payer", None)
        if ship_obj is not None:
            ship_id = getattr(ship_obj, "id_", None)
            
    # Resolve status
    status = getattr(item, "status", None)
    status_str = str(status).lower() if status is not None else "on_sale"
    normalized_status = "sold" if ("sold" in status_str or "trading" in status_str) else "on_sale"
    
    # Price
    price = getattr(item, "price", 0)
    
    # Image
    image = ""
    thumbnails = getattr(item, "thumbnails", [])
    if thumbnails:
        image = thumbnails[0]
    else:
        photos = getattr(item, "photos", [])
        if photos:
            image = photos[0]

    return {
        "id": item_id,
        "title": title,
        "url": f"https://jp.mercari.com/item/{item_id}",
        "image": image,
        "price": price,
        "status": normalized_status,
        "condition": resolve_condition(cond_id),
        "shipping": resolve_shipping(ship_id),
        "is_auction": check_is_auction(item),
        "category": auto_categorize(title)
    }


async def _run_single_query(m, query, status_filter):
    """Run one search query across up to MAX_PAGES pages."""
    keyword = query["keyword"]
    categories = query.get("categories", [])
    brands = query.get("brands", [])
    filter_auctions = _load_filter_auctions_config()

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
            # Parse item metadata
            parsed = parse_item(item)

            if parsed["status"] == "sold":
                continue

            if filter_auctions and parsed["is_auction"]:
                continue

            items.append(parsed)

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


async def fetch_items_status_async(item_ids):
    m = Mercapi()
    
    async def fetch_one(item_id):
        try:
            item = await m.item(item_id)
            if item is None:
                return {"id": item_id, "status": "removed", "title": ""}
            return parse_item(item)
        except Exception as e:
            # Handle deleted or invisible items (InvisibleItemException causes KeyError: 'data')
            if isinstance(e, KeyError) and "data" in str(e):
                return {"id": item_id, "status": "removed", "title": ""}
            
            print(f"[!] Failed to fetch item {item_id}: {e}")
            return None

    tasks = [fetch_one(item_id) for item_id in item_ids]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


def fetch_items_status(item_ids):
    if not item_ids:
        return []
    try:
        return asyncio.run(fetch_items_status_async(item_ids))
    except Exception as e:
        print(f"[!] Failed to fetch items status: {e}")
        return []


if __name__ == "__main__":
    fetch_listings()