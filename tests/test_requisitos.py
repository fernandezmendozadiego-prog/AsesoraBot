"""Casos de prueba PR-01 a PR-27 (uno por requisito, con su criterio de aceptación).
PR-27 se agregó por la observación de un usuario en la prueba de usabilidad PU-01.

Se ejecutan con:  python -m pytest -v
Usan datos SIMULADOS y un bot falso, así que no necesitan internet ni token.
"""
import re
import time
from datetime import datetime, timedelta
from html.parser import HTMLParser

import pytest

from asesorabot import reglas, reloj, tareas
from asesorabot.bot import Manejador
from conftest import HOY, Escenario, botones, textos_botones

LUNES_13 = datetime(2026, 11, 23, 13, 0)
OSCAR = "22660101"
A, B, ASESOR, COORD, TUTOR, JEFE = 100, 101, 200, 300, 400, 500


def inscribir_en_oscar(esc, chat, no_control):
    esc.alumno(chat, no_control)
    s = esc.proxima("Cálculo Diferencial")
    esc.tocar(chat, f"ins|{s['id']}")
    return s


def codigo_de(esc, chat_asesor):
    texto, _ = esc.tocar(chat_asesor, "as_cod")
    return re.search(r"<b>([A-Z0-9]{6})</b>", texto).group(1)


def invitar(esc, chat, no_control, codigo):
    esc.db.execute("INSERT INTO invitaciones VALUES (?,?,0)", (codigo, no_control))
    esc.db.commit()
    esc.escribir(chat, f"/start {codigo}")
    esc.tg.limpiar()


# ---------------------------------------------------------------- RF-01
def test_PR01_ver_asesorias_por_materia(esc):
    esc.alumno(A, "24669901")
    resp = esc.escribir(A, "/materias")
    assert len([d for _, d in botones(resp) if d.startswith("ses|")]) == 9
    s = esc.proxima("Cálculo Diferencial")
    texto, _ = esc.tocar(A, f"ses|{s['materia_id']}")
    # los 5 datos: asesor, día, hora, aula y lugares disponibles
    assert "Óscar R." in texto and "Lun 23/11" in texto and "13:00" in texto and "Aula 12" in texto
    assert re.search(r"\d+ de 15</b> lugares", texto)


# ---------------------------------------------------------------- RF-02
def test_PR02_buscar_por_parte_del_nombre(esc):
    esc.alumno(A, "24669901")
    resp = esc.escribir(A, "calc")
    assert set(textos_botones(resp)) - {"↩︎ Menú"} == {"Cálculo Diferencial", "Cálculo Integral"}
    resp = esc.escribir(A, "QUIMICA")  # sin acento y en mayúsculas también la encuentra
    assert "Química" in textos_botones(resp)


# ---------------------------------------------------------------- RF-03
def test_PR03_inscribirse_con_cupo_y_sesion_llena(esc):
    esc.alumno(A, "24669901")
    s = esc.proxima("Cálculo Diferencial")
    texto, _ = esc.tocar(A, f"ins|{s['id']}")
    assert "Inscrito" in texto
    assert reglas.sesion(esc.db, s["id"])["inscritos"] == s["inscritos"] + 1  # el cupo baja en 1
    llena = esc.proxima("Cálculo Integral", con_lugar=False)
    resp = esc.tocar(A, f"ins|{llena['id']}")
    assert "Sesión llena" in resp[0]
    assert any(d.startswith("ins|") for _, d in botones(resp))  # ofrece otra sesión


def test_PR03b_no_dos_sesiones_a_la_misma_hora(esc):
    esc.alumno(A, "24669901")
    s = esc.proxima("Cálculo Diferencial")
    reglas.inscribir(esc.db, s["id"], "24669901", reloj.ahora())
    sid = esc.db.execute("INSERT INTO sesiones(asesor, materia_id, inicio, aula) VALUES (?,?,?,?)",
                         ("22660109", esc.materia_id("Química"), s["inicio"], "Aula 99")).lastrowid
    texto, _ = esc.tocar(A, f"ins|{sid}")
    assert "RN‑03" in texto


# ---------------------------------------------------------------- RF-04
def test_PR04_cancelar_inscripcion_libera_lugar(esc):
    s = inscribir_en_oscar(esc, A, "24669901")
    antes = reglas.sesion(esc.db, s["id"])["inscritos"]
    texto, _ = esc.tocar(A, f"baja|{s['id']}")
    assert "liberé tu lugar" in texto
    assert reglas.sesion(esc.db, s["id"])["inscritos"] == antes - 1


