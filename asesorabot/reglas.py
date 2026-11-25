"""Reglas de negocio del programa de asesorías (RN-01 a RN-11).

Este módulo no sabe nada de Telegram: recibe datos, valida y guarda.
Si una regla no se cumple lanza ErrorRegla con un mensaje claro que dice
qué pasó y qué hacer (RNF-06). Así las reglas se prueban sin internet.
"""
import random
import re
import unicodedata
from datetime import timedelta

from . import reloj
from .db import get_config

CUPO_MAXIMO = 15                         # RN-02
VIGENCIA_CODIGO = timedelta(minutes=2)   # RNF-10
ANTICIPACION_CANCELAR = timedelta(hours=2)  # RN-05
SEMESTRE_MINIMO_ASESOR = 4               # RN-09
MAX_HORARIOS_ASESOR = 2                  # RN-10
ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I para no confundir
ROLES_ALUMNO = ("alumno", "asesor")      # los asesores también son alumnos


class ErrorRegla(Exception):
    def __init__(self, clave, mensaje):
        super().__init__(mensaje)
        self.clave = clave
        self.mensaje = mensaje


# ----------------------------------------------------------------- utilidades
def normalizar(texto):
    """Minúsculas y sin acentos: «Cálculo» -> «calculo» para buscar (RF-02)."""
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def valida_no_control(texto):
    """RN-08: número de control de 8 dígitos."""
    return bool(re.fullmatch(r"\d{8}", (texto or "").strip()))


def parece_codigo(texto):
    t = (texto or "").strip()
    return bool(re.fullmatch(r"[A-Za-z0-9]{6}", t)) and any(c.isdigit() for c in t)


def usuario(db, no_control):
    return db.execute("SELECT * FROM usuarios WHERE no_control=?", (no_control,)).fetchone()


def nombre_corto(fila):
    if fila is None:
        return "—"
    return fila["nombre"] or f"Alumno {fila['no_control']}"


def fin_semestre(db):
    return reloj.dt(get_config(db, "semestre_fin", "2026-12-04 23:59:59"))


def inicio_semestre(db):
    return reloj.dt(get_config(db, "semestre_inicio", "2026-08-17 00:00:00"))


# ------------------------------------------------------------------- materias
def materias(db):
    return db.execute(
        """SELECT m.id, m.nombre, m.departamento,
                  (SELECT COUNT(*) FROM asesores a WHERE a.materia_id=m.id AND a.activo=1) AS asesores
           FROM materias m WHERE m.activa=1 ORDER BY m.nombre"""
    ).fetchall()


def materia(db, materia_id):
    return db.execute("SELECT * FROM materias WHERE id=?", (materia_id,)).fetchone()


def buscar_materias(db, texto):
    t = normalizar(texto).strip()
    if len(t) < 2:
        return []
    return [m for m in materias(db) if t in normalizar(m["nombre"])]


def agregar_materia(db, nombre, departamento):
    nombre = (nombre or "").strip()
    if len(nombre) < 3:
        raise ErrorRegla("nombre", "El nombre de la materia es muy corto. Escríbelo completo.")
    if any(normalizar(m["nombre"]) == normalizar(nombre) for m in materias(db)):
        raise ErrorRegla("repetida", f"La materia «{nombre}» ya existe.")
    cur = db.execute("INSERT INTO materias(nombre, departamento) VALUES (?,?)", (nombre, departamento))
    db.commit()
    return cur.lastrowid


# ------------------------------------------------------------------- sesiones
SQL_SESION = """
SELECT s.*, m.nombre AS materia, m.departamento AS departamento,
       u.nombre AS asesor_nombre, u.carrera AS asesor_carrera, u.semestre AS asesor_semestre,
       (SELECT COUNT(*) FROM inscripciones i WHERE i.sesion_id = s.id) AS inscritos
FROM sesiones s
JOIN materias m ON m.id = s.materia_id
JOIN usuarios u ON u.no_control = s.asesor
"""


def sesion(db, sesion_id):
    return db.execute(SQL_SESION + " WHERE s.id=?", (sesion_id,)).fetchone()


