"""Tareas programadas. Se ejecutan cada minuto (ping a /tick) y también tras cada mensaje.

  RF-05  recordatorio 60 minutos antes de la sesión
  RF-18  aviso al tutor: «asistió» / «no asistió» al terminar la sesión
  RF-10  constancia en cuanto el asesor llega a su meta de horas
  RF-11  reporte semanal a la coordinación (lunes 8:00)
  RF-20  reporte semanal a cada jefatura, solo con sus materias (lunes 8:00)
  RF-19  informe semestral al cierre del semestre
Cada aviso se registra en la tabla «enviados» para no mandarlo dos veces.
"""
from datetime import timedelta

from . import documentos, reglas, reloj
from .avisos import avisar, avisar_rol, ya_enviado


def recordatorios(db, tg, ahora):
    n = 0
    proximas = db.execute(
        reglas.SQL_SESION + " WHERE s.estado='programada' AND s.inicio > ? AND s.inicio <= ?",
        (reloj.txt(ahora), reloj.txt(ahora + timedelta(minutes=60))),
    ).fetchall()
    for s in proximas:
        for alumno in reglas.inscritos(db, s["id"]):
            if ya_enviado(db, f"rec:{s['id']}:{alumno['no_control']}", reloj.txt(ahora)):
                continue
            avisar(db, tg, alumno["no_control"],
                   f"⏰ <b>Recordatorio:</b> tu asesoría de {s['materia']} empieza a las "
                   f"{s['inicio'][11:16]} en el {s['aula']}.",
                   [[("No podré ir: liberar mi lugar", f"baja|{s['id']}")]])
            n += 1
    return n


def avisos_tutor(db, tg, ahora):
    n = 0
    terminadas = db.execute(
        reglas.SQL_SESION + """ WHERE s.estado='programada'
          AND datetime(s.inicio, '+' || s.duracion || ' minutes') <= ?
          AND datetime(s.inicio, '+' || s.duracion || ' minutes') > ?""",
        (reloj.txt(ahora), reloj.txt(ahora - timedelta(hours=24))),
    ).fetchall()
    for s in terminadas:
        canal = db.execute(
            """SELECT c.*, u.nombre FROM canalizaciones c JOIN usuarios u ON u.no_control=c.alumno
               WHERE c.materia_id=? AND c.creada <= ?""", (s["materia_id"], s["inicio"])).fetchall()
        for c in canal:
            inscrito = db.execute("SELECT 1 FROM inscripciones WHERE sesion_id=? AND no_control=?",
                                  (s["id"], c["alumno"])).fetchone()
            asistio = db.execute("SELECT 1 FROM asistencias WHERE sesion_id=? AND no_control=?",
                                 (s["id"], c["alumno"])).fetchone()
            if not (inscrito or asistio):
                continue
            if ya_enviado(db, f"tut:{s['id']}:{c['alumno']}", reloj.txt(ahora)):
                continue
            resultado = "<b>asistió</b>" if asistio else "<b>no asistió</b>"
            avisar(db, tg, c["tutor"],
                   f"📋 <b>Aviso de asistencia:</b> {c['nombre'] or 'Tu tutorado ' + c['alumno']} {resultado} "
                   f"a {s['materia']} el {reloj.corto(s['inicio'])} ({s['aula']}).",
                   [[("📋 Ver mis tutorados", "tu_ver")]])
            n += 1
    return n


def avisar_constancia(db, tg, asesor):
    a = reglas.asesor_activo(db, asesor)
    u = reglas.usuario(db, asesor)
    materia = a["materia"] if a else ""
    avisar(db, tg, asesor, "📄 <b>¡Llegaste a tu meta de horas!</b> Tu constancia ya se generó; "
                           "la coordinación la manda a firma y te avisa.")
    avisar_rol(db, tg, "coord", f"📄 <b>Constancia lista:</b> {reglas.nombre_corto(u)} · {materia}. "
                                "Solo falta la firma del área.", [[("📄 Ver constancias", "co_con")]])


def constancias(db, tg, ahora):
    n = 0
    for a in reglas.asesores(db):
        if reglas.revisar_constancia(db, a["no_control"], ahora):
            avisar_constancia(db, tg, a["no_control"])
            n += 1
    return n


def reportes_semanales(db, tg, ahora):
    if ahora.weekday() != 0 or ahora.hour < 8:
        return 0
    desde, hasta = reglas.semana_anterior(ahora)
    semana = f"{desde:%Y-%m-%d}"
    n = 0
    if not ya_enviado(db, f"sem:{semana}", reloj.txt(ahora)):
        rep = reglas.reporte(db, desde, hasta)
        avisar_rol(db, tg, "coord", reglas.texto_reporte(rep, "Reporte semanal"),
                   [[("📥 Descargar en Excel", "co_xs")]])
        n += 1
    for (depto,) in db.execute("SELECT DISTINCT departamento FROM usuarios WHERE rol='jefatura'").fetchall():
        if ya_enviado(db, f"jef:{depto}:{semana}", reloj.txt(ahora)):
            continue
        rep = reglas.reporte(db, desde, hasta, depto)
        avisar_rol(db, tg, "jefatura", reglas.texto_reporte(rep, f"Reporte semanal · {depto}"),
                   [[("📥 Descargar en Excel", "je_xs")]], departamento=depto)
        n += 1
    return n


def informe_semestral(db, tg, ahora):
    fin = reglas.fin_semestre(db)
    if ahora <= fin or ya_enviado(db, f"semestral:{fin:%Y-%m-%d}", reloj.txt(ahora)):
        return 0
    inicio = reglas.inicio_semestre(db)
    ruta, rep = documentos.informe_xlsx(db, inicio, fin + timedelta(seconds=1), f"informe_semestral_{fin:%Y%m%d}.xlsx")
    for (nc,) in db.execute("SELECT no_control FROM usuarios WHERE rol='coord'").fetchall():
        for (chat,) in db.execute("SELECT chat_id FROM vinculos WHERE no_control=?", (nc,)).fetchall():
            tg.enviar_archivo(chat, ruta, "📁 <b>Informe semestral</b> generado automáticamente "
                                          f"({rep['realizadas']} sesiones, {rep['asistencias']} asistencias).")
    return 1


def ejecutar(db, tg, ahora=None):
    ahora = ahora or reloj.ahora()
    return {
        "recordatorios": recordatorios(db, tg, ahora),
        "avisos_tutor": avisos_tutor(db, tg, ahora),
        "constancias": constancias(db, tg, ahora),
        "reportes": reportes_semanales(db, tg, ahora),
        "semestral": informe_semestral(db, tg, ahora),
    }
