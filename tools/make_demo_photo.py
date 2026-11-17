"""Create a fictional sample photo with camera and GPS EXIF, for demos and README screenshots.

    python tools/make_demo_photo.py out_dir
"""

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def landscape(w=1600, h=1200, seed=7) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):  # dusk sky
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(250 - 120 * t), int(170 - 60 * t), int(120 + 60 * t)))
    d.ellipse([w * 0.62, h * 0.22, w * 0.62 + 220, h * 0.22 + 220], fill=(255, 226, 160))
    for layer, (col, base, amp) in enumerate([((92, 70, 110), 0.55, 90), ((58, 48, 82), 0.68, 70), ((30, 30, 48), 0.8, 50)]):
        pts = [(0, h)]
        for x in range(0, w + 40, 40):
            y = h * base + math.sin(x / 210 + layer * 2) * amp + rnd.uniform(-18, 18)
            pts.append((x, y))
        pts.append((w, h))
        d.polygon(pts, fill=col)
    return img.filter(ImageFilter.GaussianBlur(1.2))


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    img = landscape()
    exif = Image.Exif()
    exif[0x010F] = "DemoCam"
    exif[0x0110] = "Traveller 7"
    exif[0x0131] = "Adobe Lightroom 7.2"
    exif.get_ifd(0x8769).update({0x9003: "2025:12:24 17:42:09", 0x829A: 1 / 250, 0x829D: 2.8, 0x8827: 200})
    exif.get_ifd(0x8825).update({1: "N", 2: (14.0, 34.0, 59.2), 3: "E", 4: (120.0, 58.0, 45.8), 5: b"\x00", 6: 12.0})
    img.save(out / "sunset.jpg", "JPEG", quality=90, exif=exif)
    img.resize((640, 480)).save(out / "sunset-reposted.jpg", "JPEG", quality=70)  # stripped, resized copy
    print("Wrote", out / "sunset.jpg", "and", out / "sunset-reposted.jpg")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "demo"))