# ---------------------------------------------------------------- RF-05
def test_PR05_recordatorio_60_minutos_antes(esc):
    inscribir_en_oscar(esc, A, "24669901")
    esc.tg.limpiar()
    tareas.ejecutar(esc.db, esc.tg, datetime(2026, 11, 23, 11, 58, 59))
    assert not esc.tg.a(A)
    tareas.ejecutar(esc.db, esc.tg, datetime(2026, 11, 23, 12, 0, 30))  # entre 11:59 y 12:01
    assert any("Recordatorio" in t and "13:00" in t for t in esc.tg.a(A))
    tareas.ejecutar(esc.db, esc.tg, datetime(2026, 11, 23, 12, 1, 0))
    assert sum("Recordatorio" in t for t in esc.tg.a(A)) == 1  # no se repite


# ---------------------------------------------------------------- RF-06
def test_PR06_asesor_cancela_y_avisa_a_todos(esc):
    s = inscribir_en_oscar(esc, A, "24669901")
    inscribir_en_oscar(esc, B, "24669902")
    esc.como(ASESOR, "asesor")
    esc.como(COORD, "coord")
    esc.tg.limpiar()
    inicio = time.perf_counter()
    esc.tocar(ASESOR, f"as_cx|{s['id']}")
    texto, _ = esc.tocar(ASESOR, f"as_cm|{s['id']}|0")
    assert time.perf_counter() - inicio < 300  # menos de 5 minutos
    assert "Avisé a" in texto
    for chat in (A, B):  # 100 % de los inscritos con Telegram
        assert any("Sesión cancelada" in t for t in esc.tg.a(chat))
    assert any("Cancelación" in t for t in esc.tg.a(COORD))  # RN-05: se informa a la coordinación
    assert reglas.sesion(esc.db, s["id"])["tardia"] == 0


def test_PR06b_cancelacion_tardia_y_mover_sesion(esc):
    s = inscribir_en_oscar(esc, A, "24669901")
    esc.como(ASESOR, "asesor")
    esc.tg.limpiar()
    # mover: el martes a las 13:00 en el Aula 10 choca con Cálculo Integral
    esc.tocar(ASESOR, f"as_mh|{s['id']}|20261124|1300")
    texto, _ = esc.escribir(ASESOR, "Aula 10")
    assert "Choque" in texto
    esc.tocar(ASESOR, f"as_mh|{s['id']}|20261124|1500")
    texto, _ = esc.tocar(ASESOR, f"as_ma|{s['id']}|20261124|1500")
    assert "movida" in texto
    assert any("Sesión cambiada" in t and "Mar 24/11 15:00" in t for t in esc.tg.a(A))
    # cancelar con menos de 2 h queda marcado (RN-05)
    esc.hora(datetime(2026, 11, 24, 14, 0))
    _, _, tardia = reglas.cancelar_sesion(esc.db, s["id"], "Motivo de salud", reloj.ahora(), asesor=OSCAR)
    assert tardia


# ---------------------------------------------------------------- RF-07
def test_PR07_codigo_solo_durante_la_sesion(esc):
    esc.como(ASESOR, "asesor")
    texto, _ = esc.tocar(ASESOR, "as_cod")  # domingo, sin sesión en curso
    assert "Solo puedes mostrar el código durante tu sesión" in texto
    esc.hora(LUNES_13 + timedelta(minutes=10))
    texto, _ = esc.tocar(ASESOR, "as_cod")
    assert re.search(r"Código: <b>[A-Z0-9]{6}</b>", texto)


# ---------------------------------------------------------------- RF-08 / RNF-06
def test_PR08_registrar_asistencia_con_codigo(esc):
    inscribir_en_oscar(esc, A, "24669901")
    esc.como(ASESOR, "asesor")
    esc.hora(LUNES_13 + timedelta(minutes=5))
    texto, _ = esc.escribir(A, "ZZZZ99")
    assert "Código incorrecto. Revisa el código del pizarrón" in texto  # error claro (RNF-06)
    codigo = codigo_de(esc, ASESOR)
    texto, _ = esc.escribir(A, codigo.lower())
    assert "Asistencia registrada" in texto
    texto, _ = esc.escribir(A, codigo)
    assert "ya estaba registrada" in texto
    n = esc.db.execute("SELECT COUNT(*) FROM asistencias WHERE no_control='24669901'").fetchone()[0]
    assert n == 1  # una sola vez