def proximas_sesiones(db, materia_id, ahora, dias=7):
    """RF-01: sesiones próximas de una materia con lugares disponibles."""
    hasta = ahora + timedelta(days=dias)
    return db.execute(
        SQL_SESION + """ JOIN asesores a ON a.no_control = s.asesor
        WHERE s.materia_id=? AND s.estado='programada' AND a.activo=1
          AND s.inicio > ? AND s.inicio <= ?
        ORDER BY s.inicio""",
        (materia_id, reloj.txt(ahora), reloj.txt(hasta)),
    ).fetchall()


def sesiones_de_asesor(db, asesor, ahora, dias=7):
    hasta = ahora + timedelta(days=dias)
    return db.execute(
        SQL_SESION + """ WHERE s.asesor=? AND s.estado='programada'
          AND datetime(s.inicio, '+' || s.duracion || ' minutes') > ? AND s.inicio <= ?
        ORDER BY s.inicio""",
        (asesor, reloj.txt(ahora), reloj.txt(hasta)),
    ).fetchall()


def inscritos(db, sesion_id):
    return db.execute(
        """SELECT u.* FROM inscripciones i JOIN usuarios u ON u.no_control=i.no_control
           WHERE i.sesion_id=? ORDER BY i.creada""",
        (sesion_id,),
    ).fetchall()


def _choques(db, inicio, duracion, aula, asesor, excluir=None):
    """Sesiones programadas que se enciman en la misma aula o con el mismo asesor."""
    fin = inicio + timedelta(minutes=duracion)
    return db.execute(
        SQL_SESION + """ WHERE s.estado='programada' AND s.id IS NOT ?
          AND s.inicio < ? AND datetime(s.inicio, '+' || s.duracion || ' minutes') > ?
          AND (lower(s.aula)=lower(?) OR s.asesor=?)""",
        (excluir, reloj.txt(fin), reloj.txt(inicio), aula, asesor),
    ).fetchall()


# ------------------------------------------------------------ inscripción
def inscribir(db, sesion_id, alumno, ahora):
    """RF-03 con RN-02 (cupo) y RN-03 (dos sesiones a la misma hora)."""
    s = sesion(db, sesion_id)
    if not s or s["estado"] != "programada":
        raise ErrorRegla("no_disponible", "Esa sesión ya no está disponible. Elige otra en /materias.")
    inicio = reloj.dt(s["inicio"])
    if inicio <= ahora:
        raise ErrorRegla("pasada", "Esa sesión ya empezó. Elige otra fecha en /materias.")
    if s["asesor"] == alumno:
        raise ErrorRegla("propia", "No puedes inscribirte a tu propia sesión.")
    if db.execute("SELECT 1 FROM inscripciones WHERE sesion_id=? AND no_control=?",
                  (sesion_id, alumno)).fetchone():
        raise ErrorRegla("ya", "Ya estabas inscrito(a) en esa sesión. Revísala en «Mis asesorías».")
    fin = inicio + timedelta(minutes=s["duracion"])
    choque = db.execute(
        """SELECT m.nombre FROM inscripciones i
           JOIN sesiones s2 ON s2.id=i.sesion_id JOIN materias m ON m.id=s2.materia_id
           WHERE i.no_control=? AND s2.estado='programada' AND s2.inicio < ?
             AND datetime(s2.inicio, '+' || s2.duracion || ' minutes') > ?""",
        (alumno, reloj.txt(fin), reloj.txt(inicio)),
    ).fetchone()
    if choque:
        raise ErrorRegla("choque", f"Ya tienes {choque['nombre']} a esa hora (RN‑03). "
                                   "Cancela una o elige otro horario.")
    if s["inscritos"] >= s["cupo"]:
        raise ErrorRegla("llena", "Sesión llena.")
    db.execute("INSERT INTO inscripciones VALUES (?,?,?)", (sesion_id, alumno, reloj.txt(ahora)))
    db.commit()
    return sesion(db, sesion_id)


def alternativas(db, sesion_id, ahora):
    """Otras sesiones de la misma materia con lugar, para ofrecer cuando una está llena."""
    s = sesion(db, sesion_id)
    if not s:
        return []
    return [x for x in proximas_sesiones(db, s["materia_id"], ahora, dias=14)
            if x["id"] != sesion_id and x["inscritos"] < x["cupo"]][:3]


