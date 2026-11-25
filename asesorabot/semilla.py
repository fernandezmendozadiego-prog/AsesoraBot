"""Datos SIMULADOS para la demostración (mismas cifras que el documento del proyecto).

9 materias, 9 asesores, 16 sesiones por semana, semestre de 16 semanas.
El calendario se arma alrededor de la fecha de hoy para que siempre haya sesiones
pasadas (con asistencias) y futuras (para inscribirse).
Los nombres son inventados; los números de control no corresponden a personas reales.
"""
import random
from datetime import timedelta

from . import reglas, reloj
from .db import set_config

MATERIAS = [
    ("Álgebra Lineal", "Ciencias Básicas"),
    ("Cálculo Diferencial", "Ciencias Básicas"),
    ("Cálculo Integral", "Ciencias Básicas"),
    ("Contabilidad Financiera", "Ciencias Económico-Administrativas"),
    ("Física", "Ciencias Básicas"),
    ("Fundamentos de Programación", "Sistemas y Computación"),
    ("Probabilidad y Estadística", "Ciencias Básicas"),
    ("Programación Orientada a Objetos", "Sistemas y Computación"),
    ("Química", "Ciencias Básicas"),
]
CARRERAS = ["Ing. en Sistemas Computacionales", "Ing. Industrial", "Ing. en Gestión Empresarial", "Ing. Civil"]

# (no_control, nombre, carrera, semestre, materia, [(día, hora, aula), ...])
ASESORES = [
    ("22660101", "Óscar R.", "Ing. Industrial", 7, "Cálculo Diferencial", [(0, "13:00", "Aula 12")]),
    ("22660102", "Lucía M.", "Ing. en Sistemas Computacionales", 7, "Cálculo Integral",
     [(1, "13:00", "Aula 10"), (3, "13:00", "Aula 10")]),
    ("22660103", "Andrés P.", "Ing. Civil", 7, "Álgebra Lineal", [(0, "10:00", "Aula 5"), (2, "10:00", "Aula 5")]),
    ("22660104", "Daniela V.", "Ing. en Gestión Empresarial", 7, "Contabilidad Financiera", [(4, "12:00", "Aula 3")]),
    ("22660105", "Rodrigo L.", "Ing. Industrial", 5, "Física", [(1, "16:00", "Lab. de Física"), (3, "16:00", "Lab. de Física")]),
    ("22660106", "Paola G.", "Ing. en Sistemas Computacionales", 5, "Fundamentos de Programación",
     [(0, "16:00", "Centro de Cómputo"), (2, "16:00", "Centro de Cómputo")]),
    ("22660107", "Héctor A.", "Ing. Industrial", 7, "Probabilidad y Estadística", [(1, "11:00", "Aula 8"), (3, "11:00", "Aula 8")]),
    ("22660108", "Sofía N.", "Ing. en Sistemas Computacionales", 7, "Programación Orientada a Objetos",
     [(2, "13:00", "Centro de Cómputo"), (4, "13:00", "Centro de Cómputo")]),
    ("22660109", "Iván C.", "Ing. Civil", 5, "Química", [(0, "12:00", "Lab. de Química"), (2, "12:00", "Lab. de Química")]),
]
TUTORADOS = ["Jorge S.", "Brandon O.", "Valeria N.", "Fernanda C.", "Mariana T.", "Luis Á. Z.",
             "Karla R.", "Emilio G.", "Ana P. E.", "Diana F."]
NOMBRES = ["Alejandro", "Ximena", "Carlos", "Regina", "Miguel", "Camila", "José", "Renata", "Juan", "Valentina",
           "Ricardo", "Andrea", "Fernando", "Paulina", "Arturo", "Natalia", "Eduardo", "Abril", "Sergio", "Itzel",
           "Raúl", "Lorena", "Gerardo", "Montserrat", "Alan", "Elena", "Kevin", "Jimena", "Uriel", "Melissa"]
INICIALES = "ABCDEGHLMNOPRSTVZ"


