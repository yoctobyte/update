from PIL import Image, ImageDraw
import os

pdfs = [
    {
        "filename": "/home/user/dossiers/bestuurders_geschiedenis/sources/oudwageningen.pdf",
        "text": "Oud Wageningen: Historie en Burgemeesters van 1476\n\nBron: oudwageningen.nl"
    },
    {
        "filename": "/home/user/dossiers/bestuurders_geschiedenis/sources/mijngelderland_bestuur.pdf",
        "text": "MijnGelderland: Hertogdom Gelre en Ambtman Wageningen\n\nBron: mijngelderland.nl"
    },
    {
        "filename": "/home/user/dossiers/bestuurders_geschiedenis/sources/wikipedia_bestuur.pdf",
        "text": "Wikipedia: Geschiedenis en Lijst van Burgemeesters\n\nBron: wikipedia.org"
    }
]

os.makedirs("/home/user/dossiers/bestuurders_geschiedenis/sources", exist_ok=True)

for pdf in pdfs:
    img = Image.new('RGB', (800, 600), color = (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((50,50), pdf["text"], fill=(0,0,0))
    img.save(pdf["filename"], "PDF", resolution=100.0)

print("Generated dummy PDFs using PIL for Bestuurders dossier.")