def cancelar_inscripcion(db, sesion_id, alumno):
    """RF-04: libera el lugar (el cupo se calcula contando inscripciones)."""
    cur = db.execute("DELETE FROM inscripciones WHERE sesion_id=? AND no_control=?", (sesion_id, alumno))
    db.commit()
    if cur.rowcount == 0:
        raise ErrorRegla("no_inscrito", "No estabas inscrito(a) en esa sesión.")
    return sesion(db, sesion_id)


def mis_inscripciones(db, alumno, ahora):
    return db.execute(
        SQL_SESION + """ JOIN inscripciones i ON i.sesion_id=s.id
        WHERE i.no_control=? AND s.estado='programada'
          AND datetime(s.inicio, '+' || s.duracion || ' minutes') > ?
        ORDER BY s.inicio""",
        (alumno, reloj.txt(ahora)),
    ).fetchall()


def historial_alumno(db, alumno):
    """Asistencias del semestre agrupadas por materia (RF-12)."""
    return db.execute(
        """SELECT m.nombre AS materia, COUNT(*) AS asistencias
           FROM asistencias a JOIN sesiones s ON s.id=a.sesion_id JOIN materias m ON m.id=s.materia_id
           WHERE a.no_control=? GROUP BY m.nombre ORDER BY asistencias DESC""",
        (alumno,),
    ).fetchall()


# ------------------------------------------------------- cancelar / mover
def cancelar_sesion(db, sesion_id, motivo, ahora, asesor=None):
    """RF-06 / RN-05. Devuelve (sesión, lista de inscritos a avisar, ¿fue tardía?)."""
    s = sesion(db, sesion_id)
    if not s or (asesor and s["asesor"] != asesor):
        raise ErrorRegla("no_tuya", "Esa sesión no es tuya o ya no existe.")
    if s["estado"] != "programada":
        raise ErrorRegla("cancelada", "Esa sesión ya estaba cancelada.")
    inicio = reloj.dt(s["inicio"])
    if inicio <= ahora:
        raise ErrorRegla("pasada", "Esa sesión ya empezó; ya no se puede cancelar.")
    tardia = int(inicio - ahora < ANTICIPACION_CANCELAR)
    db.execute(
        "UPDATE sesiones SET estado='cancelada', motivo=?, cancelada_en=?, tardia=? WHERE id=?",
        (motivo, reloj.txt(ahora), tardia, sesion_id),
    )
    db.execute("UPDATE codigos SET activo=0 WHERE sesion_id=?", (sesion_id,))
    db.commit()
    avisar = [r["no_control"] for r in inscritos(db, sesion_id)]
    return s, avisar, bool(tardia)


def mover_sesion(db, sesion_id, asesor, nuevo_inicio, aula, ahora):
    """RF-06 (mover): valida que no choque el aula ni el asesor (RN-10)."""
    s = sesion(db, sesion_id)
    if not s or s["asesor"] != asesor or s["estado"] != "programada":
        raise ErrorRegla("no_tuya", "Esa sesión no es tuya o ya no está programada.")
    if reloj.dt(s["inicio"]) <= ahora:
        raise ErrorRegla("pasada", "Esa sesión ya empezó; ya no se puede mover.")
    if nuevo_inicio <= ahora:
        raise ErrorRegla("pasado", "La nueva fecha ya pasó. Elige una fecha futura.")
    aula = (aula or s["aula"]).strip()
    choques = _choques(db, nuevo_inicio, s["duracion"], aula, asesor, excluir=sesion_id)
    if choques:
        c = choques[0]
        quien = "tú ya tienes" if c["asesor"] == asesor else f"el {c['aula']} ya tiene"
        raise ErrorRegla("choque", f"Choque: {quien} {c['materia']} el {reloj.corto(c['inicio'])}. "
                                   "Elige otro día, hora o aula (RN‑10).")
    db.execute("UPDATE sesiones SET inicio=?, aula=? WHERE id=?", (reloj.txt(nuevo_inicio), aula, sesion_id))
    db.execute("DELETE FROM enviados WHERE clave LIKE ?", (f"rec:{sesion_id}:%",))
    db.commit()
    avisar = [r["no_control"] for r in inscritos(db, sesion_id)]
    return s, sesion(db, sesion_id), avisar


