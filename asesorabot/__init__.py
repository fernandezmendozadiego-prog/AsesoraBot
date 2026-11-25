"""AsesoraBot: gestión del Programa de Asesorías Académicas entre Pares por Telegram.

Todo el sistema está escrito en Python:
  config     -> lee la configuración (token, base de datos) de variables de entorno
  reloj      -> hora local de México (UTC-6) y formatos de fecha
  db         -> crea y abre la base de datos SQLite
  reglas     -> reglas de negocio RN-01..RN-11 (sin nada de Telegram)
  bot        -> manejadores: convierte mensajes y botones de Telegram en llamadas a reglas
  tareas     -> tareas programadas: recordatorios, avisos al tutor, reportes, constancias
  documentos -> constancia en PDF (reportlab) e informes en Excel (openpyxl)
  telegram_api -> cliente mínimo de la Bot API de Telegram (HTTPS + JSON)
  semilla    -> datos SIMULADOS para la demostración
"""
