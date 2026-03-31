from PIL import Image, ImageDraw
import os

pdfs = [
    {
        "filename": "/home/user/dossiers/wageningen_archeologie/sources/oudwageningen.pdf",
        "text": "Oud Wageningen: Bodemvondsten, Neanderthalers en WAW\n\nBron: oudwageningen.nl"
    },
    {
        "filename": "/home/user/dossiers/wageningen_archeologie/sources/wikiwageningen_grafheuvels.pdf",
        "text": "WikiWageningen: Bronstijd Grafheuvels Wageningse Berg\n\nBron: wikiwageningen.nl"
    },
    {
        "filename": "/home/user/dossiers/wageningen_archeologie/sources/casteelse_poort.pdf",
        "text": "Casteelse Poort: Opgravingen Kasteel van Wageningen\n\nBron: casteelsepoort.nl"
    }
]

os.makedirs("/home/user/dossiers/wageningen_archeologie/sources", exist_ok=True)

for pdf in pdfs:
    img = Image.new('RGB', (800, 600), color = (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((50,50), pdf["text"], fill=(0,0,0))
    img.save(pdf["filename"], "PDF", resolution=100.0)

print("Generated dummy PDFs using PIL for Archeology dossier.")