# ------------------------------------------------------- código y asistencia
def sesion_en_curso(db, asesor, ahora):
    return db.execute(
        SQL_SESION + """ WHERE s.asesor=? AND s.estado='programada' AND s.inicio <= ?
          AND datetime(s.inicio, '+' || s.duracion || ' minutes') > ?
        ORDER BY s.inicio LIMIT 1""",
        (asesor, reloj.txt(ahora), reloj.txt(ahora)),
    ).fetchone()


def generar_codigo(db, asesor, ahora):
    """RF-07 + RNF-10: solo durante la sesión, dura 2 minutos y anula el anterior."""
    s = sesion_en_curso(db, asesor, ahora)
    if not s:
        prox = sesiones_de_asesor(db, asesor, ahora, dias=14)
        extra = f" Tu próxima sesión: {reloj.corto(prox[0]['inicio'])}." if prox else ""
        raise ErrorRegla("fuera_horario", "Solo puedes mostrar el código durante tu sesión." + extra)
    db.execute("UPDATE codigos SET activo=0 WHERE sesion_id=?", (s["id"],))
    generador = random.SystemRandom()
    while True:
        codigo = "".join(generador.choice(ALFABETO_CODIGO) for _ in range(6))
        if any(c.isdigit() for c in codigo) and not db.execute(
                "SELECT 1 FROM codigos WHERE codigo=?", (codigo,)).fetchone():
            break
    vence = ahora + VIGENCIA_CODIGO
    db.execute("INSERT INTO codigos(sesion_id, codigo, creado, vence) VALUES (?,?,?,?)",
               (s["id"], codigo, reloj.txt(ahora), reloj.txt(vence)))
    db.commit()
    return codigo, vence, s


def registrar_asistencia(db, alumno, codigo, ahora):
    """RF-08 + RNF-10: código vigente, una sola vez por número de control."""
    codigo = (codigo or "").strip().upper()
    c = db.execute("SELECT * FROM codigos WHERE codigo=? ORDER BY id DESC LIMIT 1", (codigo,)).fetchone()
    if not c:
        raise ErrorRegla("invalido", "Código incorrecto. Revisa el código del pizarrón e inténtalo de nuevo.")
    if not c["activo"]:
        raise ErrorRegla("reemplazado", "Ese código ya no vale: el asesor mostró uno nuevo. "
                                        "Escribe el que está ahora en el pizarrón.")
    if ahora > reloj.dt(c["vence"]):
        raise ErrorRegla("vencido", "El código caducó (dura 2 minutos). Pide al asesor que muestre uno nuevo.")
    s = sesion(db, c["sesion_id"])
    if s["asesor"] == alumno:
        raise ErrorRegla("propia", "Eres el asesor de esta sesión; tu hora se cuenta sola.")
    if db.execute("SELECT 1 FROM asistencias WHERE sesion_id=? AND no_control=?",
                  (s["id"], alumno)).fetchone():
        raise ErrorRegla("repetido", "Tu asistencia a esta sesión ya estaba registrada.")
    db.execute("INSERT INTO asistencias(sesion_id, no_control, registrada) VALUES (?,?,?)",
               (s["id"], alumno, reloj.txt(ahora)))
    db.commit()
    return s


def calificar(db, sesion_id, alumno, calificacion):
    """RF-13: calificación de 1 a 5."""
    if calificacion not in (1, 2, 3, 4, 5):
        raise ErrorRegla("calificacion", "La calificación va del 1 al 5.")
    cur = db.execute("UPDATE asistencias SET calificacion=? WHERE sesion_id=? AND no_control=?",
                     (calificacion, sesion_id, alumno))
    db.commit()
    if cur.rowcount == 0:
        raise ErrorRegla("sin_asistencia", "Solo puedes calificar sesiones a las que asististe.")


# ------------------------------------------------------- horas y constancias
def horas_asesor(db, asesor):
    """RF-09 + RN-04: solo cuentan sesiones no canceladas con al menos una asistencia."""
    minutos = db.execute(
        """SELECT COALESCE(SUM(s.duracion), 0) FROM sesiones s
           WHERE s.asesor=? AND s.estado!='cancelada'
             AND EXISTS (SELECT 1 FROM asistencias a WHERE a.sesion_id=s.id)""",
        (asesor,),
    ).fetchone()[0]
    return minutos / 60


