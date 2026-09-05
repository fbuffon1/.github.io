"""
reminder_bot.py

Revisa tasks.json y envía recordatorios por correo (Gmail, con contraseña de
aplicación) según el estado de cada tarea:

  - backlog (Abierto)  -> cada 5 minutos
  - progreso           -> cada 60 minutos
  - revision           -> cada 120 minutos
  - completado         -> nunca envía nada

Solo empieza a recordar una tarea a partir de la fecha/hora programada (no
antes). Cada tarea recuerda cuándo fue el último correo enviado (lastSent) y
ese dato se guarda de vuelta en tasks.json para no perder el conteo entre
ejecuciones.

Se ejecuta automáticamente vía GitHub Actions (ver .github/workflows/reminders.yml),
pero también puede correr localmente con:  python reminder_bot.py
"""

import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

TASKS_FILE = Path(__file__).parent / "tasks.json"

# Segundos entre recordatorios, según el estado de la tarea
INTERVALS_SECONDS = {
    "backlog": 5 * 60,
    "progreso": 60 * 60,
    "revision": 2 * 60 * 60,
    "completado": None,  # nunca
}

# Mensaje distinto según el estado
SPEECHES = {
    "backlog": lambda t: (
        f"Recordatorio: '{t['title']}'",
        f"Tu tarea \"{t['title']}\" sigue en Backlog (Abierto) y estaba "
        f"programada para las {t['time']} del {t['day']}. Aun no la has iniciado.",
    ),
    "progreso": lambda t: (
        f"Sigue en progreso: '{t['title']}'",
        f"Tu tarea \"{t['title']}\" sigue En Progreso (programada {t['time']} "
        f"del {t['day']}). No la olvides.",
    ),
    "revision": lambda t: (
        f"Pendiente de revision: '{t['title']}'",
        f"Tu tarea \"{t['title']}\" sigue En Revision (programada {t['time']} "
        f"del {t['day']}). Revisa su estado cuando puedas.",
    ),
}

TZ_NAME = os.environ.get("REMINDER_TZ", "America/Mexico_City")


def send_email(gmail_user, gmail_app_password, to_email, subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_app_password)
        server.sendmail(gmail_user, [to_email], msg.as_string())


def load_tasks():
    if not TASKS_FILE.exists():
        return {"settings": {"recipientEmail": ""}, "days": [], "tasks": []}
    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tasks(data):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_app_password:
        print("Faltan GMAIL_USER o GMAIL_APP_PASSWORD (configuralos como GitHub Secrets).")
        sys.exit(1)

    data = load_tasks()
    tasks = data.get("tasks", [])
    recipient = data.get("settings", {}).get("recipientEmail") or gmail_user

    tz = ZoneInfo(TZ_NAME)
    now = datetime.now(tz)

    changed = False

    for task in tasks:
        status = task.get("status", "backlog")
        interval = INTERVALS_SECONDS.get(status)

        if interval is None:
            # completado, o estado desconocido -> nunca enviar
            continue

        try:
            scheduled = datetime.strptime(
                f"{task['day']} {task['time']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=tz)
        except (KeyError, ValueError):
            continue

        # Tareas con rango (endDay) siguen activas cada dia hasta esa fecha
        end_day = task.get("endDay") or task.get("day")
        try:
            end_of_range = datetime.strptime(f"{end_day} 23:59", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        except ValueError:
            end_of_range = scheduled

        if now < scheduled:
            continue  # todavia no llega la hora programada
        if now > end_of_range:
            continue  # el rango de repeticion ya termino

        last_sent_raw = task.get("lastSent")
        should_send = last_sent_raw is None
        if not should_send:
            try:
                last_sent = datetime.fromisoformat(last_sent_raw)
                should_send = (now - last_sent).total_seconds() >= interval
            except ValueError:
                should_send = True

        if should_send:
            subject, body = SPEECHES[status](task)
            try:
                send_email(gmail_user, gmail_app_password, recipient, subject, body)
                print(f"Correo enviado: [{status}] {task['title']}")
                task["lastSent"] = now.isoformat()
                changed = True
            except Exception as e:
                print(f"Error enviando correo para '{task['title']}': {e}")

    if changed:
        save_tasks(data)
        print("tasks.json actualizado.")
    else:
        print("Sin recordatorios pendientes por ahora.")


if __name__ == "__main__":
    main()