# ---------------------------------------------------------------- RF-09 / RN-04
def test_PR09_horas_del_asesor_se_suman_solas(esc):
    esc.alumno(A, "24669901")
    esc.como(ASESOR, "asesor")
    antes = reglas.horas_asesor(esc.db, OSCAR)
    esc.tocar(ASESOR, "as_demo|0")  # sesión sin asistencia: no cuenta
    assert reglas.horas_asesor(esc.db, OSCAR) == antes
    esc.escribir(A, codigo_de(esc, ASESOR))
    assert reglas.horas_asesor(esc.db, OSCAR) == antes + 1


# ---------------------------------------------------------------- RF-10 / RN-06 / RN-07
def test_PR10_constancia_pdf_al_cumplir_la_meta(esc, tmp_path):
    from pypdf import PdfReader
    esc.alumno(A, "24669901")
    esc.como(ASESOR, "asesor")
    esc.como(COORD, "coord")
    meta = reglas.meta_horas(esc.db, OSCAR)
    assert meta == 16  # 1 sesión por semana
    for i in range(20):
        if reglas.horas_asesor(esc.db, OSCAR) >= meta:
            break
        esc.hora(HOY + timedelta(hours=i + 1))
        esc.tocar(ASESOR, "as_demo|0")
        esc.escribir(A, codigo_de(esc, ASESOR))
    assert esc.db.execute("SELECT 1 FROM constancias WHERE asesor=?", (OSCAR,)).fetchone()
    assert any("Constancia lista" in t for t in esc.tg.a(COORD))
    esc.tocar(COORD, f"co_pdf|{OSCAR}")
    ruta = esc.tg.archivos[-1][1]
    texto = PdfReader(str(ruta)).pages[0].extract_text()
    for dato in ("Óscar R.", "Cálculo Diferencial", "Agosto", "16 horas", "Firma del titular"):
        assert dato in texto


# ---------------------------------------------------------------- RF-11
def test_PR11_reporte_semanal_lunes_8(esc):
    esc.como(COORD, "coord")
    reglas.agregar_materia(esc.db, "Ecuaciones Diferenciales", "Ciencias Básicas")
    tareas.ejecutar(esc.db, esc.tg, datetime(2026, 11, 23, 7, 59))
    assert not esc.tg.a(COORD)
    tareas.ejecutar(esc.db, esc.tg, datetime(2026, 11, 23, 8, 0))
    tareas.ejecutar(esc.db, esc.tg, datetime(2026, 11, 23, 9, 0))
    reportes = [t for t in esc.tg.a(COORD) if "Reporte semanal" in t]
    assert len(reportes) == 1
    assert "asistencias" in reportes[0] and "canceladas" in reportes[0]
    assert "Sin asesor: Ecuaciones Diferenciales" in reportes[0]


# ---------------------------------------------------------------- RF-12
def test_PR12_tutor_consulta_asistencia(esc):
    esc.como(TUTOR, "tutor")
    texto, _ = esc.tocar(TUTOR, "tu_ver")
    assert "Jorge S.: Cálculo Diferencial" in texto
    # solo ve a sus tutorados, no a otros alumnos
    otro = esc.db.execute("SELECT nombre FROM usuarios WHERE tutor IS NULL AND rol='alumno' LIMIT 1").fetchone()[0]
    assert f"{otro}:" not in texto


# ---------------------------------------------------------------- RF-13
def test_PR13_calificar_asesoria(esc):
    esc.alumno(A, "24669901")
    esc.como(ASESOR, "asesor")
    esc.tocar(ASESOR, "as_demo|0")
    resp = esc.escribir(A, codigo_de(esc, ASESOR))
    assert "¿Cómo calificas" in resp[0]
    dato = [d for _, d in botones(resp) if d.startswith("cal|")][3]  # 4 estrellas
    esc.tocar(A, dato)
    sid = int(dato.split("|")[1])
    assert esc.db.execute("SELECT calificacion FROM asistencias WHERE sesion_id=?", (sid,)).fetchone()[0] == 4


