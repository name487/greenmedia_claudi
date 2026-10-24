"""Preference (app → Settings): poster details, the business's story, photos, hashtags and audience — saved on the
client, read by the AI (brand voice), and used on posters (name, phone, address, logo, colour)."""

import io

from PIL import Image

from app import ai, ai_posts, media, preference
from app.db import SessionLocal
from app.models import Client


def _png(size=(400, 400), colour=(20, 120, 200)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", size, colour).save(b, "PNG")
    return b.getvalue()


def _photo(client, headers, slot, cid=1):
    return client.post(f"/api/clients/{cid}/preference/photos/{slot}", headers=headers, files={"image": ("p.png", _png(), "image/png")})


def test_defaults_sections_and_progress(client, portal):
    p = client.get("/api/clients/1/preference", headers=portal).json()
    v = p["values"]
    assert v["brand_name"] == "Smile Dental Studio" and v["phone_on_poster"] and v["address_on_poster"]
    assert v["target_gender"] == "Unisex" and v["hashtag_mode"] == "additional" and v["hashtags"] == []
    assert v["publish"] == {"gmb": True, "facebook": True, "instagram": True} and all(v["religious"].values())
    assert len(p["photos"]) == 12 and p["photos"]["interior_1"]["label"] == "Interior Photo - 1 (Entrance)"
    assert [s["platform"] for s in p["socials"]] == ["google", "facebook", "instagram"] and p["socials"][0]["connected"]
    assert p["choices"]["cta"][0] == "Call now" and p["labels"]["why_visit"] == "Why customer should visit you"
    prog = p["progress"]
    assert prog["total"] == 6 and prog["next"]["key"] in {"product", "logo"} and prog["done"] == sum(s["done"] for s in prog["steps"])


def test_edit_fields_one_at_a_time(client, portal):
    out = client.patch("/api/clients/1/preference", headers=portal, json={"brand_name": " Smile Dental ", "cta": "Book now"}).json()
    assert out["values"]["brand_name"] == "Smile Dental" and out["values"]["cta"] == "Book now"
    out = client.patch("/api/clients/1/preference", headers=portal, json={
        "hashtags": ["#Pune", "best dentist", "#pune", "#SmileMakeover"], "hashtag_mode": "exact", "brand_color": "#0F7A45",
        "publish": {"facebook": False}, "religious": {"christian": False}, "website": "smiledental.in", "founder_in_promos": False}).json()
    v = out["values"]
    assert v["hashtags"] == ["#Pune", "#bestdentist", "#SmileMakeover"] and v["hashtag_mode"] == "exact"
    assert v["publish"] == {"gmb": True, "facebook": False, "instagram": True} and v["religious"]["christian"] is False and v["religious"]["hindu"]
    assert v["website"] == "https://smiledental.in" and v["founder_in_promos"] is False and v["brand_name"] == "Smile Dental"  # kept
    for bad in ({"cta": "Shout"}, {"brand_color": "green"}, {"publish": {"twitter": True}}, {"nonsense": 1}, {"why_visit": "x" * 301}):
        assert client.patch("/api/clients/1/preference", headers=portal, json=bad).status_code == 422, bad
    assert client.patch("/api/clients/1/preference", headers=portal, json={"hashtags": [f"#t{i}" for i in range(11)]}).status_code == 422
    assert client.patch("/api/clients/2/preference", headers=portal, json={}).status_code == 404


def test_photos_and_progress(client, portal):
    before = client.get("/api/clients/1/preference", headers=portal).json()["progress"]["done"]
    out = _photo(client, portal, "logo").json()
    assert out["photos"]["logo"]["url"].startswith("https://api.test/media/c1/") and out["progress"]["done"] == before + 1
    rel = out["photos"]["logo"]["url"].split("/media/")[1]
    _photo(client, portal, "interior_1")
    replaced = _photo(client, portal, "logo").json()["photos"]["logo"]["url"].split("/media/")[1]
    assert rel != replaced and not media.path_of(rel).exists()  # the old file is removed
    out = client.delete("/api/clients/1/preference/photos/logo", headers=portal).json()
    assert out["photos"]["logo"]["url"] is None and not media.path_of(replaced).exists()
    assert _photo(client, portal, "selfie").status_code == 404
    bad = client.post("/api/clients/1/preference/photos/team_1", headers=portal, files={"image": ("x.png", b"nope", "image/png")})
    assert bad.status_code == 422


def test_ai_and_posters_use_it(client, portal):
    client.patch("/api/clients/1/preference", headers=portal, json={
        "brand_name": "Smile Dental Pune", "phone_on_poster": "+91 90000 11111", "address_on_poster": "Baner Road, Pune",
        "different": "Same-day crowns made in our own lab", "landmark": "Opposite Baner Gaon bus stop", "audience": "Families",
        "cta": "Book now", "brand_color": "#0F7A45", "hashtags": ["#SmilePune"], "hashtag_mode": "exact"})
    _photo(client, portal, "logo")
    with SessionLocal() as db:
        c = db.get(Client, 1)
        voice = ai._voice(c.brand_voice)
        assert "Same-day crowns made in our own lab" in voice and "Opposite Baner Gaon bus stop" in voice and "audience Families" in voice
        assert "Call-to-action style: Book now" in voice
        b = ai_posts.business(c)
        assert b["name"] == "Smile Dental Pune" and b["phone"] == "+91 90000 11111" and b["address"] == "Baner Road, Pune"
        assert b["logo"] and b["color"] == "#0F7A45"
        photo = media.save_photo(1, _png((600, 600), (200, 80, 60)))
        poster = media.render_poster(1, photo, {"name": "Teeth Whitening", "price": "1499"}, b)
        with Image.open(media.path_of(poster)) as img:
            band = img.getpixel((10, 1340))
            assert img.size == (1080, 1350) and all(abs(x - y) <= 3 for x, y in zip(band, (15, 122, 69)))  # the brand colour band (JPEG)
    # an AI poster gets exactly the owner's hashtags
    item = client.post("/api/clients/1/items", headers=portal, files={"image": ("p.png", _png(), "image/png")}, data={"name": "Whitening"}).json()
    post = client.post("/api/clients/1/ai-posts/poster", headers=portal, json={"item_id": item["id"]}).json()
    assert post["hashtags"] == ["#SmilePune"]


def test_hashtag_helpers_and_publish_switches(client, portal):
    with SessionLocal() as db:
        c = db.get(Client, 1)
        assert preference.custom_hashtags(c, ["#a"]) == ["#a"]  # nothing chosen: the generated ones
        preference.update(c, {"hashtags": ["#Mine"], "hashtag_mode": "additional", "publish": {"facebook": False}})
        assert preference.custom_hashtags(c, ["#mine", "#Other"]) == ["#Mine", "#Other"]
        assert preference.with_hashtags("Great smiles #old #tags", ["#Mine"]) == "Great smiles\n\n#Mine"
        assert "facebook" not in ai_posts.platforms(c) and "gmb" in ai_posts.platforms(c)
        preference.update(c, {"publish": {"gmb": False, "instagram": False}})
        assert ai_posts.platforms(c) == ["gmb"]  # at least Google