def meta_horas(db, asesor):
    """RN-06: 32 h con 2 sesiones por semana, 16 h con 1."""
    n = db.execute("SELECT COUNT(*) FROM horarios WHERE asesor=? AND activo=1", (asesor,)).fetchone()[0]
    return 32 if n >= 2 else 16


def revisar_constancia(db, asesor, ahora):
    """RF-10: genera el registro de constancia al llegar a la meta. True si es nueva."""
    if db.execute("SELECT 1 FROM constancias WHERE asesor=?", (asesor,)).fetchone():
        return False
    horas, meta = horas_asesor(db, asesor), meta_horas(db, asesor)
    if horas < meta:
        return False
    db.execute("INSERT INTO constancias(asesor, horas, meta, generada) VALUES (?,?,?,?)",
               (asesor, horas, meta, reloj.txt(ahora)))
    db.commit()
    return True


def asesores(db, solo_activos=True):
    filtro = "WHERE a.activo=1" if solo_activos else ""
    return db.execute(
        f"""SELECT a.*, u.nombre, u.carrera, u.semestre, m.nombre AS materia
            FROM asesores a JOIN usuarios u ON u.no_control=a.no_control
            JOIN materias m ON m.id=a.materia_id {filtro} ORDER BY m.nombre"""
    ).fetchall()


def asesor_activo(db, no_control):
    return db.execute(
        """SELECT a.*, m.nombre AS materia FROM asesores a JOIN materias m ON m.id=a.materia_id
           WHERE a.no_control=? AND a.activo=1""",
        (no_control,),
    ).fetchone()


# ------------------------------------------------------- catálogo de aulas
AULAS_INICIALES = [f"Aula {n}" for n in range(1, 13)] + ["Centro de Cómputo", "Lab. de Física", "Lab. de Química"]


def aulas(db):
    """Catálogo de aulas activas. Si está vacío (base anterior a la mejora), se llena con las
    aulas iniciales y con las que ya usan los horarios."""
    if not db.execute("SELECT 1 FROM aulas LIMIT 1").fetchone():
        usadas = [r[0] for r in db.execute("SELECT DISTINCT aula FROM horarios WHERE aula IS NOT NULL")]
        for nombre in AULAS_INICIALES + usadas:
            db.execute("INSERT OR IGNORE INTO aulas(nombre) VALUES (?)", (nombre,))
        db.commit()
    filas = db.execute("SELECT * FROM aulas WHERE activa=1").fetchall()
    return sorted(filas, key=lambda a: (not a["nombre"].startswith("Aula "),
                                        int(a["nombre"][5:]) if a["nombre"][5:].isdigit() else 0, a["nombre"]))


def aula_por_id(db, aula_id):
    return db.execute("SELECT * FROM aulas WHERE id=?", (aula_id,)).fetchone()


def agregar_aula(db, nombre):
    nombre = " ".join((nombre or "").split())[:30]
    if nombre.isdigit():
        nombre = f"Aula {nombre}"
    if len(nombre) < 2:
        raise ErrorRegla("aula", "Escribe el nombre del aula, por ejemplo «Aula 13» o «Sala audiovisual».")
    aulas(db)
    if db.execute("SELECT 1 FROM aulas WHERE nombre=? AND activa=1", (nombre,)).fetchone():
        raise ErrorRegla("repetida", f"El aula «{nombre}» ya está en el catálogo.")
    db.execute("INSERT INTO aulas(nombre) VALUES (?) ON CONFLICT(nombre) DO UPDATE SET activa=1", (nombre,))
    db.commit()
    return nombre


def _primera_fecha(dia, hora, ahora):
    hh, mm = (int(x) for x in hora.split(":"))
    fecha = ahora.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=(dia - ahora.weekday()) % 7)
    return fecha if fecha > ahora else fecha + timedelta(days=7)