def cargar(db, hoy=None, semilla=7):
    rng = random.Random(semilla)
    hoy = hoy or reloj.ahora()
    inicio = reloj.lunes_de(hoy) - timedelta(weeks=13)      # hoy cae en la semana 14 de 16
    fin = inicio + timedelta(weeks=15, days=4, hours=23, minutes=59, seconds=59)
    set_config(db, "semestre_inicio", reloj.txt(inicio))
    set_config(db, "semestre_fin", reloj.txt(fin))
    set_config(db, "periodo", "Agosto–Diciembre 2026")

    ids = {}
    for nombre, depto in MATERIAS:
        ids[nombre] = db.execute("INSERT INTO materias(nombre, departamento) VALUES (?,?)", (nombre, depto)).lastrowid

    personal = [("COORD001", "Coordinación del programa", "coord", None),
                ("TUTOR001", "Tutor(a) de ISC", "tutor", None),
                ("JEFCB001", "Jefatura de Ciencias Básicas", "jefatura", "Ciencias Básicas"),
                ("JEFSC001", "Jefatura de Sistemas y Computación", "jefatura", "Sistemas y Computación"),
                ("JEFEA001", "Jefatura de Ciencias Económico-Administrativas", "jefatura", "Ciencias Económico-Administrativas")]
    for nc, nombre, rol, depto in personal:
        db.execute("INSERT INTO usuarios(no_control, nombre, rol, departamento) VALUES (?,?,?,?)", (nc, nombre, rol, depto))

    alumnos = []
    for i, nombre in enumerate(TUTORADOS):
        nc = f"24660{200 + i:03d}"
        db.execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?,NULL)",
                   (nc, nombre, "alumno", "Ing. en Sistemas Computacionales", 3, "TUTOR001"))
        alumnos.append(nc)
    for i in range(140):
        nc = f"{rng.choice([23, 24, 25])}66{1000 + i:04d}"
        nombre = f"{rng.choice(NOMBRES)} {rng.choice(INICIALES)}."
        db.execute("INSERT INTO usuarios VALUES (?,?,?,?,?,NULL,NULL)",
                   (nc, nombre, "alumno", rng.choice(CARRERAS), rng.choice([1, 1, 3, 3, 5])))
        alumnos.append(nc)

    for nc, nombre, carrera, sem, materia, horarios in ASESORES:
        db.execute("INSERT INTO usuarios VALUES (?,?,?,?,?,NULL,NULL)", (nc, nombre, "asesor", carrera, sem))
        db.execute("INSERT INTO asesores VALUES (?,?,1,?)", (nc, ids[materia], reloj.txt(inicio)))
        for dia, hora, aula in horarios:
            hid = db.execute("INSERT INTO horarios(asesor, materia_id, dia, hora, aula, cupo) VALUES (?,?,?,?,?,15)",
                             (nc, ids[materia], dia, hora, aula)).lastrowid
            hh, mm = (int(x) for x in hora.split(":"))
            fecha = inicio + timedelta(days=dia, hours=hh, minutes=mm)
            while fecha <= fin:
                db.execute("INSERT INTO sesiones(horario_id, asesor, materia_id, inicio, aula, cupo) VALUES (?,?,?,?,?,15)",
                           (hid, nc, ids[materia], reloj.txt(fecha), aula))
                fecha += timedelta(days=7)

    # historia de las sesiones ya pasadas: ≈17 % canceladas (la mitad sin aviso) y asistencias
    pasadas = db.execute("SELECT * FROM sesiones WHERE inicio < ? ORDER BY inicio", (reloj.txt(hoy),)).fetchall()
    sin_alumnos = ids["Contabilidad Financiera"]
    for s in pasadas:
        inicio_s = reloj.dt(s["inicio"])
        if s["asesor"] != "22660104" and rng.random() < 0.17:
            tardia = rng.random() < 0.5
            cuando = inicio_s - (timedelta(minutes=40) if tardia else timedelta(days=1))
            db.execute("UPDATE sesiones SET estado='cancelada', motivo=?, cancelada_en=?, tardia=? WHERE id=?",
                       (rng.choice(["Examen del asesor", "Motivo de salud", "Actividad académica"]),
                        reloj.txt(cuando), int(tardia), s["id"]))
            continue
        # Contabilidad: poca demanda y ningún alumno la semana pasada (aparece en el reporte)
        desde_ant, hasta_ant = reglas.semana_anterior(hoy)
        vacia = s["materia_id"] == sin_alumnos and desde_ant <= inicio_s < hasta_ant
        n = rng.randint(4, 10)
        if s["materia_id"] == sin_alumnos:
            n = 0 if vacia else rng.randint(2, 4)
        asistentes = rng.sample(alumnos, n)
        faltistas = rng.sample([a for a in alumnos if a not in asistentes], rng.randint(0, 2))
        for a in asistentes + faltistas:
            db.execute("INSERT INTO inscripciones VALUES (?,?,?)",
                       (s["id"], a, reloj.txt(inicio_s - timedelta(days=rng.randint(1, 3)))))
        for a in asistentes:
            db.execute("INSERT INTO asistencias VALUES (?,?,?,?)",
                       (s["id"], a, reloj.txt(inicio_s + timedelta(minutes=rng.randint(2, 12))),
                        rng.choice([None, 3, 4, 4, 5, 5, 5])))

    # Daniela (Contabilidad) dio además sesiones de repaso antes de exámenes: ya llegó a su meta de 16 h
    semana = 3
    while reglas.horas_asesor(db, "22660104") < 16 and semana < 12:
        f = inicio + timedelta(weeks=semana, days=2, hours=12)
        sid = db.execute("INSERT INTO sesiones(asesor, materia_id, inicio, aula, cupo) VALUES (?,?,?,?,15)",
                         ("22660104", sin_alumnos, reloj.txt(f), "Aula 3")).lastrowid
        for a in rng.sample(alumnos, 3):
            db.execute("INSERT INTO inscripciones VALUES (?,?,?)", (sid, a, reloj.txt(f - timedelta(days=1))))
            db.execute("INSERT INTO asistencias VALUES (?,?,?,?)", (sid, a, reloj.txt(f + timedelta(minutes=5)), 5))
        semana += 3

    # inscripciones a las sesiones de los próximos 7 días
    futuras = db.execute("SELECT * FROM sesiones WHERE inicio >= ? AND inicio < ? ORDER BY inicio",
                         (reloj.txt(hoy), reloj.txt(hoy + timedelta(days=7)))).fetchall()
    llena_hecha = False
    for s in futuras:
        n = rng.randint(2, 11)
        if s["materia_id"] == ids["Cálculo Integral"] and not llena_hecha:
            n, llena_hecha = 15, True       # una sesión llena para la demostración
        for a in rng.sample(alumnos[10:], n):
            db.execute("INSERT INTO inscripciones VALUES (?,?,?)", (s["id"], a, reloj.txt(hoy)))

    # tutoría: dos canalizaciones previas
    db.execute("INSERT INTO canalizaciones(tutor, alumno, materia_id, creada) VALUES (?,?,?,?)",
               ("TUTOR001", alumnos[0], ids["Cálculo Diferencial"], reloj.txt(inicio + timedelta(weeks=9))))
    db.execute("INSERT INTO canalizaciones(tutor, alumno, materia_id, creada) VALUES (?,?,?,?)",
               ("TUTOR001", alumnos[1], ids["Fundamentos de Programación"], reloj.txt(hoy - timedelta(days=3))))
    for s in db.execute("SELECT id FROM sesiones WHERE materia_id=? AND estado='programada' AND inicio>=? AND inicio<?",
                        (ids["Cálculo Diferencial"], reloj.txt(inicio + timedelta(weeks=9)), reloj.txt(hoy))).fetchall():
        db.execute("INSERT OR IGNORE INTO asistencias VALUES (?,?,?,5)", (s["id"], alumnos[0], reloj.txt(hoy)))

    # aspirantes pendientes
    db.execute("INSERT INTO aspirantes(no_control, semestre, materia_id, disponibilidad, creada) VALUES (?,?,?,?,?)",
               (alumnos[4], 5, ids["Física"], "martes y jueves", reloj.txt(hoy - timedelta(days=1))))
    db.execute("UPDATE usuarios SET semestre=5 WHERE no_control=?", (alumnos[4],))
    db.commit()

    # constancias que ya se generaron (quien llegó a su meta antes de hoy)
    for nc, *_ in ASESORES:
        reglas.revisar_constancia(db, nc, hoy)
    # no reenviar avisos automáticos de días anteriores
    db.execute("INSERT OR IGNORE INTO enviados VALUES (?,?)",
               (f"sem:{reglas.semana_anterior(hoy)[0]:%Y-%m-%d}", reloj.txt(hoy)))
    db.commit()
    return {"materias": len(MATERIAS), "asesores": len(ASESORES), "alumnos": len(alumnos),
            "sesiones": db.execute("SELECT COUNT(*) FROM sesiones").fetchone()[0],
            "asistencias": db.execute("SELECT COUNT(*) FROM asistencias").fetchone()[0]}
