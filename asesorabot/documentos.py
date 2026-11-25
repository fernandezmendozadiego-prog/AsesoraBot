"""Documentos que genera el sistema: constancia en PDF (RF-10) e informes en Excel (RF-11, RF-19)."""
from datetime import timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

from . import config, reglas, reloj
from .db import get_config

INDIGO = colors.HexColor("#312E81")  # contraste alto sobre blanco (RNF-05)


def constancia_pdf(db, asesor):
    u = reglas.usuario(db, asesor)
    fila = db.execute(
        """SELECT c.*, m.nombre AS materia FROM constancias c JOIN asesores a ON a.no_control=c.asesor
           JOIN materias m ON m.id=a.materia_id WHERE c.asesor=?""", (asesor,)).fetchone()
    if not fila:
        raise reglas.ErrorRegla("sin_constancia", "Ese asesor todavía no llega a su meta de horas.")
    periodo = get_config(db, "periodo", "Agosto–Diciembre 2026")
    ruta = config.carpeta_archivos() / f"constancia_{asesor}.pdf"
    c = canvas.Canvas(str(ruta), pagesize=letter)
    ancho, alto = letter
    c.setTitle(f"Constancia de asesoría par {asesor}")
    c.setFillColor(INDIGO)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(ancho / 2, alto - 3 * cm, "Programa de Asesorías Académicas entre Pares")
    c.setFont("Helvetica", 11)
    c.drawCentredString(ancho / 2, alto - 3.7 * cm, "Coordinación del programa")
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(ancho / 2, alto - 6 * cm, "CONSTANCIA")
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 12)
    texto = c.beginText(2.5 * cm, alto - 8 * cm)
    texto.setLeading(20)
    for linea in [
        "Se hace constar que el (la) estudiante:",
        "",
        f"      {reglas.nombre_corto(u)}  ·  No. de control {asesor}",
        f"      {u['carrera'] or ''}{', ' + str(u['semestre']) + '.º semestre' if u['semestre'] else ''}",
        "",
        f"participó como asesor(a) par de la materia {fila['materia']}",
        f"durante el periodo {periodo}, con {fila['horas']:.0f} horas válidas de asesoría",
        f"(meta: {fila['meta']} horas, regla RN-06).",
        "",
        f"Generada por AsesoraBot el {reloj.dt(fila['generada']):%d/%m/%Y}.",
    ]:
        texto.textLine(linea)
    c.drawText(texto)
    c.line(ancho / 2 - 4 * cm, 7 * cm, ancho / 2 + 4 * cm, 7 * cm)
    c.drawCentredString(ancho / 2, 6.4 * cm, "Firma del titular del área")
    c.setFont("Helvetica-Oblique", 9)
    c.drawCentredString(ancho / 2, 3 * cm, "Este documento solo es oficial con la firma del titular del área (RN-07).")
    c.showPage()
    c.save()
    return ruta


def _hoja(wb, titulo, encabezados, filas, primera=False):
    ws = wb.active if primera else wb.create_sheet()
    ws.title = titulo
    ws.append(encabezados)
    for celda in ws[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="312E81")
        celda.alignment = Alignment(horizontal="center")
    for f in filas:
        ws.append(list(f))
    for col in ws.columns:
        largo = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(10, largo + 2), 45)
    return ws


def informe_xlsx(db, desde, hasta, nombre, departamento=None):
    """Informe en Excel (.xlsx), sin captura manual."""
    rep = reglas.reporte(db, desde, hasta, departamento)
    wb = Workbook()
    _hoja(wb, "Resumen", ["Concepto", "Valor"], [
        ("Periodo", f"{desde:%d/%m/%Y} – {(hasta - timedelta(days=1)):%d/%m/%Y}"),
        ("Departamento", departamento or "Todos"),
        ("Sesiones programadas", rep["programadas"]),
        ("Sesiones realizadas", rep["realizadas"]),
        ("Sesiones canceladas", rep["canceladas"]),
        ("Canceladas con menos de 2 h de aviso", rep["tardias"]),
        ("Asistencias registradas", rep["asistencias"]),
        ("Materias sin asesor", ", ".join(rep["sin_asesor"]) or "Ninguna"),
        ("Materias sin alumnos", ", ".join(rep["sin_alumnos"]) or "Ninguna"),
    ], primera=True)
    _hoja(wb, "Por materia", ["Materia", "Programadas", "Realizadas", "Canceladas", "Asistencias", "Calificación promedio"],
          [(m["materia"], m["programadas"], m["realizadas"], m["canceladas"], m["asistencias"], m["calificacion"])
           for m in rep["materias"]])
    filtro, params = "", [reloj.txt(desde), reloj.txt(hasta)]
    if departamento:
        filtro, params = " AND m.departamento=?", params + [departamento]
    sesiones = db.execute(
        f"""SELECT s.inicio, m.nombre, s.aula, s.estado, s.motivo, s.tardia,
              (SELECT COUNT(*) FROM inscripciones i WHERE i.sesion_id=s.id),
              (SELECT COUNT(*) FROM asistencias a WHERE a.sesion_id=s.id)
            FROM sesiones s JOIN materias m ON m.id=s.materia_id
            WHERE s.inicio>=? AND s.inicio<? {filtro} ORDER BY s.inicio""", params).fetchall()
    _hoja(wb, "Sesiones", ["Fecha y hora", "Materia", "Aula", "Estado", "Motivo", "Aviso < 2 h", "Inscritos", "Asistencias"],
          [(s[0][:16], s[1], s[2], s[3], s[4] or "", "Sí" if s[5] else "", s[6], s[7]) for s in sesiones])
    if not departamento:
        _hoja(wb, "Asesores", ["No. control", "Asesor(a)", "Materia", "Horas válidas", "Meta", "Constancia"],
              [(a["no_control"], a["nombre"], a["materia"], reglas.horas_asesor(db, a["no_control"]),
                reglas.meta_horas(db, a["no_control"]),
                "Generada" if db.execute("SELECT 1 FROM constancias WHERE asesor=?", (a["no_control"],)).fetchone() else "")
               for a in reglas.asesores(db, solo_activos=False)])
    ruta = config.carpeta_archivos() / nombre
    wb.save(ruta)
    return ruta, rep
