
import requests
def fetch_listings():
    r=requests.get("https://fakestoreapi.com/products",timeout=20)
    r.raise_for_status()
    out=[]
    for p in r.json():
        out.append({
            "id":str(p["id"]),
            "title":p["title"],
            "price":p["price"],
            "url":f"https://fakestoreapi.com/products/{p['id']}",
            "image":p["image"],
        })
    return out
