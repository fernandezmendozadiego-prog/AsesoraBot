# AsesoraBot · Andamio Digital

Bot de Telegram que automatiza el **Programa de Asesorías Académicas entre Pares**: inscripción con cupo, recordatorios, asistencia con código de 2 minutos, horas y constancias de asesores, canalización de tutores y reportes automáticos.

- **Lenguaje:** todo el sistema está en **Python 3**. No usa PHP, JavaScript ni HTML.
- **Base de datos:** SQLite (un archivo, en UTF-8).
- **Dónde corre:** en la nube (PythonAnywhere). Los usuarios solo necesitan Telegram, en el celular, la PC o la tableta.

## Estructura

| Archivo | Qué hace |
|---|---|
| `asesorabot/reglas.py` | Reglas de negocio RN‑01 a RN‑11 (cupo, choques, código, horas, metas) |
| `asesorabot/bot.py` | Menús y botones por rol (alumno, asesor, tutor, coordinación, jefatura) |
| `asesorabot/tareas.py` | Recordatorios, avisos al tutor, constancias, reportes semanales y el semestral |
| `asesorabot/documentos.py` | Constancia en PDF (reportlab) e informes en Excel (openpyxl) |
| `asesorabot/telegram_api.py` | Comunicación con Telegram (HTTPS + JSON) |
| `asesorabot/db.py` | Tablas de la base de datos |
| `asesorabot/semilla.py` | Datos **SIMULADOS** para la demostración |
| `app.py` | Aplicación web para la nube (webhook) |
| `local.py` | Modo local para desarrollar (polling) |
| `admin.py` | Crear la base de datos, conectar el webhook, invitaciones |
| `tests/` | Pruebas PR‑01 a PR‑27 |

## Instalar y probar en la computadora

```powershell
pip install -r requirements.txt
python -m pytest -v          # corre las 29 pruebas, no necesita internet
python admin.py iniciar      # crea datos/asesorabot.db con los datos simulados
```

Para hablar con el bot desde tu computadora:

1. Copia `.env.ejemplo` como `.env`.
2. Pega en `BOT_TOKEN` el token que te dio @BotFather.
3. Ejecuta `python local.py`.

## Subirlo a la nube (PythonAnywhere, cuenta gratuita)

Todo esto lo haces **tú** con tu cuenta; el token nunca se comparte.

1. **Crea el bot.** En Telegram, abre @BotFather, escribe `/newbot`, elige el nombre (por ejemplo *AsesoraBot ITMH*) y el usuario (por ejemplo `asesorabot_itmh_bot`). Guarda el token.
2. **Crea la cuenta** en <https://www.pythonanywhere.com> con el plan *Beginner* (gratis). Tu dirección será `https://USUARIO.pythonanywhere.com`.
3. **Sube el código.** En la pestaña **Files**, sube `AsesoraBot.zip`. Después abre una consola **Bash** y ejecuta:
   ```bash
   unzip AsesoraBot.zip -d AsesoraBot
   cd AsesoraBot
   pip3.12 install --user -r requirements.txt
   cp .env.ejemplo .env
   nano .env            # pega BOT_TOKEN e inventa WEBHOOK_SECRET y TICK_KEY; guarda con Ctrl+O y sal con Ctrl+X
   python3.12 admin.py probar     # debe responder "ok": True con el nombre de tu bot
   python3.12 admin.py iniciar    # carga los datos simulados
   ```
4. **Publica la aplicación web.** Ve a la pestaña **Web** y elige *Add a new web app* → *Manual configuration* → *Python 3.12*. Abre el *WSGI configuration file*, borra lo que trae y pega el contenido de `pythonanywhere_wsgi.py` con tu usuario. Guarda y toca **Reload**. Si abres `https://USUARIO.pythonanywhere.com` debe decir «AsesoraBot en línea ✅».
5. **Conecta Telegram con la nube.** En la consola Bash ejecuta:
   ```bash
   python3.12 admin.py webhook https://USUARIO.pythonanywhere.com
   ```
6. **Activa las tareas de cada minuto** (recordatorios y reportes). Crea una cuenta gratis en <https://cron-job.org> y agrega un *cronjob*:
   - URL: `https://USUARIO.pythonanywhere.com/tick?clave=TU_TICK_KEY`
   - Frecuencia: cada minuto

   Las tareas también se revisan cada vez que alguien le escribe al bot.
7. **Pruébalo.** En Telegram busca tu bot, escribe `/start` y toca **🧪 Probar con datos simulados**.

> La cuenta gratuita pide entrar **cada mes** a la pestaña **Web** y tocar *Run until 1 month from today* para que la aplicación no se apague. Revisa la fecha que aparece ahí.

## Cómo lo prueba el profesor

Le basta con abrir Telegram, buscar el bot y escribir `/start`; no tiene que instalar nada. Con `/demo` cambia de rol:

- **🎓 Alumno:** ver asesorías, buscar «calc», inscribirse, ver una sesión llena, cancelar, escribir el código y calificar, postularse como asesor.
- **🧑‍🏫 Asesor (Óscar, Cálculo Diferencial):**
  - registrar un horario: el bot muestra como botones solo las aulas libres a esa hora (o «Otra aula» para escribirla);
  - tocar **🧪 Sesión de prueba ahora** y luego **🔑 Mostrar código**;
  - cancelar o mover una sesión;
  - ver sus horas.
- **📋 Tutor:** ver tutorados, canalizar a uno a una materia.
- **🗂️ Coordinación:** aprobar o rechazar aspirantes, ver el reporte semanal, descargar el Excel, generar el PDF de constancia, ver el informe semestral, agregar materias y aulas (Materias → 🏫 Aulas) y dar de baja.
- **🏛️ Jefatura:** reporte solo de las materias de su departamento.

Para probar la asistencia completa se puede usar un segundo teléfono: uno como asesor y otro como alumno.

## Actualizar el bot en la nube

1. Sube el `AsesoraBot.zip` nuevo en la pestaña **Files** (reemplaza al anterior).
2. En la consola **Bash**:
   ```bash
   cd ~
   unzip -o AsesoraBot.zip -d AsesoraBot
   cd ~/AsesoraBot && python3.12 -m pytest -q
   ```
   El archivo `.env` no viene en el zip, así que se conserva.
3. En la pestaña **Web**, toca **Reload**.

## Seguridad y privacidad

- El bot pide **solo el número de control** (8 dígitos). Cada rol ve únicamente lo suyo.
- El token va en el archivo `.env`, que no se sube a ningún lado; no está dentro del código.
- Telegram firma cada mensaje con la clave `WEBHOOK_SECRET`; si alguien llama a `/webhook` sin ella, recibe 403.
- El código de asistencia dura 2 minutos, vale una vez por número de control y se anula si el asesor pide otro.
- El certificado HTTPS lo ponen Telegram y PythonAnywhere: no hay que comprar ni renovar ninguno.