# ---------------------------------------------------------------- RF-14
def test_PR14_baja_de_asesor_y_alta_de_materia(esc):
    inscribir_en_oscar(esc, A, "24669901")
    esc.como(COORD, "coord")
    texto, _ = esc.tocar(COORD, f"co_ba2|{OSCAR}")
    assert "Baja registrada" in texto
    assert reglas.proximas_sesiones(esc.db, esc.materia_id("Cálculo Diferencial"), reloj.ahora()) == []
    assert any("Sesión cancelada" in t for t in esc.tg.a(A))
    assert "Cálculo Diferencial (sin asesor)" in textos_botones(esc.escribir(A, "/materias"))
    esc.tocar(COORD, "co_nm")
    esc.escribir(COORD, "Ecuaciones Diferenciales")
    texto, _ = esc.tocar(COORD, "co_nd|0")
    assert "agregada" in texto
    assert any(m["nombre"] == "Ecuaciones Diferenciales" for m in reglas.materias(esc.db))


# ---------------------------------------------------------------- RNF-02 / RNF-09
def test_PR15_carga_50_usuarios_y_crecimiento(esc):
    db = esc.db
    for i in range(350):  # 500 alumnos en total
        db.execute("INSERT INTO usuarios(no_control, rol) VALUES (?, 'alumno')", (f"2766{i:04d}",))
    for i in range(21):  # 30 asesores en total, ~58 sesiones por semana
        nc = f"2166{i:04d}"
        m = reglas.materias(db)[i % 9]
        db.execute("INSERT INTO usuarios(no_control, nombre, rol) VALUES (?, ?, 'asesor')", (nc, f"Asesor {i}"))
        db.execute("INSERT INTO asesores VALUES (?,?,1,?)", (nc, m["id"], reloj.txt(HOY)))
        db.commit()
        for dia in (i % 5, (i + 2) % 5):
            reglas.registrar_horario(db, nc, dia, "17:00", f"Aula N{i}", 15, reloj.ahora())
    tiempos = []
    for u in range(50):
        chat = 10_000 + u
        for paso in ("/start", f"2766{u:04d}", "/materias", "calc"):
            t0 = time.perf_counter()
            esc.escribir(chat, paso)
            tiempos.append(time.perf_counter() - t0)
        s = esc.proxima("Física")
        t0 = time.perf_counter()
        esc.tocar(chat, f"ins|{s['id']}")
        tiempos.append(time.perf_counter() - t0)
    tiempos.sort()
    assert tiempos[int(len(tiempos) * 0.95)] <= 3.0  # 95 % en ≤ 3 s (sin contar la red)


# ---------------------------------------------------------------- RNF-03
def test_PR16_servicio_web_responde_y_no_se_cae(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "secreto-prueba")
    monkeypatch.setenv("TICK_KEY", "tick-prueba")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "web.db"))
    import app as web
    from asesorabot.telegram_api import BotFalso
    monkeypatch.setattr(web, "tg", BotFalso())
    c = web.app.test_client()
    assert c.get("/").status_code == 200
    assert c.post("/webhook", json={}).status_code == 403  # sin la clave de Telegram
    h = {"X-Telegram-Bot-Api-Secret-Token": "secreto-prueba"}
    assert c.post("/webhook", json={"message": {"chat": {"id": 1}, "text": "/start"}}, headers=h).status_code == 200
    assert c.post("/webhook", json={"callback_query": {"basura": True}}, headers=h).status_code == 200
    assert c.get("/tick?clave=otra").status_code == 403
    assert c.get("/tick", headers={"X-Tick-Key": "tick-prueba"}).status_code == 200


# ---------------------------------------------------------------- RNF-04
def test_PR17_solo_numero_de_control_y_datos_por_rol(esc):
    texto, _ = esc.escribir(A, "/start")
    assert "número de control" in texto
    texto, _ = esc.escribir(A, "2466")
    assert "8 dígitos" in texto
    esc.escribir(A, "24669901")
    todo = " ".join(esc.tg.a(A)).lower()
    for dato in ("correo", "teléfono", "curp", "dirección", "contraseña"):
        assert dato not in todo
    for dato in ("co_asp", "co_con", "as_cod", "tu_ver", "je_rep", f"co_ba2|{OSCAR}"):
        texto, _ = esc.tocar(A, dato)
        assert "no está disponible para tu rol" in texto
    # sin modo demo: nadie puede «tomar» un número de control ya vinculado
    real = Manejador(esc.db, esc.tg, demo=False)
    real.procesar({"message": {"chat": {"id": B, "type": "private"}, "text": "/start"}})
    real.procesar({"message": {"chat": {"id": B, "type": "private"}, "text": "24669901"}})
    assert "ya está vinculado a otra cuenta" in esc.tg.ultimo(B)[0]


