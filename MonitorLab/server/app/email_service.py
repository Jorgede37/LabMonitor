
import os
import smtplib
import ssl
import logging

from pathlib import Path
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from dotenv import load_dotenv
from sqlalchemy import text

from app.database import engine


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)


def obtener_configuracion():
    return {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "from_email": os.getenv("SMTP_FROM", "").strip(),
        "from_name": os.getenv(
            "SMTP_FROM_NAME",
            "LabMonitor"
        ).strip(),
        "use_tls": os.getenv(
            "SMTP_USE_TLS",
            "true"
        ).lower() == "true",
    }


def obtener_correos_administradores():
    """Return unique email addresses for currently active administrators."""
    with engine.connect() as connection:
        resultado = connection.execute(
            text("""
                SELECT email
                FROM dbo.users
                WHERE role = 'admin'
                  AND is_active = 1
                  AND email IS NOT NULL
                  AND LTRIM(RTRIM(email)) <> ''
                ORDER BY id
            """)
        )
        correos = resultado.scalars().all()

    destinatarios = []
    vistos = set()
    for valor in correos:
        if not isinstance(valor, str):
            continue
        correo = valor.strip()
        clave = correo.casefold()
        _nombre, direccion = parseaddr(correo)
        if (
            not correo
            or direccion.casefold() != clave
            or correo.count("@") != 1
            or "." not in correo.rsplit("@", 1)[1]
            or any(caracter.isspace() for caracter in correo)
            or "\r" in correo
            or "\n" in correo
            or clave in vistos
        ):
            continue
        vistos.add(clave)
        destinatarios.append(correo)

    return destinatarios


def obtener_estado_configuracion_correo():
    config = obtener_configuracion()
    destinatarios = obtener_correos_administradores()
    smtp_configurado = (
        bool(config["host"])
        and config["port"] > 0
        and bool(config["user"])
        and bool(config["password"])
        and not config["password"].startswith("PEGA_AQUI")
        and bool(config["use_tls"])
    )

    return {
        "smtp_configured": smtp_configurado,
        "recipient_count": len(destinatarios),
        "ready": smtp_configurado and bool(destinatarios)
    }


def enviar_correo(destinatario, asunto, mensaje):
    config = obtener_configuracion()

    if not config["user"] or not config["password"]:
        raise RuntimeError(
            "Faltan las credenciales SMTP en server/.env"
        )

    if config["password"].startswith("PEGA_AQUI"):
        raise RuntimeError(
            "Debes configurar SMTP_PASSWORD en server/.env"
        )

    if not config["use_tls"]:
        raise RuntimeError(
            "LabMonitor requiere una conexión SMTP segura."
        )

    destinatarios = (
        [destinatario]
        if isinstance(destinatario, str)
        else list(destinatario)
    )

    destinatarios = [
        correo.strip()
        for correo in destinatarios
        if isinstance(correo, str) and correo.strip()
    ]

    if not destinatarios:
        raise ValueError(
            "No se especificaron destinatarios."
        )

    for correo in destinatarios:
        nombre, direccion = parseaddr(correo)

        if (
            not direccion
            or "@" not in direccion
            or "\r" in correo
            or "\n" in correo
        ):
            raise ValueError(
                "Se encontró un destinatario inválido."
            )

    correo = EmailMessage()

    correo["From"] = formataddr((
        config["from_name"],
        config["from_email"] or config["user"]
    ))

    correo["To"] = ", ".join(destinatarios)
    correo["Subject"] = asunto
    correo.set_content(mensaje)

    contexto = ssl.create_default_context()

    try:
        with smtplib.SMTP(
            config["host"],
            config["port"],
            timeout=20
        ) as servidor:

            servidor.ehlo()
            servidor.starttls(context=contexto)
            servidor.ehlo()

            servidor.login(
                config["user"],
                config["password"]
            )

            servidor.send_message(correo)

        logger.info(
            "Correo enviado correctamente a %s",
            ", ".join(destinatarios)
        )

        return True

    except smtplib.SMTPAuthenticationError:
        logger.exception(
            "Google rechazó la autenticación SMTP."
        )
        raise

    except Exception:
        logger.exception(
            "Error al enviar correo desde LabMonitor."
        )
        raise


def enviar_alerta_hardware(
    computadora,
    laboratorio,
    evento,
    componente,
    fecha,
    estudiante="Sin sesión identificada",
    destinatarios=None
):
    if destinatarios is None:
        destinatarios = obtener_correos_administradores()

    if not destinatarios:
        raise RuntimeError(
            "No hay correos administrativos configurados."
        )

    asunto = (
        f"[LabMonitor] Alerta de hardware - {computadora}"
    )

    mensaje = f"""
LABMONITOR - ALERTA DE HARDWARE

Se ha detectado un cambio de hardware
en una computadora monitoreada.

========================================

COMPUTADORA:
{computadora}

LABORATORIO:
{laboratorio}

EVENTO:
{evento}

COMPONENTE:
{componente}

FECHA Y HORA:
{fecha}

ESTUDIANTE:
{estudiante}

========================================

Este correo fue generado automáticamente
por LabMonitor.

Departamento de Sistemas
Universidad de Durango
Campus Aguascalientes
"""

    return enviar_correo(
        destinatarios,
        asunto,
        mensaje
    )


def enviar_recuperacion_password(
    destinatario,
    nombre,
    enlace
):
    asunto = (
        "LabMonitor - Recuperación de contraseña"
    )

    mensaje = f"""
Hola, {nombre}:

Recibimos una solicitud para restablecer
la contraseña de tu cuenta de LabMonitor.

Abre el siguiente enlace para establecer
una nueva contraseña:

{enlace}

El enlace será válido durante 15 minutos
y podrá utilizarse una sola vez.

Si no solicitaste este cambio,
puedes ignorar este mensaje.

========================================

LabMonitor
Departamento de Sistemas
Universidad de Durango
Campus Aguascalientes
"""

    return enviar_correo(
        destinatario,
        asunto,
        mensaje
    )


def enviar_verificacion_correo(
    destinatario,
    nombre,
    enlace
):
    asunto = (
        "LabMonitor - Verifica tu correo electrónico"
    )

    mensaje = f"""
Hola, {nombre}:

Gracias por registrarte en LabMonitor.

Para verificar tu correo electrónico,
abre el siguiente enlace:

{enlace}

Si no creaste una cuenta de LabMonitor,
puedes ignorar este mensaje.

========================================

LabMonitor
Departamento de Sistemas
Universidad de Durango
Campus Aguascalientes
"""

    return enviar_correo(
        destinatario,
        asunto,
        mensaje
    )


def enviar_codigo_verificacion(
    destinatario,
    nombre,
    codigo
):
    asunto = "LabMonitor - Código de seguridad"
    mensaje = f"""
Hola, {nombre}:

Se creó una cuenta de estudiante para LabMonitor.
Ingresa este código en la aplicación LabMonitor para
verificar tu correo y habilitar el inicio de sesión:

{codigo}

El código vence en 15 minutos y solo puede usarse una vez.
Si no solicitaste esta cuenta, puedes ignorar este mensaje.

========================================

LabMonitor
Universidad de Durango
Campus Aguascalientes
"""

    return enviar_correo(destinatario, asunto, mensaje)
