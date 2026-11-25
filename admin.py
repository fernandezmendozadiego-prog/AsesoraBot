"""Comandos de administración.

  python admin.py iniciar            crea la base de datos con los datos SIMULADOS de la demo
  python admin.py iniciar --vacia    crea la base de datos sin datos (uso real)
  python admin.py probar             verifica que el token funciona (getMe)
  python admin.py webhook URL        conecta Telegram con https://URL/webhook
  python admin.py invitar NOCONTROL  crea un enlace de alta para coordinación/tutor/jefatura
  python admin.py tick               ejecuta una vez las tareas programadas
"""
import secrets
import sys
from pathlib import Path

from asesorabot import config, semilla, tareas
from asesorabot import db as base
from asesorabot.telegram_api import BotAPI

COMANDOS = [("menu", "Ver mis opciones"), ("materias", "Asesorías por materia"),
            ("buscar", "Buscar materia por nombre"), ("mis", "Mis inscripciones"),
            ("codigo", "Registrar asistencia con el código"), ("postularme", "Quiero ser asesor"),
            ("ayuda", "Cómo usar el bot"), ("privacidad", "Qué datos guardamos"), ("demo", "Probar otro rol (demo)")]


def main(args):
    config.cargar_env()
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    if cmd == "iniciar":
        ruta = Path(config.db_path())
        if ruta.exists():
            ruta.unlink()
        con = base.conectar(str(ruta))
        if "--vacia" in args:
            print("Base de datos vacía creada en", ruta)
        else:
            print("Datos simulados cargados:", semilla.cargar(con), "en", ruta)
        return
    tg = BotAPI(config.token())
    if cmd == "probar":
        print(tg.yo())
    elif cmd == "webhook":
        url = args[1].rstrip("/") + "/webhook"
        print(tg.poner_webhook(url, config.webhook_secret()))
        print(tg.poner_comandos(COMANDOS))
        print(tg.info_webhook())
    elif cmd == "invitar":
        con = base.conectar(config.db_path())
        codigo = secrets.token_urlsafe(9)
        con.execute("INSERT INTO invitaciones VALUES (?,?,0)", (codigo, args[1]))
        con.commit()
        usuario = tg.yo().get("result", {}).get("username", "TU_BOT")
        print(f"Enlace de alta (un solo uso): https://t.me/{usuario}?start={codigo}")
    elif cmd == "tick":
        print(tareas.ejecutar(base.conectar(config.db_path()), tg))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
