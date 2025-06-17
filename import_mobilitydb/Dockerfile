# Użyjemy oficjalnego obrazu Pythona
FROM python:3.9-slim-buster

# Ustaw katalog roboczy w kontenerze
WORKDIR /app/docker_db

# Kopiuj plik requirements.txt (jeśli będziesz mieć)
# COPY requirements.txt .

# Instaluj zależności Pythona
# RUN pip install -r requirements.txt

# Jeśli nie używasz requirements.txt, możesz zainstalować bezpośrednio:
RUN pip install psycopg2-binary pandas Pillow

# Skopiuj skrypty importujące
# COPY ./import_scripts/ /app/import_scripts/

# Tutaj możesz dodać kopiowanie skryptów, które będą używane do importu danych.
# Na razie kopiujemy tylko podstawowe narzędzia.
# Wszystkie Twoje pliki .py, .bag, foldery z obrazami będą dostępne poprzez wolumen mapowany w docker-compose.yml
# pod /app w kontenerze.
# Dodaj tę linię na końcu Dockerfile:
CMD ["tail", "-f", "/dev/null"]