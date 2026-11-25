"""Manejadores del bot: convierten mensajes y botones de Telegram en llamadas a las reglas.

Cada botón lleva un «dato» corto (callback_data), por ejemplo «ins|42» = inscribirme a la sesión 42.
Cuando el bot espera que la persona escriba algo (un código, un aula, un motivo) guarda
en la tabla «estados» en qué paso va esa conversación.
"""
import json
import logging
from datetime import datetime, timedelta
from html import escape

from . import documentos, reglas, reloj, tareas
from .avisos import avisar, avisar_rol
from .reglas import ROLES_ALUMNO, ErrorRegla

log = logging.getLogger("asesorabot.bot")

DEPARTAMENTOS = ["Ciencias Básicas", "Sistemas y Computación", "Ciencias Económico-Administrativas"]
HORAS = [f"{h:02d}:00" for h in range(7, 20)]
MOTIVOS_RECHAZO = ["No ha aprobado la materia", "Ya hay asesores suficientes en esa materia",
                   "Su disponibilidad no coincide con aulas libres"]
MOTIVOS_CANCELAR = ["Tengo examen", "Motivo de salud", "Actividad académica"]
NOMBRE_ROL = {"alumno": "Alumno(a)", "asesor": "Asesor(a)", "tutor": "Tutor(a)",
              "coord": "Coordinación", "jefatura": "Jefatura académica"}
PERMISOS = {"as_": ("asesor",), "tu_": ("tutor",), "co_": ("coord",), "je_": ("jefatura",),
            "ins": ROLES_ALUMNO, "baja": ROLES_ALUMNO, "cod": ROLES_ALUMNO, "cal": ROLES_ALUMNO,
            "post": ROLES_ALUMNO, "p_": ROLES_ALUMNO, "mis": ROLES_ALUMNO}
MENU = [("↩︎ Menú", "menu")]
PASOS_INTERMEDIOS = {"p_sem", "p_mat", "p_dia", "p_ok", "as_hd", "as_hh", "as_ha", "as_hotra", "as_cupo",
                     "as_md", "as_mh", "as_ma", "as_mva", "as_motra", "co_nd"}

# usuarios de la demostración (datos SIMULADOS, ver semilla.py)
DEMO_ROLES = {"asesor": "22660101", "tutor": "TUTOR001", "coord": "COORD001", "jefatura": "JEFCB001"}

AYUDA = ("<b>AsesoraBot</b> te ayuda con las asesorías entre pares:\n"
         "• /materias ver asesorías · /buscar calc buscar por nombre\n"
         "• /mis mis inscripciones · /codigo K7P2Q9 registrar asistencia\n"
         "• /menu ver tus opciones · /privacidad qué datos guardamos")
PRIVACIDAD = ("🔒 Solo guardamos tu <b>número de control</b>, tus inscripciones y asistencias. "
              "Cada rol ve únicamente lo que le corresponde.")


def sesion_linea(s):
    asesor = escape(s["asesor_nombre"] or "Asesor(a)")
    perfil = f"{s['asesor_carrera'] or ''}{', ' + str(s['asesor_semestre']) + '.º' if s['asesor_semestre'] else ''}"
    lugares = "<b>LLENA</b>" if s["inscritos"] >= s["cupo"] else f"<b>{s['cupo'] - s['inscritos']} de {s['cupo']}</b> lugares"
    return f"• {reloj.corto(s['inicio'])} · {escape(s['aula'])} · {asesor} ({escape(perfil)}) — {lugares}"