# ---------------------------------------------------------------- RNF-07 (prueba automática de formato)
class _Etiquetas(HTMLParser):
    def __init__(self):
        super().__init__()
        self.pila, self.malas = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in ("b", "i"):
            self.malas.append(tag)
        self.pila.append(tag)

    def handle_endtag(self, tag):
        assert self.pila and self.pila.pop() == tag


def test_PR18_mensajes_validos_para_todos_los_clientes(esc):
    for chat, rol in ((A, "alumno"), (ASESOR, "asesor"), (TUTOR, "tutor"), (COORD, "coord"), (JEFE, "jefatura")):
        esc.tocar(chat, f"demo|{rol}")
    for dato in ("mat", "mis", "post", "as_hrs", "as_ins", "as_can", "tu_ver", "tu_can", "co_asp", "co_rep",
                 "co_con", "co_mat", "co_ba", "co_bs", "je_rep"):
        for chat in (A, ASESOR, TUTOR, COORD, JEFE):
            esc.tocar(chat, dato)
    tareas.ejecutar(esc.db, esc.tg, datetime(2026, 11, 23, 8, 0))
    assert len(esc.tg.enviados) > 50
    for _, texto, bts in esc.tg.enviados:
        assert len(texto) <= 4096  # límite de Telegram
        p = _Etiquetas()
        p.feed(texto)
        assert not p.malas and not p.pila  # solo <b> e <i>, bien cerradas
        for fila in bts:
            for _, dato in fila:
                assert len(dato.encode()) <= 64  # límite de callback_data


# ---------------------------------------------------------------- RNF-08
def test_PR19_instalacion_con_un_comando(tmp_path, monkeypatch, capsys):
    from pathlib import Path
    import admin
    from asesorabot import db as base
    monkeypatch.setenv("DB_PATH", str(tmp_path / "nueva.db"))
    admin.main(["iniciar"])
    con = base.conectar(str(tmp_path / "nueva.db"))
    assert con.execute("SELECT COUNT(*) FROM materias").fetchone()[0] == 9
    req = (Path(admin.__file__).parent / "requirements.txt").read_text(encoding="utf-8")
    for paquete in ("flask", "requests", "openpyxl", "reportlab"):
        assert paquete in req.lower()


# ---------------------------------------------------------------- RF-15 / RN-09
def test_PR20_postularse_como_asesor(esc):
    esc.alumno(A, "24669901")
    esc.como(COORD, "coord")
    esc.tocar(A, "post")
    texto, _ = esc.tocar(A, "p_sem|2")
    assert "4.º semestre" in texto
    esc.tocar(A, "post")
    esc.tocar(A, "p_sem|5")
    esc.tocar(A, f"p_mat|{esc.materia_id('Química')}")
    texto, _ = esc.tocar(A, "p_ok")
    assert "Falta: disponibilidad" in texto  # indica qué dato falta
    esc.tocar(A, "p_dia|1")
    esc.tocar(A, "p_dia|3")
    texto, _ = esc.tocar(A, "p_ok")
    assert "Solicitud enviada" in texto
    assert any(a["no_control"] == "24669901" for a in reglas.aspirantes_pendientes(esc.db))
    assert any("Nueva solicitud de asesor" in t for t in esc.tg.a(COORD))


# ---------------------------------------------------------------- RF-16
def test_PR21_aprobar_o_rechazar_aspirante(esc):
    for chat, nc in ((A, "24669901"), (B, "24669902")):
        esc.alumno(chat, nc)
        reglas.postular(esc.db, nc, 6, esc.materia_id("Química"), "lunes", reloj.ahora())
    esc.como(COORD, "coord")
    ids = {a["no_control"]: a["id"] for a in reglas.aspirantes_pendientes(esc.db)}
    esc.tocar(COORD, f"co_ap|{ids['24669901']}")
    assert any("¡Aprobado!" in t for t in esc.tg.a(A))
    assert reglas.usuario(esc.db, "24669901")["rol"] == "asesor"
    assert "Eres asesor(a) de <b>Química</b>" in esc.escribir(A, "/menu")[0]
    esc.tocar(COORD, f"co_re|{ids['24669902']}")
    esc.tocar(COORD, f"co_rm|{ids['24669902']}|0")
    assert any("no fue aprobada. Motivo: No ha aprobado la materia" in t for t in esc.tg.a(B))


