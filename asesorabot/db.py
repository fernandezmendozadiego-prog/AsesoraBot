"""Base de datos SQLite (un solo archivo, sin servidor aparte).

Se guarda en UTF-8, por eso «Cálculo» o «Química» se conservan con acentos.
"""
import sqlite3
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios(
  no_control   TEXT PRIMARY KEY,          -- único dato personal que pide el bot (RNF-04)
  nombre       TEXT,                      -- solo en datos simulados
  rol          TEXT NOT NULL DEFAULT 'alumno',  -- alumno | asesor | tutor | coord | jefatura
  carrera      TEXT,
  semestre     INTEGER,
  tutor        TEXT,                      -- no_control del tutor asignado (RN-11)
  departamento TEXT                       -- para jefaturas (RF-20)
);
CREATE TABLE IF NOT EXISTS vinculos(       -- chat de Telegram -> número de control
  chat_id    INTEGER PRIMARY KEY,
  no_control TEXT NOT NULL REFERENCES usuarios(no_control)
);
CREATE TABLE IF NOT EXISTS invitaciones(   -- enlaces de alta para coordinación, tutores y jefaturas
  codigo TEXT PRIMARY KEY, no_control TEXT NOT NULL, usada INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS materias(
  id INTEGER PRIMARY KEY, nombre TEXT UNIQUE NOT NULL, departamento TEXT NOT NULL,
  activa INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS asesores(
  no_control TEXT PRIMARY KEY REFERENCES usuarios(no_control),
  materia_id INTEGER NOT NULL REFERENCES materias(id),
  activo INTEGER DEFAULT 1, alta TEXT
);
CREATE TABLE IF NOT EXISTS horarios(       -- horario semanal que publica el asesor (RF-17)
  id INTEGER PRIMARY KEY, asesor TEXT, materia_id INTEGER, dia INTEGER, hora TEXT,
  aula TEXT, cupo INTEGER DEFAULT 15, activo INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sesiones(       -- cada fecha concreta de asesoría
  id INTEGER PRIMARY KEY, horario_id INTEGER, asesor TEXT, materia_id INTEGER,
  inicio TEXT, duracion INTEGER DEFAULT 60, aula TEXT, cupo INTEGER DEFAULT 15,
  estado TEXT DEFAULT 'programada',        -- programada | cancelada
  motivo TEXT, cancelada_en TEXT, tardia INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_sesiones_inicio ON sesiones(inicio);
CREATE TABLE IF NOT EXISTS inscripciones(
  sesion_id INTEGER, no_control TEXT, creada TEXT, PRIMARY KEY(sesion_id, no_control)
);
CREATE TABLE IF NOT EXISTS codigos(        -- código de asistencia de 2 minutos (RNF-10)
  id INTEGER PRIMARY KEY, sesion_id INTEGER, codigo TEXT, creado TEXT, vence TEXT,
  activo INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS asistencias(
  sesion_id INTEGER, no_control TEXT, registrada TEXT, calificacion INTEGER,
  PRIMARY KEY(sesion_id, no_control)      -- una sola vez por número de control
);
CREATE TABLE IF NOT EXISTS canalizaciones(
  id INTEGER PRIMARY KEY, tutor TEXT, alumno TEXT, materia_id INTEGER, creada TEXT
);
CREATE TABLE IF NOT EXISTS aspirantes(
  id INTEGER PRIMARY KEY, no_control TEXT, semestre INTEGER, materia_id INTEGER,
  disponibilidad TEXT, estado TEXT DEFAULT 'pendiente', motivo TEXT, creada TEXT
);
CREATE TABLE IF NOT EXISTS constancias(
  asesor TEXT PRIMARY KEY, horas REAL, meta INTEGER, generada TEXT, firmada INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS enviados(       -- evita mandar dos veces el mismo aviso automático
  clave TEXT PRIMARY KEY, cuando TEXT
);
CREATE TABLE IF NOT EXISTS estados(        -- en qué paso de una conversación va cada chat
  chat_id INTEGER PRIMARY KEY, estado TEXT, datos TEXT
);
CREATE TABLE IF NOT EXISTS aulas(          -- catálogo que administra la coordinación (mejora de la prueba PU-01)
  id INTEGER PRIMARY KEY, nombre TEXT UNIQUE NOT NULL COLLATE NOCASE, activa INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS config(clave TEXT PRIMARY KEY, valor TEXT);
"""


def conectar(ruta):
    if ruta != ":memory:":
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta, check_same_thread=False, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(ESQUEMA)
    return con


def get_config(con, clave, defecto=None):
    fila = con.execute("SELECT valor FROM config WHERE clave=?", (clave,)).fetchone()
    return fila[0] if fila else defecto


def set_config(con, clave, valor):
    con.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (clave, str(valor)))
    con.commit()
