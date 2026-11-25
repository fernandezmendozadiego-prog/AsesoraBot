"""Hora local y formatos de fecha.

México dejó de usar horario de verano en 2022, así que Matehuala está siempre en UTC-6.
Las fechas se guardan en SQLite como texto 'AAAA-MM-DD HH:MM:SS', que se puede
comparar y ordenar como texto.
"""
from datetime import datetime, timedelta, timezone

ZONA = timezone(timedelta(hours=-6))
FMT = "%Y-%m-%d %H:%M:%S"
DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
DIAS_LARGOS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

_fijo = None  # las pruebas fijan la hora para que sean repetibles


def ahora():
    if _fijo is not None:
        return _fijo
    return datetime.now(ZONA).replace(tzinfo=None, microsecond=0)


def fijar(momento):
    global _fijo
    _fijo = momento


def txt(momento):
    return momento.strftime(FMT)


def dt(texto):
    return datetime.strptime(texto, FMT)


def corto(momento):
    """'Lun 23/11 13:00'"""
    if isinstance(momento, str):
        momento = dt(momento)
    return f"{DIAS[momento.weekday()]} {momento:%d/%m %H:%M}"


def lunes_de(momento):
    base = momento.replace(hour=0, minute=0, second=0, microsecond=0)
    return base - timedelta(days=base.weekday())