# ---------------------------------------------------------------- RF-17 / RN-10
def test_PR22_registrar_horario_y_validar_choques(esc):
    esc.como(ASESOR, "asesor")

    def proponer(dia, hhmm, aula):
        esc.tocar(ASESOR, "as_hor")
        esc.tocar(ASESOR, f"as_hd|{dia}")
        esc.tocar(ASESOR, f"as_hh|{dia}|{hhmm}")
        esc.escribir(ASESOR, aula)
        return esc.tocar(ASESOR, "as_cupo|15")[0]

    assert "ya tienes sesión el lunes" in proponer(0, "1300", "Aula 12")
    assert "el Aula 10 ya tiene Cálculo Integral" in proponer(1, "1300", "Aula 10")
    assert "Publicado" in proponer(2, "1300", "Aula 12")
    ses = reglas.proximas_sesiones(esc.db, esc.materia_id("Cálculo Diferencial"), reloj.ahora())
    assert any(s["inicio"] == "2026-11-25 13:00:00" for s in ses)  # aparece al instante
    assert "máximo" in esc.tocar(ASESOR, "as_hor")[0]


# ---------------------------------------------------------------- RF-18 / RN-11
def test_PR23_canalizar_y_avisar_asistencia_al_tutor(esc):
    valeria, diana = "24660202", "24660209"
    esc.alumno(A, valeria)
    esc.alumno(B, diana)
    esc.como(TUTOR, "tutor")
    esc.como(ASESOR, "asesor")
    cd = esc.materia_id("Cálculo Diferencial")
    for chat, nc in ((A, valeria), (B, diana)):
        esc.tocar(TUTOR, f"tu_c2|{nc}|{cd}")
        texto, bts = esc.tg.ultimo(chat)
        assert "te recomienda asesoría de <b>Cálculo Diferencial</b>" in texto
        esc.tocar(chat, [d for _, d in botones((texto, bts)) if d.startswith("ins|")][0])
    # RN-11: otro tutor no puede canalizar a una tutorada ajena
    esc.db.execute("INSERT INTO usuarios(no_control, nombre, rol) VALUES ('TUTOR002', 'Otro tutor', 'tutor')")
    invitar(esc, 401, "TUTOR002", "inv-tutor2")
    assert "Solo el tutor asignado" in esc.tocar(401, f"tu_c2|{valeria}|{cd}")[0]
    # Valeria asiste y Diana no
    esc.hora(LUNES_13 + timedelta(minutes=5))
    esc.escribir(A, codigo_de(esc, ASESOR))
    esc.tg.limpiar()
    tareas.ejecutar(esc.db, esc.tg, LUNES_13 + timedelta(minutes=65))
    avisos = esc.tg.a(TUTOR)
    assert any("Valeria N. <b>asistió</b>" in t for t in avisos)
    assert any("Diana F. <b>no asistió</b>" in t for t in avisos)


# ---------------------------------------------------------------- RF-19
def test_PR24_informe_semestral_automatico(esc):
    from openpyxl import load_workbook
    esc.como(COORD, "coord")
    fin = reglas.fin_semestre(esc.db)
    tareas.ejecutar(esc.db, esc.tg, fin - timedelta(minutes=1))
    assert not esc.tg.archivos
    tareas.ejecutar(esc.db, esc.tg, fin + timedelta(minutes=1))
    tareas.ejecutar(esc.db, esc.tg, fin + timedelta(minutes=2))
    assert len(esc.tg.archivos) == 1 and esc.tg.archivos[0][0] == COORD
    wb = load_workbook(esc.tg.archivos[0][1])
    assert {"Resumen", "Por materia", "Sesiones", "Asesores"} <= set(wb.sheetnames)
    assert wb["Sesiones"].max_row > 200  # todas las sesiones del semestre, sin captura manual


# ---------------------------------------------------------------- RF-20
def test_PR25_reporte_por_jefatura(esc):
    from openpyxl import load_workbook
    invitar(esc, JEFE, "JEFSC001", "inv-sc")
    invitar(esc, JEFE + 1, "JEFCB001", "inv-cb")
    tareas.ejecutar(esc.db, esc.tg, datetime(2026, 11, 23, 8, 0))
    assert any("Sistemas y Computación" in t for t in esc.tg.a(JEFE))
    assert any("Ciencias Básicas" in t for t in esc.tg.a(JEFE + 1))
    esc.tocar(JEFE, "je_xs")
    wb = load_workbook(esc.tg.archivos[-1][1])
    materias = {f[0].value for f in wb["Por materia"].iter_rows(min_row=2)}
    assert materias and materias <= {"Fundamentos de Programación", "Programación Orientada a Objetos"}


