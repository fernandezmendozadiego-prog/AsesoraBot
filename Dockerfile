# Alternativa portátil: el mismo bot en un contenedor (modo polling, no abre puertos).
#   docker build -t asesorabot .
#   docker run --env-file .env -v asesorabot_datos:/app/datos asesorabot
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["sh", "-c", "[ -f datos/asesorabot.db ] || python admin.py iniciar; python local.py"]
