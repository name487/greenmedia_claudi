"""Files for AI posts: product photos (re-encoded on upload), branded posters, and short 9:16 "viral" videos rendered
frame by frame with Pillow and encoded with the ffmpeg binary bundled by imageio-ffmpeg."""

import io
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .config import settings

MAX_UPLOAD = 8 * 1024 * 1024
FPS = 24


class MediaError(Exception):
    pass


def root() -> Path:
    p = Path(settings.media_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def url(rel: str) -> str:
    return f"{settings.public_base_url}/media/{rel}" if rel else ""


def path_of(rel: str) -> Path:
    p = (root() / rel).resolve()
    if root().resolve() not in p.parents:
        raise MediaError("Bad media path")
    return p


def _new(client_id: int, ext: str) -> tuple[str, Path]:
    rel = f"c{client_id}/{uuid.uuid4().hex}.{ext}"
    p = root() / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return rel, p


def save_photo(client_id: int, data: bytes) -> str:
    """Re-encode an uploaded photo as JPEG (drops EXIF/location, rejects anything that isn't an image)."""
    if len(data) > MAX_UPLOAD:
        raise MediaError("Photo is too large — 8 MB at most")
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as e:  # noqa: BLE001 — any decoding problem means "not an image"
        raise MediaError("That file isn't a photo (use JPG, PNG or WebP)") from e
    img.thumbnail((1600, 1600))
    rel, p = _new(client_id, "jpg")
    img.save(p, "JPEG", quality=88)
    return rel


MAX_VIDEO = 75 * 1024 * 1024  # Google Business Profile: videos up to 75 MB and 30 seconds
VIDEO_EXTS = {"mp4", "mov", "m4v", "webm", "3gp"}


def save_profile_photo(client_id: int, data: bytes) -> str:
    """A photo for the Google profile: Google wants at least 250 x 250 px."""
    rel = save_photo(client_id, data)
    with Image.open(path_of(rel)) as img:
        if min(img.size) < 250:
            path_of(rel).unlink(missing_ok=True)
            raise MediaError("Photo is too small for Google — at least 250 × 250 pixels")
    return rel


def save_video(client_id: int, data: bytes, filename: str) -> tuple[str, str, float]:
    """Store an uploaded video as is and grab its first frame as the thumbnail. Returns (video_rel, thumb_rel, seconds)."""
    import re
    import subprocess

    from imageio_ffmpeg import get_ffmpeg_exe

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in VIDEO_EXTS:
        raise MediaError("Use an MP4 or MOV video")
    if len(data) > MAX_VIDEO:
        raise MediaError("Video is too large — 75 MB at most")
    rel, p = _new(client_id, ext)
    p.write_bytes(data)
    thumb, tp = _new(client_id, "jpg")
    r = subprocess.run([get_ffmpeg_exe(), "-y", "-loglevel", "info", "-i", str(p), "-frames:v", "1", "-vf", "scale='min(720,iw)':-2", str(tp)],
                       capture_output=True, text=True, timeout=60)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if r.returncode != 0 or not tp.exists() or not m:
        p.unlink(missing_ok=True)
        tp.unlink(missing_ok=True)
        raise MediaError("That file isn't a video we can read")
    seconds = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    if seconds > 30.5:
        p.unlink(missing_ok=True)
        tp.unlink(missing_ok=True)
        raise MediaError(f"Video is {round(seconds)} seconds — Google takes videos up to 30 seconds")
    return rel, thumb, seconds


def price_label(price: str) -> str:
    """"1499" → "Rs 1,499" (Indian grouping). The built-in font has no ₹ glyph, so ₹ becomes "Rs"."""
    raw = price.replace("₹", "").replace("Rs.", "").replace("Rs", "").replace(",", "").strip()
    if not raw.replace(".", "", 1).isdigit():
        return price.replace("₹", "Rs ").strip()
    whole, _, dec = raw.partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "Rs " + ",".join(groups + [tail]) + (f".{dec}" if dec else "")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _cover(img: Image.Image, w: int, h: int, zoom: float = 1.0, dx: float = 0.0) -> Image.Image:
    """Crop to fill w×h, optionally zoomed in and shifted horizontally (Ken Burns)."""
    scale = max(w / img.width, h / img.height) * zoom
    rw, rh = int(img.width * scale) + 1, int(img.height * scale) + 1
    r = img.resize((rw, rh), Image.BILINEAR)
    x = int((rw - w) / 2 + dx * (rw - w) / 2)
    y = (rh - h) // 2
    return r.crop((x, y, x + w, y + h))


def _contain(img: Image.Image, w: int, h: int, bg: tuple[int, int, int]) -> Image.Image:
    canvas = Image.new("RGB", (w, h), bg)
    c = img.copy()
    c.thumbnail((w, h))
    canvas.paste(c, ((w - c.width) // 2, (h - c.height) // 2))
    return canvas


def _wrap(draw: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=f) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _centered(draw, lines: list[str], f, cx: int, top: int, fill, gap: int = 8) -> int:
    y = top
    for line in lines:
        w = draw.textlength(line, font=f)
        draw.text((cx - w / 2, y), line, font=f, fill=fill)
        y += f.size + gap
    return y


def _logo(business: dict, size: int) -> Image.Image | None:
    """The owner's logo (Preference) as a round RGBA image, or None."""
    if not business.get("logo"):
        return None
    try:
        img = _cover(Image.open(path_of(business["logo"])).convert("RGB"), size, size)
    except (OSError, MediaError):
        return None
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def end_card(w: int, h: int, business: dict, colours: tuple[str, str]) -> Image.Image:
    """The branded last frame: name, phone and address on a white card."""
    bg, accent = _hex(colours[0]), _hex(colours[1])
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    d.ellipse((w * 0.62, -w * 0.25, w * 1.25, w * 0.38), fill=accent)
    m = int(w * 0.09)
    d.rounded_rectangle((m, int(h * 0.12), w - m, int(h * 0.86)), radius=int(w * 0.06), fill=(255, 255, 255))
    initials = "".join(x[0] for x in business["name"].split()[:2]).upper() or "•"
    r = int(w * 0.13)
    cx, cy = w // 2, int(h * 0.3)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=bg)
    logo = _logo(business, 2 * r)
    if logo:
        img.paste(logo, (cx - r, cy - r), logo)
    else:
        f = font(int(r * 0.9))
        d.text((cx - d.textlength(initials, font=f) / 2, cy - f.size * 0.62), initials, font=f, fill=accent)
    y = _centered(d, _wrap(d, business["name"], font(int(w * 0.075)), w - 3 * m), font(int(w * 0.075)), cx, int(h * 0.42), (20, 30, 40))
    if business.get("phone"):
        fp = font(int(w * 0.045))
        tw = d.textlength(business["phone"], font=fp)
        d.rounded_rectangle((cx - tw / 2 - 24, y + 24, cx + tw / 2 + 24, y + 24 + fp.size + 22), radius=40, outline=(20, 30, 40), width=3)
        d.text((cx - tw / 2, y + 35), business["phone"], font=fp, fill=(20, 30, 40))
        y += fp.size + 70
    if business.get("address"):
        _centered(d, _wrap(d, business["address"], font(int(w * 0.03)), w - 3 * m)[:3], font(int(w * 0.03)), cx, y + 10, (90, 100, 110))
    return img


# ---------- poster ----------

def render_poster(client_id: int, photo_rel: str, item: dict, business: dict, colours: tuple[str, str] = ("#0E1A3A", "#FFB400")) -> str:
    """1080×1350 poster: the product photo, its name and price, and the business's name and phone."""
    w, h = 1080, 1350
    bg, accent = _hex(business.get("color") or colours[0]), _hex(colours[1])  # the brand colour from Preference, if set
    img = Image.new("RGB", (w, h), (255, 255, 255))
    photo = Image.open(path_of(photo_rel)).convert("RGB")
    img.paste(_cover(photo, w, int(h * 0.68)), (0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, int(h * 0.68), w, h), fill=bg)
    if item.get("price"):
        fp = font(64)
        tag = price_label(item["price"])
        tw = d.textlength(tag, font=fp)
        d.rounded_rectangle((w - tw - 120, int(h * 0.68) - 60, w - 40, int(h * 0.68) + 50), radius=50, fill=accent)
        d.text((w - tw - 80, int(h * 0.68) - 40), tag, font=fp, fill=bg)
    y = _centered(d, _wrap(d, item["name"], font(72), w - 160)[:2], font(72), w // 2, int(h * 0.72) + 30, (255, 255, 255))
    if item.get("description"):
        y = _centered(d, _wrap(d, item["description"], font(36), w - 200)[:2], font(36), w // 2, y + 6, (210, 220, 235))
    line = " · ".join(x for x in (business["name"], business.get("phone", "")) if x)
    _centered(d, [line], font(38), w // 2, h - 90, accent)
    logo = _logo(business, 150)
    if logo:  # top-right, on a white ring
        d.ellipse((w - 200, 30, w - 30, 200), fill=(255, 255, 255))
        img.paste(logo, (w - 190, 40), logo)
    rel, p = _new(client_id, "jpg")
    img.save(p, "JPEG", quality=90)
    return rel


# ---------- video ----------

def render_video(client_id: int, photo_rels: list[str], template: dict, business: dict, progress: Callable[[int], None] = lambda s: None) -> tuple[str, str]:
    """Intro (template text) → each product photo with a slow zoom/pan → branded end card. Returns (video, thumbnail).
    progress(step) is called as the steps finish: 1 photos read, 2 framed, 3 details, 4 style, 5 encoded."""
    w = settings.video_width - settings.video_width % 2
    h = (w * 16 // 9) - (w * 16 // 9) % 2
    colours = (template["bg"], template["accent"])
    bg, accent = _hex(colours[0]), _hex(colours[1])
    photos = [Image.open(path_of(r)).convert("RGB") for r in photo_rels]
    if not photos:
        raise MediaError("Add at least one product photo")
    progress(1)
    framed = [_cover(p, w, h, 1.0) for p in photos]
    progress(2)
    card = end_card(w, h, business, colours)
    progress(3)
    intro_lines = [ln.replace("{business}", business["name"]).replace("{city}", business.get("city", "")) for ln in template["intro"]]
    progress(4)

    def intro(i: int, n: int) -> Image.Image:
        img = Image.new("RGB", (w, h), bg)
        d = ImageDraw.Draw(img)
        t = i / max(1, n - 1)
        shown = intro_lines[: max(1, int(t * len(intro_lines) * 1.4) + 1)]
        f = font(int(w * 0.11))
        y = h // 2 - (len(intro_lines) * (f.size + 18)) // 2
        for k, line in enumerate(shown):
            colour = accent if k % 2 else (255, 255, 255)
            y = _centered(d, [line.upper()], f, w // 2, y, colour, gap=18)
        return img

    def product(img: Image.Image, i: int, n: int, k: int) -> Image.Image:
        t = i / max(1, n - 1)
        motion = template.get("motion", "zoom")
        if motion == "pan":
            frame = _cover(img, w, h, 1.15, dx=(-1 + 2 * t) * (1 if k % 2 else -1))
        else:
            frame = _cover(img, w, h, 1.0 + 0.12 * t)
        d = ImageDraw.Draw(frame)
        d.rectangle((0, h - int(h * 0.08), w, h), fill=bg)
        _centered(d, [business["name"]], font(int(w * 0.045)), w // 2, h - int(h * 0.065), accent)
        return frame

    rel, p = _new(client_id, "mp4")
    from imageio_ffmpeg import get_ffmpeg_exe

    cmd = [get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "26", "-movflags", "+faststart", str(p)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        def put(frame: Image.Image) -> None:
            proc.stdin.write(frame.tobytes())  # type: ignore[union-attr]

        n = int(FPS * 2.2)
        for i in range(n):
            put(intro(i, n))
        for k, img in enumerate(framed[:6]):
            n = int(FPS * 1.8)
            for i in range(n):
                put(product(photos[k], i, n, k))
        for _ in range(int(FPS * 2.4)):
            put(card)
        proc.stdin.close()  # type: ignore[union-attr]
        if proc.wait(timeout=300) != 0:
            raise MediaError((proc.stderr.read() or b"").decode()[:300] or "Video encoding failed")  # type: ignore[union-attr]
    finally:
        if proc.poll() is None:
            proc.kill()
    progress(5)
    thumb_rel, tp = _new(client_id, "jpg")
    framed[0].save(tp, "JPEG", quality=85)
    return rel, thumb_rel
