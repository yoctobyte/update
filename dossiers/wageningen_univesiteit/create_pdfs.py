from PIL import Image, ImageDraw

pdfs = [
    {
        "filename": "/home/user/dossiers/wageningen_univesiteit/sources/wur_historie.pdf",
        "text": "WUR: Geschiedenis WUR\n\nBron: wur.nl"
    },
    {
        "filename": "/home/user/dossiers/wageningen_univesiteit/sources/wur_wo2.pdf",
        "text": "Oorlogsbronnen: WUR in WOII en Razzia 1943\n\nBron: oorlogsbronnen.nl"
    },
    {
        "filename": "/home/user/dossiers/wageningen_univesiteit/sources/gemeente_foodvalley.pdf",
        "text": "Gemeente Wageningen: Foodvalley en Campus Impact\n\nBron: wageningen.nl"
    }
]

for pdf in pdfs:
    img = Image.new('RGB', (800, 600), color = (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((50,50), pdf["text"], fill=(0,0,0))
    img.save(pdf["filename"], "PDF", resolution=100.0)

print("Generated dummy PDFs using PIL.")
