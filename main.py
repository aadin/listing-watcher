
import json
from sources.example_source import fetch_listings
from notifiers.discord import notify

cfg=json.load(open("config.json"))
seen=set(json.load(open("seen.json")))
changed=False
for item in fetch_listings():
    if item["id"] in seen: continue
    seen.add(item["id"]); changed=True
    notify(cfg["webhook"], item)
if changed:
    json.dump(list(seen), open("seen.json","w"))
print("Done")
