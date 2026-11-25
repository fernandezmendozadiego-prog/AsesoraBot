"""Modo local (polling): el bot le pregunta a Telegram «¿hay mensajes nuevos?» cada pocos segundos.

No abre puertos ni necesita IP pública, dominio o certificado. Sirve para desarrollar
en la computadora o para un servidor/contenedor siempre encendido.
    python local.py
"""
import logging
import time

from asesorabot import config, tareas
from asesorabot import db as base
from asesorabot.bot import Manejador
from asesorabot.telegram_api import BotAPI


def main():
    config.cargar_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not config.token():
        raise SystemExit("Falta BOT_TOKEN. Copia .env.ejemplo como .env y pega el token que te dio BotFather.")
    tg = BotAPI(config.token())
    yo = tg.yo()
    if not yo.get("ok"):
        raise SystemExit(f"Telegram rechazó el token: {yo.get('description')}")
    tg.quitar_webhook()  # polling y webhook no pueden estar activos a la vez
    con = base.conectar(config.db_path())
    bot = Manejador(con, tg, config.demo())
    logging.info("AsesoraBot (@%s) escuchando. Ctrl+C para detener.", yo["result"]["username"])
    offset, ultimo_tick = None, 0.0
    while True:
        try:
            for update in tg.actualizaciones(offset, espera=20):
                offset = update["update_id"] + 1
                try:
                    bot.procesar(update)
                except Exception:
                    logging.exception("Error con el update %s", update["update_id"])
            if time.time() - ultimo_tick >= 30:
                ultimo_tick = time.time()
                tareas.ejecutar(con, tg)
        except KeyboardInterrupt:
            break
        except Exception:
            logging.exception("Error general; reintento en 5 s")
            time.sleep(5)


if __name__ == "__main__":
    main()
