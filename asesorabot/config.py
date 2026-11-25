"""Configuración por variables de entorno.

El token del bot NUNCA se escribe en el código: se lee de la variable BOT_TOKEN
(o del archivo .env, que no se sube al repositorio).
"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def cargar_env(ruta=None):
    """Lee un archivo .env sencillo (CLAVE=valor) sin dependencias externas."""
    ruta = Path(ruta) if ruta else BASE / ".env"
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            clave, valor = linea.split("=", 1)
            os.environ.setdefault(clave.strip(), valor.strip())


def token():
    return os.environ.get("BOT_TOKEN", "")


def db_path():
    return os.environ.get("DB_PATH", str(BASE / "datos" / "asesorabot.db"))


def carpeta_archivos():
    ruta = Path(os.environ.get("ARCHIVOS", str(BASE / "datos" / "archivos")))
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def webhook_secret():
    return os.environ.get("WEBHOOK_SECRET", "")


def tick_key():
    return os.environ.get("TICK_KEY", "")


def demo():
    """Modo demostración: habilita /demo para cambiar de rol con datos simulados."""
    return os.environ.get("DEMO", "1") == "1"
