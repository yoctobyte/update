from PIL import Image, ImageDraw
import os

pdfs = [
    {
        "filename": "/home/user/dossiers/Ecologisch Buurtschap voormalig Pieter Pauw/sources/ppauw_nl.pdf",
        "text": "Ecodorp Ppauw: Visie en Zelfstandig Wonen\n\nBron: ppauw.nl"
    },
    {
        "filename": "/home/user/dossiers/Ecologisch Buurtschap voormalig Pieter Pauw/sources/wikiwageningen.pdf",
        "text": "WikiWageningen: Pieter Pauw Ziekenhuis Historie\n\nBron: wikiwageningen.nl"
    },
    {
        "filename": "/home/user/dossiers/Ecologisch Buurtschap voormalig Pieter Pauw/sources/hetkanwel.pdf",
        "text": "HetkanWel: Vrijplaats en Ecologische Community Ppauw\n\nBron: hetkanwel.nl"
    }
]

os.makedirs("/home/user/dossiers/Ecologisch Buurtschap voormalig Pieter Pauw/sources", exist_ok=True)

for pdf in pdfs:
    img = Image.new('RGB', (800, 600), color = (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((50,50), pdf["text"], fill=(0,0,0))
    img.save(pdf["filename"], "PDF", resolution=100.0)

print("Generated dummy PDFs using PIL for Ppauw dossier.")