class Manejador:
    def __init__(self, db, tg, demo=False):
        self.db, self.tg, self.demo = db, tg, demo

    @property
    def ahora(self):
        return reloj.ahora()

    # ------------------------------------------------------------ utilidades
    def decir(self, chat, texto, botones=None):
        return self.tg.enviar(chat, texto, botones)

    def usuario_de(self, chat):
        return self.db.execute(
            "SELECT u.* FROM vinculos v JOIN usuarios u ON u.no_control=v.no_control WHERE v.chat_id=?",
            (chat,)).fetchone()

    def estado(self, chat):
        fila = self.db.execute("SELECT estado, datos FROM estados WHERE chat_id=?", (chat,)).fetchone()
        return (fila[0], json.loads(fila[1] or "{}")) if fila else (None, {})

    def poner_estado(self, chat, estado, datos=None):
        self.db.execute("INSERT OR REPLACE INTO estados VALUES (?,?,?)",
                        (chat, estado, json.dumps(datos or {}, ensure_ascii=False)))
        self.db.commit()

    def limpiar(self, chat):
        self.db.execute("DELETE FROM estados WHERE chat_id=?", (chat,))
        self.db.commit()

    def vincular(self, chat, no_control):
        self.db.execute("INSERT OR REPLACE INTO vinculos VALUES (?,?)", (chat, no_control))
        self.db.commit()

    # ------------------------------------------------------------ entrada
    def procesar(self, update):
        if "callback_query" in update:
            q = update["callback_query"]
            self.tg.responder_boton(q["id"])
            msg = q.get("message") or {}
            chat = msg.get("chat", {}).get("id")
            if chat is not None:
                self.boton(chat, msg.get("message_id"), q.get("data", ""))
        elif "message" in update:
            msg = update["message"]
            if msg.get("chat", {}).get("type", "private") == "private":
                self.mensaje(msg["chat"]["id"], (msg.get("text") or "").strip())

    def mensaje(self, chat, texto):
        if not texto:
            return self.decir(chat, "Por ahora solo entiendo texto y botones. Escribe /menu.")
        cmd, arg = "", ""
        if texto.startswith("/"):
            cmd, _, arg = texto[1:].partition(" ")
            cmd, arg = cmd.split("@")[0].lower(), arg.strip()
            if cmd == "start":
                return self.cmd_start(chat, arg)
            if cmd == "demo":
                return self.cmd_demo(chat)
            if cmd in ("ayuda", "help"):
                return self.decir(chat, AYUDA, [MENU])
            if cmd == "privacidad":
                return self.decir(chat, PRIVACIDAD, [MENU])
        u = self.usuario_de(chat)
        est, datos = self.estado(chat)
        if not u:
            if est == "registro" and not cmd:
                return self.registro(chat, texto)
            return self.pedir_registro(chat)
        try:
            if cmd:
                self.limpiar(chat)
                return self.comando(chat, u, cmd, arg)
            if est:
                return self.texto_en_estado(chat, u, est, datos, texto)
            if reglas.parece_codigo(texto) and u["rol"] in ROLES_ALUMNO:
                return self.asistencia(chat, u, texto)
            return self.buscar(chat, texto)
        except ErrorRegla as e:
            return self.decir(chat, "⚠️ " + e.mensaje, [MENU])

    def comando(self, chat, u, cmd, arg):
        rol = u["rol"]
        if cmd == "menu":
            return self.menu(chat, u)
        if cmd == "materias":
            return self.lista_materias(chat)
        if cmd == "buscar":
            if not arg:
                self.poner_estado(chat, "busqueda")
                return self.decir(chat, "🔎 Escribe parte del nombre de la materia (por ejemplo, «calc»).")
            return self.buscar(chat, arg)
        if cmd == "mis" and rol in ROLES_ALUMNO:
            return self.boton(chat, None, "mis")
        if cmd == "codigo" and rol in ROLES_ALUMNO:
            if arg:
                return self.asistencia(chat, u, arg)
            return self.boton(chat, None, "cod")
        if cmd == "postularme" and rol in ROLES_ALUMNO:
            return self.boton(chat, None, "post")
        if cmd == "cancelar" and rol == "asesor":
            return self.boton(chat, None, "as_can")
        if cmd == "horas" and rol == "asesor":
            return self.boton(chat, None, "as_hrs")
        if cmd == "canalizar" and rol == "tutor":
            return self.boton(chat, None, "tu_can")
        if cmd == "reporte" and rol in ("coord", "jefatura"):
            return self.boton(chat, None, "co_rep" if rol == "coord" else "je_rep")
        return self.decir(chat, "No conozco ese comando o no está disponible para tu rol. Toca /menu.", [MENU])

    # ------------------------------------------------------------ registro
    def cmd_start(self, chat, arg):
        self.limpiar(chat)
        if arg:
            inv = self.db.execute("SELECT * FROM invitaciones WHERE codigo=? AND usada=0", (arg,)).fetchone()
            if inv:
                self.db.execute("UPDATE invitaciones SET usada=1 WHERE codigo=?", (arg,))
                self.vincular(chat, inv["no_control"])
                u = self.usuario_de(chat)
                self.decir(chat, f"✅ Cuenta vinculada como <b>{NOMBRE_ROL.get(u['rol'], u['rol'])}</b>.")
                return self.menu(chat, u)
        u = self.usuario_de(chat)
        if u:
            return self.menu(chat, u)
        return self.pedir_registro(chat, bienvenida=True)

    def pedir_registro(self, chat, bienvenida=False):
        self.poner_estado(chat, "registro")
        texto = ("👋 ¡Hola! Soy <b>AsesoraBot</b>, del Programa de Asesorías entre Pares.\n" if bienvenida else "")
        texto += "Para empezar, escribe tu <b>número de control</b> (8 dígitos). Es el único dato que guardo."
        botones = [[("🧪 Probar con datos simulados (demo)", "demo")]] if self.demo else None
        return self.decir(chat, texto, botones)

    def registro(self, chat, texto):
        nc = texto.strip()
        if not reglas.valida_no_control(nc):
            return self.decir(chat, "⚠️ El número de control debe tener exactamente 8 dígitos, sin letras ni espacios. "
                                    "Escríbelo de nuevo.")
        u = reglas.usuario(self.db, nc)
        if u and u["rol"] not in ROLES_ALUMNO:
            return self.decir(chat, "⚠️ Esa cuenta es del personal: usa el enlace de invitación que te dio la coordinación.")
        otro = self.db.execute("SELECT chat_id FROM vinculos WHERE no_control=? AND chat_id!=?", (nc, chat)).fetchone()
        if otro and not self.demo:
            return self.decir(chat, "⚠️ Ese número de control ya está vinculado a otra cuenta de Telegram. "
                                    "Si es tuyo, acude a la coordinación.")
        if not u:
            self.db.execute("INSERT INTO usuarios(no_control, rol) VALUES (?, 'alumno')", (nc,))
        self.vincular(chat, nc)
        self.limpiar(chat)
        self.decir(chat, "✅ Listo, ya estás registrado(a).")
        return self.menu(chat, self.usuario_de(chat))

    def cmd_demo(self, chat):
        if not self.demo:
            return self.decir(chat, "El modo demostración no está activo.")
        self.limpiar(chat)
        return self.decir(chat, "🧪 <b>Modo demostración</b> (datos SIMULADOS). ¿Con qué rol quieres probar?", [
            [("🎓 Alumno", "demo|alumno"), ("🧑‍🏫 Asesor", "demo|asesor")],
            [("📋 Tutor", "demo|tutor"), ("🗂️ Coordinación", "demo|coord")],
            [("🏛️ Jefatura (Ciencias Básicas)", "demo|jefatura")]])

    def entrar_demo(self, chat, rol):
        if rol == "alumno":
            nc = f"99{chat % 10**6:06d}"
            if not reglas.usuario(self.db, nc):
                self.db.execute("INSERT INTO usuarios(no_control, nombre, rol, carrera, semestre, tutor) "
                                "VALUES (?,?,?,?,?,?)", (nc, "Alumno(a) de prueba", "alumno",
                                                         "Ing. en Sistemas Computacionales", 5, "TUTOR001"))
        else:
            nc = DEMO_ROLES[rol]
        self.vincular(chat, nc)
        self.limpiar(chat)
        return self.menu(chat, self.usuario_de(chat))

    # ------------------------------------------------------------ menú
    def menu(self, chat, u):
        rol = u["rol"]
        nombre = escape(u["nombre"] or "")
        if rol == "asesor":
            a = reglas.asesor_activo(self.db, u["no_control"])
            horas, meta = reglas.horas_asesor(self.db, u["no_control"]), reglas.meta_horas(self.db, u["no_control"])
            texto = (f"Hola{', <b>' + nombre + '</b>' if nombre else ''}. Eres asesor(a) de <b>{escape(a['materia'])}</b>.\n"
                     f"Llevas <b>{horas:.0f} de {meta}</b> horas válidas.")
            botones = [[("🗓️ Registrar horario", "as_hor"), ("👥 Mis sesiones", "as_ins")],
                       [("🔑 Mostrar código", "as_cod"), ("⚠️ Cancelar o mover", "as_can")],
                       [("⏱️ Mis horas", "as_hrs"), ("📚 Asesorías (como alumno)", "mat")]]
            if self.demo:
                botones.append([("🧪 Sesión de prueba ahora", "as_demo|0"), ("🧪 En 61 min", "as_demo|61")])
        elif rol == "tutor":
            texto = f"Hola{', <b>' + nombre + '</b>' if nombre else ''}. ¿Qué necesitas?"
            botones = [[("👥 Mis tutorados", "tu_ver")], [("📨 Canalizar a un tutorado", "tu_can")]]
        elif rol == "coord":
            n = len(reglas.aspirantes_pendientes(self.db))
            texto = "🗂️ <b>Coordinación del programa.</b> ¿Qué necesitas?"
            botones = [[(f"🙋 Aspirantes ({n})", "co_asp"), ("📊 Reporte semanal", "co_rep")],
                       [("📄 Constancias", "co_con"), ("📁 Informe semestral", "co_inf")],
                       [("🛠️ Materias", "co_mat"), ("🚫 Bajas", "co_baj")]]
        elif rol == "jefatura":
            texto = f"🏛️ <b>{escape(u['departamento'] or 'Jefatura')}</b>. Cada lunes te llega el reporte de tus materias."
            botones = [[("📊 Reporte de mi departamento", "je_rep")]]
        else:
            texto = "¿Qué quieres hacer?"
            botones = [[("📚 Ver asesorías", "mat")],
                       [("🔎 Buscar materia", "bus"), ("🗓️ Mis asesorías", "mis")],
                       [("✍️ Escribir código de asistencia", "cod")],
                       [("🙋 Postularme como asesor", "post")]]
        if self.demo:
            botones.append([("🧪 Cambiar de rol (demo)", "demo")])
        return self.decir(chat, texto, botones)

    # ------------------------------------------------------------ alumno
    def lista_materias(self, chat):
        ms = reglas.materias(self.db)
        botones, fila = [], []
        for m in ms:
            fila.append((m["nombre"] if m["asesores"] else f"{m['nombre']} (sin asesor)", f"ses|{m['id']}"))
            if len(fila) == 2:
                botones.append(fila)
                fila = []
        if fila:
            botones.append(fila)
        botones.append(MENU)
        return self.decir(chat, "📚 <b>Materias con asesoría.</b> Elige una para ver fechas y lugares:", botones)

    def buscar(self, chat, texto):
        self.limpiar(chat)
        ms = reglas.buscar_materias(self.db, texto)
        if not ms:
            return self.decir(chat, f"No encontré materias con «{escape(texto)}». Revisa cómo lo escribiste "
                                    "o toca «Ver asesorías».", [[("📚 Ver asesorías", "mat")], MENU])
        return self.decir(chat, f"Encontré {len(ms)} materia{'s' if len(ms) > 1 else ''}:",
                          [[(m["nombre"], f"ses|{m['id']}")] for m in ms] + [MENU])

    def sesiones_materia(self, chat, materia_id, encabezado=""):
        m = reglas.materia(self.db, materia_id)
        if not m:
            return self.decir(chat, "Esa materia ya no existe.", [MENU])
        ses = reglas.proximas_sesiones(self.db, materia_id, self.ahora)
        if not ses:
            return self.decir(chat, f"{encabezado}<b>{escape(m['nombre'])}</b>: no hay sesiones en los próximos 7 días.",
                              [[("📚 Otra materia", "mat")], MENU])
        texto = f"{encabezado}<b>{escape(m['nombre'])}</b>\n" + "\n".join(sesion_linea(s) for s in ses)
        botones = [[(("✅ Inscribirme " if s["inscritos"] < s["cupo"] else "") + reloj.corto(s["inicio"])
                     + (" (llena)" if s["inscritos"] >= s["cupo"] else ""), f"ins|{s['id']}")] for s in ses]
        return self.decir(chat, texto, botones + [[("📚 Otra materia", "mat")], MENU])

    def asistencia(self, chat, u, codigo):
        try:
            s = reglas.registrar_asistencia(self.db, u["no_control"], codigo, self.ahora)
        except ErrorRegla as e:
            self.poner_estado(chat, "codigo")  # puede volver a intentarlo
            return self.decir(chat, "⚠️ " + e.mensaje, [MENU])
        self.limpiar(chat)
        canalizado = self.db.execute("SELECT 1 FROM canalizaciones WHERE alumno=? AND materia_id=?",
                                     (u["no_control"], s["materia_id"])).fetchone()
        self.decir(chat, f"✅ <b>Asistencia registrada</b> ({escape(s['materia'])}, {reloj.corto(s['inicio'])})."
                         + ("\nTu tutor(a) recibirá el aviso." if canalizado else "")
                         + "\n¿Cómo calificas la asesoría?",
                   [[(f"{n} ⭐", f"cal|{s['id']}|{n}") for n in range(1, 6)]])
        if reglas.revisar_constancia(self.db, s["asesor"], self.ahora):
            tareas.avisar_constancia(self.db, self.tg, s["asesor"])

    # ------------------------------------------------------------ texto esperado
    def texto_en_estado(self, chat, u, est, datos, texto):
        if est == "codigo":
            return self.asistencia(chat, u, texto)
        if est == "busqueda":
            return self.buscar(chat, texto)
        if est == "aula":
            datos["aula"] = texto.strip()[:30]
            return self._pedir_cupo(chat, datos)
        if est == "motivo":
            self.limpiar(chat)
            return self.aplicar_cancelacion(chat, u, datos["sid"], texto.strip()[:120])
        if est == "aula_mover":
            self.limpiar(chat)
            return self.aplicar_movimiento(chat, u, datos["sid"], datos["fecha"], datos["hora"], texto.strip()[:30])
        if est == "aula_nueva":
            self.limpiar(chat)
            try:
                nombre = reglas.agregar_aula(self.db, texto)
            except ErrorRegla as e:
                return self.decir(chat, "⚠️ " + e.mensaje, [[("🏫 Aulas", "co_aul")], MENU])
            return self.decir(chat, f"✅ Aula «{escape(nombre)}» agregada al catálogo.", [[("🏫 Aulas", "co_aul")], MENU])
        if est == "materia_nueva":
            self.poner_estado(chat, "materia_depto", {"nombre": texto.strip()[:60]})
            return self.decir(chat, "¿De qué departamento es?",
                              [[(d, f"co_nd|{i}")] for i, d in enumerate(DEPARTAMENTOS)])
        if est == "rechazo":
            self.limpiar(chat)
            return self.rechazar(chat, datos["aid"], texto.strip()[:150])
        self.limpiar(chat)
        return self.buscar(chat, texto)

    # ------------------------------------------------------------ botones
    def boton(self, chat, mid, data):
        partes = data.split("|")
        acc = partes[0]
        if acc == "demo" and len(partes) == 1:
            return self.cmd_demo(chat)
        if acc == "demo":
            if not self.demo or partes[1] not in ("alumno", *DEMO_ROLES):
                return self.decir(chat, "El modo demostración no está activo.")
            return self.entrar_demo(chat, partes[1])
        u = self.usuario_de(chat)
        if not u:
            return self.pedir_registro(chat)
        for prefijo, roles in PERMISOS.items():
            if acc.startswith(prefijo) and u["rol"] not in roles:
                return self.decir(chat, "🔒 Esa opción no está disponible para tu rol.", [MENU])
        try:
            return self._boton(chat, mid, u, acc, partes[1:])
        except ErrorRegla as e:
            return self.decir(chat, "⚠️ " + e.mensaje, [MENU])
        except (ValueError, IndexError, KeyError, TypeError):
            log.exception("Botón con datos inválidos: %s", data)
            return self.decir(chat, "⚠️ Ese botón ya no es válido. Toca /menu para empezar de nuevo.")

    def _boton(self, chat, mid, u, acc, p):
        nc, db, ahora = u["no_control"], self.db, self.ahora
        # un botón nuevo cancela cualquier texto que el bot estuviera esperando,
        # salvo los pasos intermedios de un mismo trámite
        if acc not in PASOS_INTERMEDIOS:
            self.limpiar(chat)
        if acc == "menu":
            return self.menu(chat, u)
        if acc == "mat":
            return self.lista_materias(chat)
        if acc == "bus":
            self.poner_estado(chat, "busqueda")
            return self.decir(chat, "🔎 Escribe parte del nombre de la materia (por ejemplo, «calc»).")
        if acc == "ses":
            return self.sesiones_materia(chat, int(p[0]))

        # ---- alumno
        if acc == "ins":
            sid = int(p[0])
            try:
                s = reglas.inscribir(db, sid, nc, ahora)
            except ErrorRegla as e:
                if e.clave != "llena":
                    raise
                alt = reglas.alternativas(db, sid, ahora)
                return self.decir(chat, "⚠️ <b>Sesión llena.</b> " + ("Estas fechas tienen lugar:" if alt else
                                  "No hay otra fecha con lugar esta semana."),
                                  [[("✅ " + reloj.corto(a["inicio"]) + " · " + a["aula"], f"ins|{a['id']}")] for a in alt]
                                  + [MENU])
            return self.decir(chat, f"✅ <b>Inscrito(a).</b> {escape(s['materia'])}, {reloj.corto(s['inicio'])}, "
                                    f"{escape(s['aula'])}.\nTe aviso 1 hora antes. Lugares restantes: {s['cupo'] - s['inscritos']}.",
                              [[("Cancelar mi inscripción", f"baja|{sid}")], MENU])
        if acc == "baja":
            s = reglas.cancelar_inscripcion(db, int(p[0]), nc)
            return self.decir(chat, f"Listo, liberé tu lugar en {escape(s['materia'])} ({reloj.corto(s['inicio'])}).",
                              [[("📚 Ver otras fechas", f"ses|{s['materia_id']}")], MENU])
        if acc == "mis":
            ins = reglas.mis_inscripciones(db, nc, ahora)
            hist = reglas.historial_alumno(db, nc)
            texto = "<b>Tus próximas asesorías</b>\n" + ("\n".join(
                f"• {reloj.corto(s['inicio'])} · {escape(s['materia'])} · {escape(s['aula'])}" for s in ins)
                or "• Ninguna por ahora.")
            if hist:
                texto += "\n\n<b>Asistencias del semestre</b>\n" + "\n".join(
                    f"• {escape(h['materia'])} — {h['asistencias']}" for h in hist)
            return self.decir(chat, texto, [[(f"Cancelar {reloj.corto(s['inicio'])}", f"baja|{s['id']}")] for s in ins]
                              + [MENU])
        if acc == "cod":
            self.poner_estado(chat, "codigo")
            return self.decir(chat, "✍️ Escribe el código de 6 caracteres que muestra el asesor en el pizarrón.")
        if acc == "cal":
            reglas.calificar(db, int(p[0]), nc, int(p[1]))
            return self.decir(chat, f"¡Gracias! Guardé tu calificación: {'⭐' * int(p[1])}", [MENU])

        # ---- postularse como asesor (RF-15)
        if acc == "post":
            if reglas.asesor_activo(db, nc):
                raise ErrorRegla("ya_asesor", "Ya eres asesor del programa.")
            self.poner_estado(chat, "postulacion", {})
            return self.decir(chat, "🙋 <b>Postulación como asesor.</b> ¿Qué semestre cursas?",
                              [[(str(n), f"p_sem|{n}") for n in range(i, i + 4)] for i in (1, 5, 9)])
        if acc in ("p_sem", "p_mat", "p_dia", "p_ok"):
            est, datos = self.estado(chat)
            if est != "postulacion":
                return self.decir(chat, "Esa postulación ya no está abierta. Toca «Postularme como asesor» de nuevo.", [MENU])
            if acc == "p_sem":
                if int(p[0]) < reglas.SEMESTRE_MINIMO_ASESOR:
                    self.limpiar(chat)
                    raise ErrorRegla("semestre", "Para ser asesor necesitas cursar 4.º semestre o superior (RN‑09).")
                datos["sem"] = int(p[0])
                self.poner_estado(chat, "postulacion", datos)
                return self.decir(chat, "¿Qué materia quieres asesorar? (debes haberla aprobado)",
                                  [[(m["nombre"], f"p_mat|{m['id']}")] for m in reglas.materias(db)])
            if acc == "p_mat":
                datos["mat"] = int(p[0])
                datos.setdefault("dias", [])
                self.poner_estado(chat, "postulacion", datos)
                return self.decir(chat, "¿Qué días puedes? Elige hasta 2 y toca «Listo».", self._botones_dias(datos["dias"]))
            if acc == "p_dia":
                d = int(p[0])
                dias = datos.setdefault("dias", [])
                if d in dias:
                    dias.remove(d)
                elif len(dias) < 2:
                    dias.append(d)
                self.poner_estado(chat, "postulacion", datos)
                if mid:
                    return self.tg.editar(chat, mid, "¿Qué días puedes? Elige hasta 2 y toca «Listo».",
                                          self._botones_dias(dias))
                return None
            if acc == "p_ok":
                dias = " y ".join(reloj.DIAS_LARGOS[d] for d in sorted(datos.get("dias", [])))
                reglas.postular(db, nc, datos.get("sem"), datos.get("mat"), dias, ahora)
                self.limpiar(chat)
                m = reglas.materia(db, datos["mat"])
                avisar_rol(db, self.tg, "coord",
                           f"🙋 <b>Nueva solicitud de asesor:</b> {datos['sem']}.º semestre · {escape(m['nombre'])} · {dias}.",
                           [[("Ver aspirantes", "co_asp")]])
                return self.decir(chat, "📨 <b>Solicitud enviada.</b> La coordinación revisa que hayas aprobado la materia "
                                        "y te avisa por aquí.", [MENU])

        # ---- asesor
        if acc.startswith("as_"):
            return self.boton_asesor(chat, u, acc, p)
        if acc.startswith("tu_"):
            return self.boton_tutor(chat, u, acc, p)
        if acc.startswith("co_"):
            return self.boton_coord(chat, u, acc, p)
        if acc.startswith("je_"):
            return self.boton_jefatura(chat, u, acc, p)
        return self.decir(chat, "No entendí ese botón. Toca /menu.", [MENU])

    @staticmethod
    def _botones_aulas(lista, plantilla, por_fila=3):
        botones = [(a["nombre"], plantilla.format(id=a["id"])) for a in lista]
        return [botones[i:i + por_fila] for i in range(0, len(botones), por_fila)]

    def _pedir_cupo(self, chat, datos):
        self.poner_estado(chat, "cupo", datos)
        return self.decir(chat, f"Aula: <b>{escape(datos['aula'])}</b>. ¿Cuántos lugares tendrá? (máximo 15, RN‑02)",
                          [[("5", "as_cupo|5"), ("10", "as_cupo|10"), ("15", "as_cupo|15")]])

    @staticmethod
    def _botones_dias(elegidos):
        fila = [(("✅ " if i in elegidos else "") + reloj.DIAS[i], f"p_dia|{i}") for i in range(5)]
        return [fila, [("Listo", "p_ok")]]

    # ------------------------------------------------------------ asesor
    def boton_asesor(self, chat, u, acc, p):
        nc, db, ahora = u["no_control"], self.db, self.ahora
        if acc == "as_hor":
            n = db.execute("SELECT COUNT(*) FROM horarios WHERE asesor=? AND activo=1", (nc,)).fetchone()[0]
            if n >= reglas.MAX_HORARIOS_ASESOR:
                raise ErrorRegla("maximo", "Ya tienes 2 sesiones por semana, que es el máximo (RN‑10).")
            return self.decir(chat, "🗓️ ¿Qué día propones para tu sesión semanal?",
                              [[(reloj.DIAS[d], f"as_hd|{d}") for d in range(5)]])
        if acc == "as_hd":
            d = int(p[0])
            return self.decir(chat, f"¿A qué hora el {reloj.DIAS_LARGOS[d]}?",
                              [[(h, f"as_hh|{d}|{h.replace(':', '')}") for h in HORAS[i:i + 4]] for i in range(0, len(HORAS), 4)])
        if acc == "as_hh":
            d, h = int(p[0]), f"{p[1][:2]}:{p[1][2:]}"
            self.poner_estado(chat, "aula", {"dia": d, "hora": h})
            libres = reglas.aulas_libres_semanal(db, d, h, ahora)
            texto = (f"{reloj.DIAS_LARGOS[d].capitalize()} {h}. ¿En qué aula? Estas están libres todas las semanas "
                     "a esa hora:" if libres else
                     f"{reloj.DIAS_LARGOS[d].capitalize()} {h}. No hay aulas del catálogo libres a esa hora. "
                     "Escribe otra aula o elige otra hora.")
            return self.decir(chat, texto, self._botones_aulas(libres, "as_ha|{id}")
                              + [[("✏️ Otra aula (escribir)", "as_hotra")], [("🗓️ Elegir otra hora", f"as_hd|{d}")]])
        if acc == "as_ha":
            est, datos = self.estado(chat)
            a = reglas.aula_por_id(db, int(p[0]))
            if est != "aula" or not a:
                return self.decir(chat, "Ese registro ya no está abierto. Toca «Registrar horario» de nuevo.", [MENU])
            datos["aula"] = a["nombre"]
            return self._pedir_cupo(chat, datos)
        if acc == "as_hotra":
            return self.decir(chat, "Escribe el aula (por ejemplo, «Aula 13» o «Sala audiovisual»).")
        if acc == "as_cupo":
            est, datos = self.estado(chat)
            if est != "cupo":
                return self.decir(chat, "Ese registro ya no está abierto. Toca «Registrar horario» de nuevo.", [MENU])
            self.limpiar(chat)
            try:
                _, creadas = reglas.registrar_horario(db, nc, datos["dia"], datos["hora"], datos["aula"], int(p[0]), ahora)
            except ErrorRegla as e:
                return self.decir(chat, "⚠️ " + e.mensaje, [[("🗓️ Elegir otro horario", "as_hor")], MENU])
            aula = datos["aula"] if not datos["aula"].isdigit() else f"Aula {datos['aula']}"
            return self.decir(chat, f"✅ <b>Publicado.</b> Tu sesión del {reloj.DIAS_LARGOS[datos['dia']]} {datos['hora']} "
                                    f"en {escape(aula)} ya aparece en /materias con cupo de {p[0]} ({creadas} fechas).", [MENU])
        if acc == "as_ins":
            ses = reglas.sesiones_de_asesor(db, nc, ahora)
            if not ses:
                return self.decir(chat, "No tienes sesiones en los próximos 7 días.", [MENU])
            bloques = []
            for s in ses:
                nombres = " · ".join(escape(reglas.nombre_corto(x)) for x in reglas.inscritos(db, s["id"]))
                bloques.append(f"<b>{reloj.corto(s['inicio'])} · {escape(s['aula'])}</b> — {s['inscritos']} de {s['cupo']}"
                               + (f"\n{nombres}" if nombres else ""))
            return self.decir(chat, "\n\n".join(bloques), [MENU])
        if acc == "as_cod":
            codigo, vence, s = reglas.generar_codigo(db, nc, ahora)
            n = db.execute("SELECT COUNT(*) FROM asistencias WHERE sesion_id=?", (s["id"],)).fetchone()[0]
            return self.decir(chat, f"🔑 Código: <b>{codigo}</b>\nVence a las {vence:%H:%M:%S} (2 min). "
                                    f"Escríbelo en el pizarrón. Asistencias hasta ahora: {n}.",
                              [[("🔄 Nuevo código", "as_cod")], MENU])
        if acc == "as_can":
            ses = [s for s in reglas.sesiones_de_asesor(db, nc, ahora, dias=14) if reloj.dt(s["inicio"]) > ahora]
            if not ses:
                return self.decir(chat, "No tienes sesiones próximas.", [MENU])
            return self.decir(chat, "¿Qué sesión quieres cancelar o mover?",
                              [[(f"{reloj.corto(s['inicio'])} · {s['aula']} ({s['inscritos']} inscritos)", f"as_cs|{s['id']}")]
                               for s in ses[:8]] + [MENU])
        if acc == "as_cs":
            s = reglas.sesion(db, int(p[0]))
            return self.decir(chat, f"Sesión del <b>{reloj.corto(s['inicio'])}</b> en {escape(s['aula'])}. ¿Qué hacemos?",
                              [[("❌ Cancelarla", f"as_cx|{s['id']}"), ("🔁 Moverla", f"as_mv|{s['id']}")], MENU])
        if acc == "as_cx":
            sid = int(p[0])
            self.poner_estado(chat, "motivo", {"sid": sid})
            return self.decir(chat, "¿Por qué la cancelas? Elige o escribe el motivo (se lo diré a los inscritos).",
                              [[(m, f"as_cm|{sid}|{i}")] for i, m in enumerate(MOTIVOS_CANCELAR)])
        if acc == "as_cm":
            return self.aplicar_cancelacion(chat, u, int(p[0]), MOTIVOS_CANCELAR[int(p[1])])
        if acc == "as_mv":
            sid = int(p[0])
            base = ahora.replace(hour=0, minute=0, second=0)
            dias = [base + timedelta(days=i) for i in range(0, 10) if (base + timedelta(days=i)).weekday() < 5][:6]
            return self.decir(chat, "¿A qué día la mueves?",
                              [[(f"{reloj.DIAS[d.weekday()]} {d:%d/%m}", f"as_md|{sid}|{d:%Y%m%d}") for d in dias[i:i + 3]]
                               for i in (0, 3)])
        if acc == "as_md":
            sid, f = int(p[0]), p[1]
            return self.decir(chat, "¿A qué hora?",
                              [[(h, f"as_mh|{sid}|{f}|{h.replace(':', '')}") for h in HORAS[i:i + 4]]
                               for i in range(0, len(HORAS), 4)])
        if acc == "as_mh":
            sid, f, h = int(p[0]), p[1], p[2]
            s = reglas.sesion(db, sid)
            self.poner_estado(chat, "aula_mover", {"sid": sid, "fecha": f, "hora": h})
            nuevo = datetime.strptime(f + h, "%Y%m%d%H%M")
            libres = reglas.aulas_libres_fecha(db, nuevo, s["duracion"], excluir=sid)
            misma = s["aula"].lower() in {a["nombre"].lower() for a in libres} or not any(
                a["nombre"].lower() == s["aula"].lower() for a in reglas.aulas(db))
            botones = [[(f"Misma aula ({s['aula']})", f"as_ma|{sid}|{f}|{h}")]] if misma else []
            otras = [a for a in libres if a["nombre"].lower() != s["aula"].lower()]
            texto = (f"¿En qué aula? Libres el {reloj.corto(reloj.txt(nuevo))}:" if libres else
                     "No hay aulas del catálogo libres a esa hora. Escribe otra aula o elige otra hora.")
            return self.decir(chat, texto, botones + self._botones_aulas(otras, f"as_mva|{sid}|{f}|{h}|{{id}}")
                              + [[("✏️ Otra aula (escribir)", "as_motra")], [("🕐 Elegir otra hora", f"as_md|{sid}|{f}")]])
        if acc == "as_ma":
            self.limpiar(chat)
            return self.aplicar_movimiento(chat, u, int(p[0]), p[1], p[2], None)
        if acc == "as_mva":
            a = reglas.aula_por_id(db, int(p[3]))
            self.limpiar(chat)
            return self.aplicar_movimiento(chat, u, int(p[0]), p[1], p[2], a["nombre"] if a else None)
        if acc == "as_motra":
            return self.decir(chat, "Escribe el aula (por ejemplo, «Aula 13» o «Sala audiovisual»).")
        if acc == "as_hrs":
            horas, meta = reglas.horas_asesor(db, nc), reglas.meta_horas(db, nc)
            c = db.execute("SELECT * FROM constancias WHERE asesor=?", (nc,)).fetchone()
            estado = ("\n📄 Tu constancia ya se generó" + (" y está firmada." if c["firmada"] else "; falta la firma del área.")
                      if c else f"\nTe faltan {max(0, meta - horas):.0f} h para tu constancia.")
            return self.decir(chat, f"⏱️ Llevas <b>{horas:.0f} de {meta}</b> horas válidas. Solo cuentan las sesiones "
                                    f"con al menos una asistencia (RN‑04).{estado}", [MENU])
        if acc == "as_demo" and self.demo:
            a = reglas.asesor_activo(db, nc)
            minutos = int(p[0])
            inicio = ahora.replace(second=0) + timedelta(minutes=minutos)
            db.execute("INSERT INTO sesiones(asesor, materia_id, inicio, aula, cupo) VALUES (?,?,?,?,15)",
                       (nc, a["materia_id"], reloj.txt(inicio), "Aula de prueba"))
            db.commit()
            extra = ("Ya puedes tocar «Mostrar código»." if minutos == 0 else
                     "Inscríbete como alumno: el recordatorio llega cuando falte 1 hora.")
            return self.decir(chat, f"🧪 Sesión de prueba creada: {reloj.corto(inicio)}, Aula de prueba. {extra}", [MENU])
        return self.decir(chat, "No entendí ese botón. Toca /menu.", [MENU])

    def aplicar_cancelacion(self, chat, u, sid, motivo):
        db, ahora = self.db, self.ahora
        try:
            s, avisar_a, tardia = reglas.cancelar_sesion(db, sid, motivo, ahora, asesor=u["no_control"])
        except ErrorRegla as e:
            return self.decir(chat, "⚠️ " + e.mensaje, [MENU])
        self._avisar_cancelacion(s, avisar_a, motivo)
        avisar_rol(db, self.tg, "coord",
                   f"ℹ️ <b>Cancelación:</b> {escape(s['materia'])}, {reloj.corto(s['inicio'])}. Motivo: {escape(motivo)}. "
                   f"Se avisó a {len(avisar_a)} inscritos." + (" ⚠️ Con menos de 2 h de anticipación (RN‑05)." if tardia else ""))
        return self.decir(chat, f"Listo. Avisé a {len(avisar_a)} inscritos y a la coordinación."
                          + ("\n⚠️ Recuerda: debes cancelar con al menos 2 horas de anticipación (RN‑05)." if tardia else ""),
                          [MENU])

    def _avisar_cancelacion(self, s, alumnos, motivo):
        alt = [a for a in reglas.proximas_sesiones(self.db, s["materia_id"], self.ahora) if a["inscritos"] < a["cupo"]][:2]
        botones = [[("✅ " + reloj.corto(a["inicio"]) + " · " + a["aula"], f"ins|{a['id']}")] for a in alt]
        for nc in alumnos:
            avisar(self.db, self.tg, nc,
                   f"⚠️ <b>Sesión cancelada.</b> La asesoría de {escape(s['materia'])} del {reloj.corto(s['inicio'])} "
                   f"({escape(s['aula'])}) se canceló: {escape(motivo)}." + ("\n¿Quieres otra fecha?" if alt else ""),
                   botones + [[("📚 Ver otras fechas", f"ses|{s['materia_id']}")]])

    def aplicar_movimiento(self, chat, u, sid, fecha, hora, aula):
        nuevo = datetime.strptime(fecha + hora, "%Y%m%d%H%M")
        try:
            viejo, s, avisar_a = reglas.mover_sesion(self.db, sid, u["no_control"], nuevo, aula, self.ahora)
        except ErrorRegla as e:
            return self.decir(chat, "⚠️ " + e.mensaje, [[("🔁 Elegir otra fecha", f"as_mv|{sid}")], MENU])
        for nc in avisar_a:
            avisar(self.db, self.tg, nc,
                   f"🔁 <b>Sesión cambiada.</b> {escape(s['materia'])}: era el {reloj.corto(viejo['inicio'])} en "
                   f"{escape(viejo['aula'])}; ahora es el <b>{reloj.corto(s['inicio'])}</b> en {escape(s['aula'])}. "
                   "Sigues inscrito(a).", [[("No puedo: liberar mi lugar", f"baja|{sid}")]])
        avisar_rol(self.db, self.tg, "coord", f"ℹ️ <b>Cambio de sesión:</b> {escape(s['materia'])} pasa del "
                                              f"{reloj.corto(viejo['inicio'])} al {reloj.corto(s['inicio'])} ({escape(s['aula'])}).")
        return self.decir(chat, f"✅ Sesión movida al {reloj.corto(s['inicio'])} en {escape(s['aula'])}. "
                                f"Avisé a {len(avisar_a)} inscritos.", [MENU])

    # ------------------------------------------------------------ tutor
    def boton_tutor(self, chat, u, acc, p):
        nc, db = u["no_control"], self.db
        if acc == "tu_ver":
            lineas = []
            for t in reglas.tutorados(db, nc):
                hist = reglas.historial_alumno(db, t["no_control"])
                detalle = " · ".join(f"{escape(h['materia'])} {h['asistencias']}" for h in hist) or "sin asesorías"
                lineas.append(f"• {escape(reglas.nombre_corto(t))}: {detalle}")
            canal = reglas.canalizaciones_de(db, nc)
            texto = "<b>Tus tutorados</b> (asistencias del semestre)\n" + ("\n".join(lineas) or "• Sin tutorados asignados.")
            if canal:
                texto += "\n\n<b>Canalizaciones</b>\n" + "\n".join(
                    f"• {escape(c['alumno_nombre'] or c['alumno'])} → {escape(c['materia'])}: "
                    + (f"asistió ({c['asistio']})" if c["asistio"] else "aún no asiste") for c in canal[:10])
            return self.decir(chat, texto, [[("📨 Canalizar", "tu_can")], MENU])
        if acc == "tu_can":
            ts = reglas.tutorados(db, nc)
            if not ts:
                return self.decir(chat, "No tienes tutorados asignados.", [MENU])
            return self.decir(chat, "¿A quién quieres canalizar?",
                              [[(reglas.nombre_corto(t), f"tu_c1|{t['no_control']}")] for t in ts] + [MENU])
        if acc == "tu_c1":
            return self.decir(chat, "¿A qué materia?",
                              [[(m["nombre"], f"tu_c2|{p[0]}|{m['id']}")] for m in reglas.materias(db) if m["asesores"]])
        if acc == "tu_c2":
            alumno, mid_ = p[0], int(p[1])
            reglas.canalizar(db, nc, alumno, mid_, self.ahora)
            m = reglas.materia(db, mid_)
            t = reglas.usuario(db, alumno)
            ses = [s for s in reglas.proximas_sesiones(db, mid_, self.ahora) if s["inscritos"] < s["cupo"]][:3]
            enviados = avisar(db, self.tg, alumno,
                              f"📨 Tu tutor(a) te recomienda asesoría de <b>{escape(m['nombre'])}</b>. Elige una fecha:",
                              [[("✅ " + reloj.corto(s["inicio"]) + " · " + s["aula"], f"ins|{s['id']}")] for s in ses]
                              + [[("📚 Ver todas las fechas", f"ses|{mid_}")]])
            nota = "" if enviados else "\n(Aún no usa el bot: se le avisará cuando se registre con su número de control.)"
            return self.decir(chat, f"📨 Canalización enviada a {escape(reglas.nombre_corto(t))} ({escape(m['nombre'])}). "
                                    f"Te aviso si asiste o falta.{nota}", [MENU])
        return self.decir(chat, "No entendí ese botón. Toca /menu.", [MENU])

    # ------------------------------------------------------------ coordinación
    def boton_coord(self, chat, u, acc, p):
        db, ahora = self.db, self.ahora
        if acc == "co_asp":
            pend = reglas.aspirantes_pendientes(db)
            if not pend:
                return self.decir(chat, "No hay aspirantes pendientes. 🎉", [MENU])
            a = pend[0]
            return self.decir(chat, f"<b>Aspirante 1 de {len(pend)}:</b> {a['semestre']}.º semestre de "
                                    f"{escape(a['carrera'] or 'carrera no indicada')} · {escape(a['materia'])} · {escape(a['disponibilidad'])}\n"
                                    "Solicitud completa ✔️ · Semestre ✔️ · Aprobó la materia: <i>validar en kárdex</i>",
                              [[("✅ Aprobar", f"co_ap|{a['id']}"), ("❌ Rechazar", f"co_re|{a['id']}")], MENU])
        if acc == "co_ap":
            asp = reglas.resolver_aspirante(db, int(p[0]), True, None, ahora)
            avisar(db, self.tg, asp["no_control"], f"🎉 <b>¡Aprobado!</b> Ya eres asesor(a) de {escape(asp['materia'])}. "
                                                   "Registra tu horario desde el menú.", [MENU])
            return self.decir(chat, f"✅ Aprobado como asesor(a) de {escape(asp['materia'])}. Ya le avisé.",
                              [[("Siguiente aspirante", "co_asp")], MENU])
        if acc == "co_re":
            aid = int(p[0])
            self.poner_estado(chat, "rechazo", {"aid": aid})
            return self.decir(chat, "¿Motivo del rechazo? Elige uno o escríbelo.",
                              [[(m, f"co_rm|{aid}|{i}")] for i, m in enumerate(MOTIVOS_RECHAZO)])
        if acc == "co_rm":
            return self.rechazar(chat, int(p[0]), MOTIVOS_RECHAZO[int(p[1])])
        if acc in ("co_rep", "co_xs"):
            desde, hasta = reglas.semana_anterior(ahora)
            if acc == "co_rep":
                rep = reglas.reporte(db, desde, hasta)
                return self.decir(chat, reglas.texto_reporte(rep, "Reporte semanal"), [[("📥 Descargar en Excel", "co_xs")], MENU])
            ruta, _ = documentos.informe_xlsx(db, desde, hasta, f"reporte_semanal_{desde:%Y%m%d}.xlsx")
            self.tg.enviar_archivo(chat, ruta, "📥 Reporte semanal en Excel.")
            return None
        if acc == "co_inf":
            inicio, fin = reglas.inicio_semestre(db), reglas.fin_semestre(db)
            hasta = min(ahora, fin + timedelta(seconds=1))
            ruta, rep = documentos.informe_xlsx(db, inicio, hasta, f"informe_semestral_{hasta:%Y%m%d}.xlsx")
            self.tg.enviar_archivo(chat, ruta, f"📁 <b>Informe semestral</b> al {hasta:%d/%m/%Y}: {rep['realizadas']} sesiones, "
                                               f"{rep['asistencias']} asistencias, {rep['canceladas']} canceladas.")
            return None
        if acc == "co_con":
            lineas, botones = [], []
            for a in reglas.asesores(db):
                h, m = reglas.horas_asesor(db, a["no_control"]), reglas.meta_horas(db, a["no_control"])
                c = db.execute("SELECT * FROM constancias WHERE asesor=?", (a["no_control"],)).fetchone()
                marca = ("✅ firmada" if c and c["firmada"] else "📄 lista, falta firma") if c else f"{h:.0f}/{m} h"
                lineas.append(f"• {escape(a['materia'])} — {escape(reglas.nombre_corto(a))}: {marca}")
                if c:
                    fila = [(f"📄 PDF {reglas.nombre_corto(a)}", f"co_pdf|{a['no_control']}")]
                    if not c["firmada"]:
                        fila.append(("✍️ Marcar firmada", f"co_fir|{a['no_control']}"))
                    botones.append(fila)
            return self.decir(chat, "<b>Horas de los asesores</b>\n" + "\n".join(lineas), botones + [MENU])
        if acc == "co_pdf":
            ruta = documentos.constancia_pdf(db, p[0])
            self.tg.enviar_archivo(chat, ruta, "📄 Constancia lista para firma (RN‑07).")
            return None
        if acc == "co_fir":
            db.execute("UPDATE constancias SET firmada=1 WHERE asesor=?", (p[0],))
            db.commit()
            avisar(db, self.tg, p[0], "📄 Tu constancia ya está firmada. Recógela en la coordinación.")
            return self.decir(chat, "✍️ Marcada como firmada. Ya le avisé al asesor.", [[("📄 Constancias", "co_con")], MENU])
        if acc == "co_mat":
            lineas = [f"• {escape(m['nombre'])} ({escape(m['departamento'])}) — "
                      + (f"{m['asesores']} asesor(es)" if m["asesores"] else "⚠️ sin asesor") for m in reglas.materias(db)]
            return self.decir(chat, "<b>Materias del programa</b>\n" + "\n".join(lineas),
                              [[("➕ Agregar materia", "co_nm")], [("🏫 Aulas", "co_aul")], MENU])
        if acc == "co_aul":
            nombres = ", ".join(escape(a["nombre"]) for a in reglas.aulas(db))
            return self.decir(chat, "<b>Aulas del catálogo</b>\nSon las que el bot ofrece al asesor cuando están libres.\n"
                                    + nombres, [[("➕ Agregar aula", "co_na")], MENU])
        if acc == "co_na":
            self.poner_estado(chat, "aula_nueva")
            return self.decir(chat, "Escribe el nombre de la nueva aula (por ejemplo, «Aula 13» o «Sala audiovisual»).")
        if acc == "co_nm":
            self.poner_estado(chat, "materia_nueva")
            return self.decir(chat, "Escribe el nombre de la nueva materia.")
        if acc == "co_nd":
            est, datos = self.estado(chat)
            self.limpiar(chat)
            if est != "materia_depto":
                return self.decir(chat, "Ese registro ya no está abierto. Toca «Agregar materia» de nuevo.", [MENU])
            reglas.agregar_materia(db, datos["nombre"], DEPARTAMENTOS[int(p[0])])
            return self.decir(chat, f"✅ Materia «{escape(datos['nombre'])}» agregada. Aparece como «sin asesor» "
                                    "hasta que apruebes a un aspirante.", [MENU])
        if acc == "co_baj":
            return self.decir(chat, "¿Qué quieres dar de baja?",
                              [[("🧑‍🏫 Un asesor", "co_ba")], [("🗓️ Una sesión", "co_bs")], MENU])
        if acc == "co_ba":
            return self.decir(chat, "¿Qué asesor(a)? Sus sesiones futuras se cancelan y se avisa a sus inscritos.",
                              [[(f"{a['materia']} — {reglas.nombre_corto(a)}", f"co_ba1|{a['no_control']}")]
                               for a in reglas.asesores(db)] + [MENU])
        if acc == "co_ba1":
            a = reglas.asesor_activo(db, p[0])
            return self.decir(chat, f"¿Confirmas la baja de {escape(reglas.nombre_corto(reglas.usuario(db, p[0])))} "
                                    f"({escape(a['materia'])})?", [[("Sí, dar de baja", f"co_ba2|{p[0]}"), ("No", "menu")]])
        if acc == "co_ba2":
            afectadas = reglas.dar_baja_asesor(db, p[0], ahora)
            total = 0
            for s, alumnos in afectadas:
                self._avisar_cancelacion(s, alumnos, "el asesor fue dado de baja")
                total += len(alumnos)
            avisar(db, self.tg, p[0], "ℹ️ La coordinación registró tu baja como asesor(a). Gracias por tu apoyo.")
            return self.decir(chat, f"✅ Baja registrada. Ya no aparece en /materias. Se cancelaron {len(afectadas)} "
                                    f"sesiones y se avisó a {total} inscritos.", [MENU])
        if acc == "co_bs":
            ses = db.execute(reglas.SQL_SESION + " WHERE s.estado='programada' AND s.inicio>? AND s.inicio<=? ORDER BY s.inicio LIMIT 20",
                             (reloj.txt(ahora), reloj.txt(ahora + timedelta(days=7)))).fetchall()
            return self.decir(chat, "¿Qué sesión cancelas?",
                              [[(f"{reloj.corto(s['inicio'])} · {s['materia']}", f"co_bs1|{s['id']}")] for s in ses] + [MENU])
        if acc == "co_bs1":
            s = reglas.sesion(db, int(p[0]))
            return self.decir(chat, f"¿Cancelar {escape(s['materia'])} del {reloj.corto(s['inicio'])} ({s['inscritos']} inscritos)?",
                              [[("Sí, cancelar", f"co_bs2|{s['id']}"), ("No", "menu")]])
        if acc == "co_bs2":
            s, alumnos, _ = reglas.cancelar_sesion(db, int(p[0]), "Cancelada por la coordinación", ahora)
            self._avisar_cancelacion(s, alumnos, "decisión de la coordinación")
            avisar(db, self.tg, s["asesor"], f"ℹ️ La coordinación canceló tu sesión del {reloj.corto(s['inicio'])}.")
            return self.decir(chat, f"✅ Sesión cancelada. Avisé a {len(alumnos)} inscritos y al asesor.", [MENU])
        return self.decir(chat, "No entendí ese botón. Toca /menu.", [MENU])

    def rechazar(self, chat, aid, motivo):
        asp = reglas.resolver_aspirante(self.db, aid, False, motivo, self.ahora)
        avisar(self.db, self.tg, asp["no_control"],
               f"Tu solicitud para asesorar {escape(asp['materia'])} no fue aprobada. Motivo: {escape(motivo)}.")
        return self.decir(chat, "Rechazo registrado y aspirante avisado.", [[("Siguiente aspirante", "co_asp")], MENU])

    # ------------------------------------------------------------ jefatura
    def boton_jefatura(self, chat, u, acc, p):
        depto = u["departamento"]
        desde, hasta = reglas.semana_anterior(self.ahora)
        if acc == "je_rep":
            rep = reglas.reporte(self.db, desde, hasta, depto)
            return self.decir(chat, reglas.texto_reporte(rep, f"Reporte semanal · {escape(depto)}"),
                              [[("📥 Descargar en Excel", "je_xs")], MENU])
        if acc == "je_xs":
            ruta, _ = documentos.informe_xlsx(self.db, desde, hasta, f"reporte_{desde:%Y%m%d}_{u['no_control']}.xlsx", depto)
            self.tg.enviar_archivo(chat, ruta, f"📥 Reporte de {escape(depto)} en Excel.")
            return None
        return self.decir(chat, "No entendí ese botón. Toca /menu.", [MENU])
