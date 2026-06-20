"""
# pendings_auto.py
* Se crea una baraja de años en la carpeta deck dividiendo "pendings_init.txt" en varios txts por años
* en "deck/" 
* se creara un txt por años detectados en el init
* En "E:\\_Internal\\2026\\23. resources.local.images\\2026-01\\2026-01-15 X"
* Se toma el año despues de "E:\\_Internal\\" y se añade al txt del año correspondiente en "deck/"
* "pendings_init.txt" esta en la misma carpeta que el script
"""

# pendings_auto.py

from pathlib import Path
import re

# Carpeta donde está el script
BASE_DIR = Path(__file__).parent

# Archivo origen
INIT_FILE = BASE_DIR / "pendings_init.txt"

# Carpeta destino
DECK_DIR = BASE_DIR / "deck"
DECK_DIR.mkdir(exist_ok=True)

# Regex para extraer el año después de E:\_Internal\
YEAR_PATTERN = re.compile(r"E:\\_Internal\\(\d{4})\\")

if not INIT_FILE.exists():
    print(f"No existe: {INIT_FILE}")
    raise SystemExit(1)

with open(INIT_FILE, "r", encoding="utf-8") as f:
    lines = f.readlines()

years_data = {}

for line in lines:
    line = line.rstrip()

    match = YEAR_PATTERN.search(line)
    if not match:
        continue

    year = match.group(1)

    if year not in years_data:
        years_data[year] = []

    years_data[year].append(line)

# Crear un txt por año
for year, entries in years_data.items():
    year_file = DECK_DIR / f"{year}.txt"

    with open(year_file, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(entry + "\n")

    print(f"{year}: {len(entries)} registros -> {year_file}")

print("Proceso completado.")