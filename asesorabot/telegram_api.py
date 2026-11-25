"""Cliente mínimo de la Bot API de Telegram.

Telegram y el bot se comunican con peticiones HTTPS que llevan JSON, por ejemplo:
  POST https://api.telegram.org/bot<TOKEN>/sendMessage
  {"chat_id": 123, "text": "Hola", "reply_markup": {"inline_keyboard": [[...]]}}
El cifrado (certificado HTTPS) lo pone Telegram; el bot no necesita uno propio.
"""
import logging

import requests

log = logging.getLogger("asesorabot.telegram")


def _teclado(botones):
    """[[("Texto", "dato"), ...], ...] -> formato inline_keyboard de Telegram."""
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in fila] for fila in botones]}


class BotAPI:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.http = requests.Session()  # respeta HTTPS_PROXY si el hosting lo define

    def _llamar(self, metodo, datos=None, archivos=None, timeout=30):
        try:
            if archivos:
                r = self.http.post(self.base + metodo, data=datos, files=archivos, timeout=timeout)
            else:
                r = self.http.post(self.base + metodo, json=datos or {}, timeout=timeout)
            j = r.json()
        except (requests.RequestException, ValueError) as e:
            log.error("Fallo al llamar %s: %s", metodo, e)
            return {"ok": False, "description": str(e)}
        if not j.get("ok"):
            log.warning("Telegram respondió error en %s: %s", metodo, j.get("description"))
        return j

    # --- mensajes
    def enviar(self, chat_id, texto, botones=None):
        datos = {"chat_id": chat_id, "text": texto, "parse_mode": "HTML", "disable_web_page_preview": True}
        if botones:
            datos["reply_markup"] = _teclado(botones)
        return self._llamar("sendMessage", datos)

    def editar(self, chat_id, message_id, texto, botones=None):
        datos = {"chat_id": chat_id, "message_id": message_id, "text": texto, "parse_mode": "HTML"}
        if botones:
            datos["reply_markup"] = _teclado(botones)
        return self._llamar("editMessageText", datos)

    def responder_boton(self, callback_id, texto=None):
        datos = {"callback_query_id": callback_id}
        if texto:
            datos["text"] = texto
        return self._llamar("answerCallbackQuery", datos)

    def enviar_archivo(self, chat_id, ruta, texto=None):
        with open(ruta, "rb") as f:
            datos = {"chat_id": chat_id}
            if texto:
                datos.update(caption=texto, parse_mode="HTML")
            return self._llamar("sendDocument", datos, archivos={"document": (ruta.name, f)}, timeout=60)

    # --- configuración
    def yo(self):
        return self._llamar("getMe")

    def poner_webhook(self, url, secreto):
        return self._llamar("setWebhook", {"url": url, "secret_token": secreto,
                                           "allowed_updates": ["message", "callback_query"]})

    def quitar_webhook(self):
        return self._llamar("deleteWebhook")

    def info_webhook(self):
        return self._llamar("getWebhookInfo")

    def poner_comandos(self, comandos):
        return self._llamar("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in comandos]})

    def actualizaciones(self, offset=None, espera=20):
        datos = {"timeout": espera, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            datos["offset"] = offset
        j = self._llamar("getUpdates", datos, timeout=espera + 10)
        return j.get("result", []) if j.get("ok") else []


class BotFalso:
    """Sustituto para pruebas: guarda lo que el bot «enviaría» sin usar internet."""

    def __init__(self):
        self.enviados = []   # (chat_id, texto, botones)
        self.archivos = []   # (chat_id, ruta, texto)
        self._id = 0

    def enviar(self, chat_id, texto, botones=None):
        self._id += 1
        self.enviados.append((chat_id, texto, botones or []))
        return {"ok": True, "result": {"message_id": self._id}}

    def editar(self, chat_id, message_id, texto, botones=None):
        return self.enviar(chat_id, texto, botones)

    def responder_boton(self, callback_id, texto=None):
        return {"ok": True}

    def enviar_archivo(self, chat_id, ruta, texto=None):
        self.archivos.append((chat_id, ruta, texto))
        return {"ok": True}

    # ayudas para las pruebas
    def a(self, chat_id):
        return [t for c, t, _ in self.enviados if c == chat_id]

    def ultimo(self, chat_id):
        msgs = [(t, b) for c, t, b in self.enviados if c == chat_id]
        return msgs[-1] if msgs else (None, [])

    def limpiar(self):
        self.enviados.clear()
        self.archivos.clear()
