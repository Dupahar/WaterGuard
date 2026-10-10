# contact sheet of review stills, labelled with their time. Usage: python sheet.py dir out.jpg [cols]
import sys, glob, os
from PIL import Image, ImageDraw
d, out = sys.argv[1], sys.argv[2]; cols = int(sys.argv[3]) if len(sys.argv) > 3 else 3
fs = sorted(glob.glob(os.path.join(d, '*.jpg')))
w, h = 640, 360
rows = (len(fs) + cols - 1) // cols
sheet = Image.new('RGB', (cols * (w + 4), rows * (h + 4)), 'white')
for i, f in enumerate(fs):
    im = Image.open(f).convert('RGB').resize((w, h))
    ImageDraw.Draw(im).text((8, 8), os.path.basename(f)[1:-4], fill=(255, 0, 255))
    sheet.paste(im, ((i % cols) * (w + 4), (i // cols) * (h + 4)))
sheet.save(out, quality=85)