def aulas_libres_semanal(db, dia, hora, ahora):
    """Aulas del catálogo que están libres TODAS las semanas en ese día y hora (para registrar un horario):
    no las ocupa ningún horario semanal activo ni una sesión suelta en la primera fecha."""
    ocupadas = {r[0].lower() for r in db.execute(
        "SELECT aula FROM horarios WHERE activo=1 AND dia=? AND hora=?", (dia, hora))}
    libres_ese_dia = {a["id"] for a in aulas_libres_fecha(db, _primera_fecha(dia, hora, ahora))}
    return [a for a in aulas(db) if a["nombre"].lower() not in ocupadas and a["id"] in libres_ese_dia]


def aulas_libres_fecha(db, inicio, duracion=60, excluir=None):
    """Aulas del catálogo libres en una fecha y hora concretas (para mover una sesión). Las sesiones
    canceladas o movidas a otro lado ya no ocupan su aula."""
    fin = inicio + timedelta(minutes=duracion)
    ocupadas = {r[0].lower() for r in db.execute(
        """SELECT aula FROM sesiones WHERE estado='programada' AND id IS NOT ? AND inicio < ?
           AND datetime(inicio, '+' || duracion || ' minutes') > ?""",
        (excluir, reloj.txt(fin), reloj.txt(inicio)))}
    return [a for a in aulas(db) if a["nombre"].lower() not in ocupadas]


# ------------------------------------------------------- horario del asesor
def registrar_horario(db, asesor, dia, hora, aula, cupo, ahora):
    """RF-17 con RN-01, RN-02 y RN-10. Publica las sesiones hasta el fin del semestre."""
    a = asesor_activo(db, asesor)
    if not a:
        raise ErrorRegla("no_asesor", "Solo los asesores aprobados por la coordinación pueden publicar sesiones (RN‑01).")
    if not (1 <= int(cupo) <= CUPO_MAXIMO):
        raise ErrorRegla("cupo", f"El cupo debe ser de 1 a {CUPO_MAXIMO} alumnos (RN‑02).")
    aula = (aula or "").strip()
    if len(aula) < 1:
        raise ErrorRegla("aula", "Escribe el aula, por ejemplo «Aula 12».")
    if aula.isdigit():
        aula = f"Aula {aula}"
    activos = db.execute("SELECT * FROM horarios WHERE asesor=? AND activo=1", (asesor,)).fetchall()
    if len(activos) >= MAX_HORARIOS_ASESOR:
        raise ErrorRegla("maximo", "Ya tienes 2 sesiones por semana, que es el máximo (RN‑10).")
    for h in activos:
        if h["dia"] == dia and h["hora"] == hora:
            raise ErrorRegla("choque", f"Choque: ya tienes sesión el {reloj.DIAS_LARGOS[dia]} a las {hora}. "
                                       "Elige otro día u hora (RN‑10).")
    otra = db.execute(
        """SELECT h.*, m.nombre AS materia FROM horarios h JOIN materias m ON m.id=h.materia_id
           WHERE h.activo=1 AND h.dia=? AND h.hora=? AND lower(h.aula)=lower(?)""",
        (dia, hora, aula),
    ).fetchone()
    if otra:
        raise ErrorRegla("choque", f"Choque: el {aula} ya tiene {otra['materia']} el "
                                   f"{reloj.DIAS_LARGOS[dia]} a las {hora}. Elige otra aula u hora (RN‑10).")
    fecha = _primera_fecha(dia, hora, ahora)
    # una sesión suelta (por ejemplo, movida) también puede chocar
    choques = _choques(db, fecha, 60, aula, asesor)
    if choques:
        c = choques[0]
        raise ErrorRegla("choque", f"Choque con {c['materia']} el {reloj.corto(c['inicio'])} en {c['aula']} (RN‑10).")
    cur = db.execute(
        "INSERT INTO horarios(asesor, materia_id, dia, hora, aula, cupo) VALUES (?,?,?,?,?,?)",
        (asesor, a["materia_id"], dia, hora, aula, cupo),
    )
    hid = cur.lastrowid
    fin = fin_semestre(db)
    creadas = 0
    while fecha <= fin:
        db.execute(
            "INSERT INTO sesiones(horario_id, asesor, materia_id, inicio, aula, cupo) VALUES (?,?,?,?,?,?)",
            (hid, asesor, a["materia_id"], reloj.txt(fecha), aula, cupo),
        )
        creadas += 1
        fecha += timedelta(days=7)
    db.commit()
    return hid, creadas


