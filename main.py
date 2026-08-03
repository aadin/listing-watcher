import os
import json

from sources.example_source import fetch_listings
from notifiers.discord import notify

# Load config
with open("config.json", "r") as f:
    cfg = json.load(f)

# Use GitHub Secret if available, otherwise use config.json
webhook = os.getenv("DISCORD_WEBHOOK", cfg["webhook"])

# Load previously seen items
with open("seen.json", "r") as f:
    seen = set(json.load(f))

changed = False

for item in fetch_listings():
    if item["id"] in seen:
        continue

    seen.add(item["id"])
    changed = True

    notify(webhook, item)

# Save updated seen list
if changed:
    with open("seen.json", "w") as f:
        json.dump(list(seen), f, indent=2)

print("Done")