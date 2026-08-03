
import requests
def notify(webhook,item):
    payload={"embeds":[{
        "title":item["title"],
        "url":item["url"],
        "image":{"url":item["image"]},
        "fields":[{"name":"Price","value":str(item["price"])}]
    }]}
    requests.post(webhook,json=payload,timeout=20)