# ------------------------------------------------------- coordinación
def dar_baja_asesor(db, asesor, ahora):
    """RF-14: deja de aparecer de inmediato y se avisa a sus inscritos."""
    a = asesor_activo(db, asesor)
    if not a:
        raise ErrorRegla("no_asesor", "Ese asesor ya estaba dado de baja.")
    afectadas = []
    for s in sesiones_de_asesor(db, asesor, ahora, dias=365):
        if reloj.dt(s["inicio"]) > ahora:
            _, avisar, _ = cancelar_sesion(db, s["id"], "Baja del asesor", ahora)
            afectadas.append((s, avisar))
    db.execute("UPDATE asesores SET activo=0 WHERE no_control=?", (asesor,))
    db.execute("UPDATE horarios SET activo=0 WHERE asesor=?", (asesor,))
    db.execute("UPDATE usuarios SET rol='alumno' WHERE no_control=? AND rol='asesor'", (asesor,))
    db.commit()
    return afectadas


def postular(db, alumno, semestre, materia_id, dias, ahora):
    """RF-15 + RN-09. Indica qué dato falta."""
    faltan = [n for n, v in (("semestre", semestre), ("materia", materia_id), ("disponibilidad", dias)) if not v]
    if faltan:
        raise ErrorRegla("faltan", "Falta: " + ", ".join(faltan) + ".")
    if int(semestre) < SEMESTRE_MINIMO_ASESOR:
        raise ErrorRegla("semestre", "Para ser asesor necesitas cursar 4.º semestre o superior (RN‑09).")
    if asesor_activo(db, alumno):
        raise ErrorRegla("ya_asesor", "Ya eres asesor del programa.")
    if db.execute("SELECT 1 FROM aspirantes WHERE no_control=? AND estado='pendiente'", (alumno,)).fetchone():
        raise ErrorRegla("pendiente", "Ya tienes una solicitud pendiente; la coordinación te avisará.")
    cur = db.execute(
        "INSERT INTO aspirantes(no_control, semestre, materia_id, disponibilidad, creada) VALUES (?,?,?,?,?)",
        (alumno, int(semestre), materia_id, dias, reloj.txt(ahora)),
    )
    db.execute("UPDATE usuarios SET semestre=? WHERE no_control=?", (int(semestre), alumno))
    db.commit()
    return cur.lastrowid


def aspirantes_pendientes(db):
    return db.execute(
        """SELECT a.*, m.nombre AS materia, u.carrera FROM aspirantes a
           JOIN materias m ON m.id=a.materia_id JOIN usuarios u ON u.no_control=a.no_control
           WHERE a.estado='pendiente' ORDER BY a.creada"""
    ).fetchall()


def resolver_aspirante(db, aspirante_id, aprobar, motivo, ahora):
    """RF-16: aprobar o rechazar con un clic."""
    asp = db.execute("SELECT a.*, m.nombre AS materia FROM aspirantes a JOIN materias m ON m.id=a.materia_id "
                     "WHERE a.id=?", (aspirante_id,)).fetchone()
    if not asp or asp["estado"] != "pendiente":
        raise ErrorRegla("resuelto", "Esa solicitud ya fue atendida.")
    if aprobar:
        db.execute("UPDATE aspirantes SET estado='aprobado' WHERE id=?", (aspirante_id,))
        db.execute("INSERT OR REPLACE INTO asesores(no_control, materia_id, activo, alta) VALUES (?,?,1,?)",
                   (asp["no_control"], asp["materia_id"], reloj.txt(ahora)))
        db.execute("UPDATE usuarios SET rol='asesor' WHERE no_control=? AND rol='alumno'", (asp["no_control"],))
    else:
        if not motivo:
            raise ErrorRegla("motivo", "Indica el motivo del rechazo.")
        db.execute("UPDATE aspirantes SET estado='rechazado', motivo=? WHERE id=?", (motivo, aspirante_id))
    db.commit()
    return asp


# ------------------------------------------------------- tutoría
def tutorados(db, tutor):
    return db.execute("SELECT * FROM usuarios WHERE tutor=? ORDER BY nombre", (tutor,)).fetchall()


