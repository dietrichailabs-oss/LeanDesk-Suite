from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

COLORS = {
    "bg": (23, 24, 31),
    "panel": (35, 37, 47),
    "ivory": (245, 240, 230),
    "cobalt": (79, 124, 255),
    "copper": (217, 135, 74),
    "orchid": (193, 120, 232),
    "jade": (78, 201, 165),
    "amber": (240, 184, 75),
    "coral": (239, 125, 125),
    "muted": (169, 173, 186),
}


def font(size: int, bold: bool = False):
    choices = [
        Path(r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in choices:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def draw_logo(draw, box):
    x1, y1, x2, y2 = box
    w = x2 - x1
    h = y2 - y1
    draw.rounded_rectangle(
        box,
        radius=int(w * .18),
        fill=COLORS["panel"],
        outline=COLORS["copper"],
        width=max(3, int(w * .035)),
    )
    margin = int(w * .16)
    page = (x1 + margin, y1 + margin, x2 - margin, y2 - margin)
    draw.rounded_rectangle(page, radius=int(w * .07), fill=COLORS["ivory"])
    stripe_h = max(6, int(h * .045))
    colors = [COLORS["cobalt"], COLORS["jade"], COLORS["amber"], COLORS["orchid"]]
    for idx, color in enumerate(colors):
        yy = y1 + margin + int(h * (.15 + idx * .15))
        width = int((x2 - x1 - 2 * margin) * (0.78 if idx != 2 else 0.58))
        draw.rounded_rectangle(
            (x1 + margin + 18, yy, x1 + margin + 18 + width, yy + stripe_h),
            radius=stripe_h // 2,
            fill=color,
        )


def make_icon():
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw_logo(draw, (24, 24, 488, 488))
    image.save(ASSETS / "leandesk-suite-icon.png")
    image.save(
        ROOT / "lean_desk_suite.ico",
        format="ICO",
        sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(96,96),(128,128),(256,256)],
    )


def make_banner():
    image = Image.new("RGB", (1400, 360), COLORS["bg"])
    draw = ImageDraw.Draw(image)
    for x in range(0, 1400, 44):
        draw.line((x, 0, x, 360), fill=(31, 33, 42))
    for y in range(0, 360, 44):
        draw.line((0, y, 1400, y), fill=(31, 33, 42))
    draw_logo(draw, (60, 50, 320, 310))
    draw.text((370, 66), "LEANDESK", font=font(62, True), fill=COLORS["ivory"])
    draw.text((370, 132), "SUITE", font=font(78, True), fill=COLORS["copper"])
    draw.text((375, 225), "Lean tools. Fast work.", font=font(28), fill=COLORS["ivory"])
    labels = [("WRITER", "cobalt"), ("SHEETS", "jade"), ("SLIDES", "amber"), ("NOTES", "orchid"), ("DRAW", "coral")]
    x = 375
    for label, color in labels:
        draw.rounded_rectangle((x, 278, x + 142, 322), radius=16, fill=COLORS["panel"], outline=COLORS[color], width=2)
        draw.text((x + 71, 300), label, font=font(17, True), fill=COLORS[color], anchor="mm")
        x += 158
    draw.text((1190, 326), "DIETRICH AI LABS", font=font(15, True), fill=COLORS["muted"])
    image.save(ASSETS / "leandesk-suite-banner.png")


def make_social():
    image = Image.new("RGB", (1280, 640), COLORS["bg"])
    draw = ImageDraw.Draw(image)
    for x in range(0, 1280, 46):
        draw.line((x, 0, x, 640), fill=(31, 33, 42))
    for y in range(0, 640, 46):
        draw.line((0, y, 1280, y), fill=(31, 33, 42))
    draw_logo(draw, (785, 105, 1125, 445))
    draw.text((76, 76), "LEANDESK", font=font(70, True), fill=COLORS["ivory"])
    draw.text((76, 152), "SUITE", font=font(94, True), fill=COLORS["copper"])
    draw.text((82, 280), "A focused local office suite", font=font(33, True), fill=COLORS["ivory"])
    draw.text((82, 331), "without the account, cloud, or subscription baggage.", font=font(24), fill=COLORS["muted"])
    labels = [("Writer", "cobalt"), ("Sheets", "jade"), ("Slides", "amber"), ("Notes", "orchid"), ("Draw", "coral")]
    x = 82
    for label, color in labels:
        draw.rounded_rectangle((x, 409, x + 132, 463), radius=19, fill=COLORS["panel"], outline=COLORS[color], width=2)
        draw.text((x + 66, 436), label.upper(), font=font(17, True), fill=COLORS[color], anchor="mm")
        x += 145
    draw.line((82, 510, 690, 510), fill=COLORS["copper"], width=4)
    draw.text((82, 535), "LOCAL-FIRST  •  FAST  •  NO TELEMETRY  •  NO SUBSCRIPTION", font=font(18, True), fill=COLORS["ivory"])
    draw.text((82, 590), "DIETRICH AI LABS", font=font(17, True), fill=COLORS["muted"])
    draw.text((1110, 590), "PREVIEW 0.3", font=font(17, True), fill=COLORS["muted"])
    image.save(ASSETS / "leandesk-suite-social-preview.png")


if __name__ == "__main__":
    make_icon()
    make_banner()
    make_social()
    print("LeanDesk artwork created.")
