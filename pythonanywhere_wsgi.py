# Contenido para el archivo WSGI de PythonAnywhere (pestaña Web -> «WSGI configuration file»).
# Cambia USUARIO por tu nombre de usuario de PythonAnywhere.
import os
import sys

RUTA = "/home/USUARIO/AsesoraBot"
if RUTA not in sys.path:
    sys.path.insert(0, RUTA)
os.chdir(RUTA)

from app import app as application  # noqa: E402,F401
