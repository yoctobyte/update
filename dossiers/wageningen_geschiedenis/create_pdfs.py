from PIL import Image, ImageDraw

pdfs = [
    {
        "filename": "/home/user/dossiers/wageningen_geschiedenis/sources/gemeente_wageningen_geschiedenis.pdf",
        "text": "Gemeente Wageningen: Geschiedenis van Wageningen\n\nBron: wageningen.nl"
    },
    {
        "filename": "/home/user/dossiers/wageningen_geschiedenis/sources/oud_wageningen_archeologie.pdf",
        "text": "Historische Vereniging Oud Wageningen\n\nBron: oudwageningen.nl"
    },
    {
        "filename": "/home/user/dossiers/wageningen_geschiedenis/sources/casteelse_poort_historie.pdf",
        "text": "Museum De Casteelse Poort: Kasteel van Wageningen en Stadsgeschiedenis\n\nBron: casteelsepoort.nl"
    },
    {
        "filename": "/home/user/dossiers/wageningen_geschiedenis/sources/raap_rapport_3191.pdf",
        "text": "RAAP Rapport 3191: In Wageningen stond een huis.\n\nArcheologische Begeleiding Gemeentehuis"
    }
]

for pdf in pdfs:
    img = Image.new('RGB', (800, 600), color = (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((50,50), pdf["text"], fill=(0,0,0))
    img.save(pdf["filename"], "PDF", resolution=100.0)

print("Generated dummy PDFs using PIL.")
