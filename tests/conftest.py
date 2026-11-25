import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from asesorabot import db as base, reglas, reloj, semilla  # noqa: E402
from asesorabot.bot import Manejador  # noqa: E402
from asesorabot.telegram_api import BotFalso  # noqa: E402

HOY = datetime(2026, 11, 22, 18, 0)  # domingo; el lunes 23/11 hay sesiones


class Escenario:
    """Base de datos simulada + bot falso + ayudas para «tocar botones» y «escribir»."""

    def __init__(self, demo=True):
        reloj.fijar(HOY)
        self.db = base.conectar(":memory:")
        semilla.cargar(self.db, HOY)
        self.tg = BotFalso()
        self.bot = Manejador(self.db, self.tg, demo=demo)

    def escribir(self, chat, texto):
        self.bot.procesar({"message": {"chat": {"id": chat, "type": "private"}, "text": texto}})
        return self.tg.ultimo(chat)

    def tocar(self, chat, dato):
        self.bot.procesar({"callback_query": {"id": "q", "data": dato,
                                              "message": {"message_id": 1, "chat": {"id": chat}}}})
        return self.tg.ultimo(chat)

    def como(self, chat, rol):
        self.tocar(chat, f"demo|{rol}")
        self.tg.limpiar()

    def alumno(self, chat, no_control):
        self.escribir(chat, "/start")
        self.escribir(chat, no_control)
        self.tg.limpiar()

    def hora(self, momento):
        reloj.fijar(momento)

    def materia_id(self, nombre):
        return self.db.execute("SELECT id FROM materias WHERE nombre=?", (nombre,)).fetchone()[0]

    def proxima(self, materia, con_lugar=True):
        ses = reglas.proximas_sesiones(self.db, self.materia_id(materia), reloj.ahora())
        return next(s for s in ses if (s["inscritos"] < s["cupo"]) == con_lugar)


@pytest.fixture
def esc(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHIVOS", str(tmp_path))
    e = Escenario()
    yield e
    reloj.fijar(None)


def botones(resp):
    return [b for fila in resp[1] for b in fila]


def textos_botones(resp):
    return [t for t, _ in botones(resp)]
