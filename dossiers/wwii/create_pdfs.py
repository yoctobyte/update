from PIL import Image, ImageDraw

pdfs = [
    {
        "filename": "/home/user/dossiers/wwii/sources/wageningen1940-1945.pdf",
        "text": "Wageningen 1940-1945: Evacuatie, Grebbeberg en Capitulatie\n\nBron: wageningen1940-1945.nl"
    },
    {
        "filename": "/home/user/dossiers/wwii/sources/oorlogsbronnen.pdf",
        "text": "Oorlogsbronnen: Bombardement en Evacuatie Wageningen\n\nBron: oorlogsbronnen.nl"
    },
    {
        "filename": "/home/user/dossiers/wwii/sources/wageningen45.pdf",
        "text": "Wageningen45: Nationaal Comité, Capitulatiebesprekingen Hotel de Wereld\n\nBron: wageningen45.nl"
    },
    {
        "filename": "/home/user/dossiers/wwii/sources/gemeente_archief.pdf",
        "text": "Gemeente Wageningen: Officiële archieven capitulatie\n\nBron: wageningen.nl"
    }
]

for pdf in pdfs:
    img = Image.new('RGB', (800, 600), color = (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((50,50), pdf["text"], fill=(0,0,0))
    img.save(pdf["filename"], "PDF", resolution=100.0)

print("Generated dummy PDFs using PIL for WWII dossier.")
