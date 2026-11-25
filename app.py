"""Aplicación web para la nube (webhook).

Telegram manda cada mensaje por HTTPS a  https://<tu-usuario>.pythonanywhere.com/webhook
con un encabezado secreto; el bot responde llamando a la Bot API.
Un servicio de cron externo visita /tick cada minuto para las tareas programadas.
"""
import hmac
import logging

from flask import Flask, abort, jsonify, request

from asesorabot import config, tareas
from asesorabot import db as base
from asesorabot.bot import Manejador
from asesorabot.telegram_api import BotAPI

config.cargar_env()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("asesorabot.app")

app = Flask(__name__)
tg = BotAPI(config.token())


def _igual(a, b):
    return bool(b) and hmac.compare_digest(a or "", b)


@app.get("/")
def salud():
    return "AsesoraBot en línea ✅"


@app.post("/webhook")
def webhook():
    if not _igual(request.headers.get("X-Telegram-Bot-Api-Secret-Token"), config.webhook_secret()):
        abort(403)
    update = request.get_json(silent=True) or {}
    con = base.conectar(config.db_path())
    try:
        Manejador(con, tg, config.demo()).procesar(update)
        tareas.ejecutar(con, tg)
    except Exception:  # responder 200 siempre; si no, Telegram reintenta el mismo mensaje sin fin
        log.exception("Error al procesar el update %s", update.get("update_id"))
    finally:
        con.close()
    return "ok"


@app.route("/tick", methods=["GET", "POST"])
def tick():
    clave = request.headers.get("X-Tick-Key") or request.args.get("clave")
    if not _igual(clave, config.tick_key()):
        abort(403)
    con = base.conectar(config.db_path())
    try:
        return jsonify(tareas.ejecutar(con, tg))
    finally:
        con.close()


if __name__ == "__main__":
    app.run(host="localhost", port=5000)
