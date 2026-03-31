from PIL import Image, ImageDraw
import os

pdfs = [
    {
        "filename": "/home/user/dossiers/wageningse_politiek/sources/gemeenteraad_uitslagen.pdf",
        "text": "Gemeente Wageningen: Uitslagen Verkiezingen 2026 en Zetelverdeling\n\nBron: wageningen.nl"
    },
    {
        "filename": "/home/user/dossiers/wageningse_politiek/sources/college_bw.pdf",
        "text": "Gemeente Wageningen: Samenstelling College van B&W (Vermeulen, Vulpen, Hulshof)\n\nBron: wageningen.nl"
    }
]

os.makedirs("/home/user/dossiers/wageningse_politiek/sources", exist_ok=True)

for pdf in pdfs:
    img = Image.new('RGB', (800, 600), color = (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((50,50), pdf["text"], fill=(0,0,0))
    img.save(pdf["filename"], "PDF", resolution=100.0)

print("Generated dummy PDFs using PIL for Politics dossier.")