# ---------------------------------------------------------------- RNF-10
def test_PR26_codigo_caduca_en_2_minutos_y_vale_una_vez(esc):
    esc.alumno(A, "24669901")
    esc.alumno(B, "24669902")
    esc.alumno(B + 1, "24669903")
    esc.como(ASESOR, "asesor")
    esc.hora(LUNES_13 + timedelta(minutes=10))
    codigo = codigo_de(esc, ASESOR)
    esc.hora(LUNES_13 + timedelta(minutes=12))            # 2:00 exactos: vale
    assert "Asistencia registrada" in esc.escribir(A, codigo)[0]
    esc.hora(LUNES_13 + timedelta(minutes=12, seconds=1))  # 2:01: se rechaza
    assert "caducó" in esc.escribir(B, codigo)[0]
    nuevo = codigo_de(esc, ASESOR)
    assert "ya no vale" in esc.escribir(B, codigo)[0]      # el anterior deja de valer
    assert "Asistencia registrada" in esc.escribir(B, nuevo)[0]
    assert "ya estaba registrada" in esc.escribir(A, nuevo)[0]  # una vez por número de control


# ------------------------------------------- RF-17 / RN-10 (mejora surgida de la prueba PU-01)
def test_PR27_aulas_libres_como_botones(esc):
    def id_aula(nombre):
        return esc.db.execute("SELECT id FROM aulas WHERE nombre=?", (nombre,)).fetchone()[0]

    esc.como(ASESOR, "asesor")
    s = esc.proxima("Cálculo Diferencial")             # lunes 23/11 13:00, Aula 12
    # mover al martes 24/11 13:00: el Aula 10 está ocupada por Cálculo Integral y no se ofrece
    resp = esc.tocar(ASESOR, f"as_mh|{s['id']}|20261124|1300")
    assert "Aula 7" in textos_botones(resp) and "Aula 10" not in textos_botones(resp)
    assert "✏️ Otra aula (escribir)" in textos_botones(resp)
    # si esa sesión se cancela, el Aula 10 queda libre ese día y ya se ofrece
    integral = esc.db.execute("SELECT id FROM sesiones WHERE aula='Aula 10' AND inicio='2026-11-24 13:00:00'").fetchone()[0]
    reglas.cancelar_sesion(esc.db, integral, "Examen del asesor", reloj.ahora(), asesor="22660102")
    resp = esc.tocar(ASESOR, f"as_mh|{s['id']}|20261124|1300")
    assert "Aula 10" in textos_botones(resp)
    texto, _ = esc.tocar(ASESOR, f"as_mva|{s['id']}|20261124|1300|{id_aula('Aula 10')}")
    assert "movida" in texto and reglas.sesion(esc.db, s["id"])["aula"] == "Aula 10"

    # horario semanal: el jueves 13:00 el Aula 10 sigue ocupada (el horario de Lucía sigue activo)
    esc.tocar(ASESOR, "as_hor")
    resp = esc.tocar(ASESOR, "as_hh|3|1300")
    assert "Aula 10" not in textos_botones(resp) and "Aula 7" in textos_botones(resp)
    assert "Aula 7" in esc.tocar(ASESOR, f"as_ha|{id_aula('Aula 7')}")[0]
    assert "Publicado" in esc.tocar(ASESOR, "as_cupo|15")[0]
    assert esc.db.execute("SELECT 1 FROM horarios WHERE asesor=? AND dia=3 AND aula='Aula 7'", (OSCAR,)).fetchone()

    # la coordinación agrega un aula al catálogo y aparece como opción
    esc.como(COORD, "coord")
    esc.tocar(COORD, "co_na")
    assert "agregada" in esc.escribir(COORD, "Sala audiovisual")[0]
    assert "ya está" in (esc.tocar(COORD, "co_na"), esc.escribir(COORD, "sala audiovisual"))[1][0]
    assert any(a["nombre"] == "Sala audiovisual" for a in reglas.aulas_libres_semanal(esc.db, 4, "10:00", reloj.ahora()))