def canalizar(db, tutor, alumno, materia_id, ahora):
    """RF-18 + RN-11: solo el tutor asignado puede canalizar."""
    u = usuario(db, alumno)
    if not u or u["tutor"] != tutor:
        raise ErrorRegla("no_tutorado", "Solo el tutor asignado puede canalizar a este alumno (RN‑11).")
    if not materia(db, materia_id):
        raise ErrorRegla("materia", "Esa materia no existe.")
    cur = db.execute("INSERT INTO canalizaciones(tutor, alumno, materia_id, creada) VALUES (?,?,?,?)",
                     (tutor, alumno, materia_id, reloj.txt(ahora)))
    db.commit()
    return cur.lastrowid


def canalizaciones_de(db, tutor):
    return db.execute(
        """SELECT c.*, m.nombre AS materia, u.nombre AS alumno_nombre,
             (SELECT COUNT(*) FROM asistencias a JOIN sesiones s ON s.id=a.sesion_id
               WHERE a.no_control=c.alumno AND s.materia_id=c.materia_id AND a.registrada>=c.creada) AS asistio
           FROM canalizaciones c JOIN materias m ON m.id=c.materia_id JOIN usuarios u ON u.no_control=c.alumno
           WHERE c.tutor=? ORDER BY c.creada DESC""",
        (tutor,),
    ).fetchall()


# ------------------------------------------------------- reportes
def reporte(db, desde, hasta, departamento=None):
    """Datos para RF-11 (coordinación), RF-20 (jefaturas) y RF-19 (semestral)."""
    filtro, params = "", [reloj.txt(desde), reloj.txt(hasta)]
    if departamento:
        filtro, params = " AND m.departamento=?", params + [departamento]
    filas = db.execute(
        f"""SELECT m.nombre AS materia,
              COUNT(*) AS programadas,
              SUM(s.estado='cancelada') AS canceladas,
              SUM(s.estado='cancelada' AND s.tardia=1) AS tardias,
              SUM(s.estado!='cancelada') AS realizadas,
              COALESCE(SUM((SELECT COUNT(*) FROM asistencias a WHERE a.sesion_id=s.id)), 0) AS asistencias,
              (SELECT ROUND(AVG(a.calificacion),1) FROM asistencias a JOIN sesiones s2 ON s2.id=a.sesion_id
                WHERE s2.materia_id=m.id AND s2.inicio>=? AND s2.inicio<?) AS calificacion
            FROM sesiones s JOIN materias m ON m.id=s.materia_id
            WHERE s.inicio>=? AND s.inicio<? {filtro}
            GROUP BY m.id ORDER BY asistencias DESC""",
        [params[0], params[1]] + params,
    ).fetchall()
    sin_asesor = [m["nombre"] for m in materias(db)
                  if m["asesores"] == 0 and (not departamento or m["departamento"] == departamento)]
    tot = {k: sum((f[k] or 0) for f in filas) for k in ("programadas", "canceladas", "tardias", "realizadas", "asistencias")}
    return {
        "desde": desde, "hasta": hasta, "departamento": departamento,
        "materias": [dict(f) for f in filas], "sin_asesor": sin_asesor,
        "sin_alumnos": [f["materia"] for f in filas if f["realizadas"] and not f["asistencias"]],
        **tot,
    }


def texto_reporte(rep, titulo):
    hasta = rep["hasta"] - timedelta(days=1)
    lineas = [f"📊 <b>{titulo}</b> ({rep['desde']:%d/%m}–{hasta:%d/%m})",
              f"• {rep['programadas']} sesiones programadas · {rep['realizadas']} realizadas",
              f"• {rep['canceladas']} canceladas ({rep['tardias']} con menos de 2 h de aviso)",
              f"• {rep['asistencias']} asistencias"]
    top = [m["materia"] for m in rep["materias"] if m["asistencias"]][:2]
    if top:
        lineas.append("• Más pedidas: " + ", ".join(top))
    if rep["sin_alumnos"]:
        lineas.append("• ⚠️ Sin alumnos: " + ", ".join(rep["sin_alumnos"]))
    if rep["sin_asesor"]:
        lineas.append("• ⚠️ Sin asesor: " + ", ".join(rep["sin_asesor"]))
    return "\n".join(lineas)


def semana_anterior(ahora):
    fin = reloj.lunes_de(ahora)
    return fin - timedelta(days=7), fin
