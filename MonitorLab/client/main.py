
import ctypes
import json
import os
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from ctypes import wintypes

import requests
import win32con
import win32file
import win32pipe
import pywintypes

from service_control import detener_servicio_elevado


# ==========================================
# CONFIGURACION
# ==========================================

PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", str(Path.home())))
CLIENT_CONFIG_FILE = PROGRAM_DATA / "LabMonitor" / "client.env"
RESOURCE_DIR = Path(
    getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
)
UAD_MARK_FILE = RESOURCE_DIR / "assets" / "uad_mark.png"


def obtener_url_servidor():
    url_entorno = os.environ.get("LABMONITOR_SERVER_URL")

    if url_entorno:
        return url_entorno.strip().rstrip("/")

    if CLIENT_CONFIG_FILE.is_file():
        try:
            with CLIENT_CONFIG_FILE.open("r", encoding="utf-8-sig") as archivo:
                for linea in archivo:
                    linea = linea.strip()

                    if not linea or linea.startswith("#") or "=" not in linea:
                        continue

                    clave, valor = linea.split("=", 1)

                    if clave.strip() == "LABMONITOR_SERVER_URL":
                        url = valor.strip().strip('"').strip("'")

                        if url:
                            return url.rstrip("/")

        except OSError:
            pass

    return "http://127.0.0.1:8000"


SERVER_URL = obtener_url_servidor()

PIPE_NAME = r"\\.\pipe\LabMonitorStudent"

COLOR_FONDO = "#211720"
COLOR_TARJETA = "#30232e"
COLOR_TEXTO = "#fbf7f2"
COLOR_SECUNDARIO = "#d0c2c6"
COLOR_PRINCIPAL = "#762642"
COLOR_ERROR = "#f3a5a5"
COLOR_EXITO = "#9ad4a5"
COLOR_ADVERTENCIA = "#e1c47c"
COLOR_DORADO = "#c5a15b"

VERIFICATION_INTERVAL = 5000
SESSION_CHECK_INTERVAL = 5000
ACTIVITY_CHECK_INTERVAL = 1000


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD)
    ]


def obtener_ultimo_input_tick():
    informacion = LASTINPUTINFO()
    informacion.cbSize = ctypes.sizeof(LASTINPUTINFO)

    if not ctypes.windll.user32.GetLastInputInfo(
        ctypes.byref(informacion)
    ):
        raise OSError(
            "No se pudo consultar la actividad de la sesión interactiva."
        )

    return informacion.dwTime


# ==========================================
# COMUNICACION CON EL AGENTE
# ==========================================

class ErrorAgente(Exception):
    pass


def solicitar_agente(
    accion,
    student_token=None,
    session_id=None,
    admin_token=None,
    server_url=None,
    local_admin_username=None,
    local_admin_password=None,
    operation=None,
    windows_account=None
):
    solicitud = {
        "action": accion
    }

    if student_token is not None:
        solicitud["student_token"] = student_token

    if session_id is not None:
        solicitud["session_id"] = session_id

    if admin_token is not None:
        solicitud["admin_token"] = admin_token

    if server_url is not None:
        solicitud["server_url"] = server_url

    if local_admin_username is not None:
        solicitud["local_admin_username"] = local_admin_username

    if local_admin_password is not None:
        solicitud["local_admin_password"] = local_admin_password

    if operation is not None:
        solicitud["operation"] = operation

    if windows_account is not None:
        solicitud["windows_account"] = windows_account

    operacion = "WaitNamedPipe"

    try:
        win32pipe.WaitNamedPipe(
            PIPE_NAME,
            5000
        )

        operacion = "CreateFile"

        pipe = win32file.CreateFile(
            PIPE_NAME,
            0x0001 | 0x0002 | 0x0100 | 0x00100000,
            0,
            None,
            win32con.OPEN_EXISTING,
            0,
            None
        )

    except pywintypes.error as error:
        raise ErrorAgente(
            f"Operacion: {operacion}. "
            f"Codigo Windows: {error.winerror}. "
            f"Detalle: {error.strerror}"
        ) from error

    try:
        win32pipe.SetNamedPipeHandleState(
            pipe,
            win32pipe.PIPE_READMODE_MESSAGE,
            None,
            None
        )

        contenido = json.dumps(
            solicitud
        ).encode("utf-8")

        win32file.WriteFile(
            pipe,
            contenido
        )

        _, respuesta_bytes = win32file.ReadFile(
            pipe,
            65536
        )

        respuesta = json.loads(
            respuesta_bytes.decode("utf-8")
        )

        if not isinstance(respuesta, dict):
            raise ErrorAgente(
                "El agente devolvio una respuesta invalida."
            )

        if not respuesta.get("ok"):
            raise ErrorAgente(
                str(
                    respuesta.get(
                        "error",
                        "El agente rechazo la operacion."
                    )
                )
            )

        return respuesta.get("data", {})

    except (
        pywintypes.error,
        json.JSONDecodeError,
        UnicodeDecodeError
    ) as error:
        raise ErrorAgente(
            "Se perdio la comunicacion con el agente. "
            "El estado de la sesion debe verificarse."
        ) from error

    finally:
        win32file.CloseHandle(pipe)


# ==========================================
# APLICACION
# ==========================================

class LabMonitorClient:

    def __init__(self, root):
        self.root = root

        self.root.title(
            "LabMonitor - Acceso de estudiantes"
        )

        self.root.attributes("-fullscreen", True)
        self.root.resizable(False, False)
        self.root.configure(bg=COLOR_FONDO)
        self._revision_barra_tareas = None
        self._mostrar_barra_tareas(False)
        self._programar_ocultar_barra_tareas()
        self.logo_image = tk.PhotoImage(file=str(UAD_MARK_FILE))
        self.root.bind_class(
            "Button",
            "<Enter>",
            self._boton_al_entrar,
            add="+"
        )
        self.root.bind_class(
            "Button",
            "<Leave>",
            self._boton_al_salir,
            add="+"
        )

        self.usuario = None
        self.token = None
        self.session_id = None

        self.operacion_en_curso = False
        self.cierre_pendiente = False
        self.verificacion_en_curso = False
        self.verificacion_programada = None
        self.revision_sesion_programada = None
        self.revision_sesion_en_curso = False
        self.actividad_programada = None
        self.actividad_en_curso = False
        self.ultimo_input_tick = None

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.al_cerrar_ventana
        )

        self.configuracion = None
        self.admin_token = None
        self.modo_admin = None
        self.cambio_acceso_asignado_en_curso = False
        self.canvas_desplazamiento = None
        self.ventana_desplazamiento = None
        self.admin_refresh_generation = 0

        self.consultar_configuracion_inicial()

    # ======================================
    # INTERFAZ GENERAL
    # ======================================

    def _mostrar_barra_tareas(self, visible):
        if os.name != "nt":
            return

        estado = 5 if visible else 0
        user32 = ctypes.windll.user32
        encontrar_ventana = user32.FindWindowW
        encontrar_ventana.argtypes = (
            wintypes.LPCWSTR,
            wintypes.LPCWSTR
        )
        encontrar_ventana.restype = wintypes.HWND
        mostrar_ventana = user32.ShowWindow
        mostrar_ventana.argtypes = (wintypes.HWND, ctypes.c_int)
        mostrar_ventana.restype = wintypes.BOOL

        ventanas = set()
        principal = encontrar_ventana("Shell_TrayWnd", None)
        if principal:
            ventanas.add(principal)

        enumerar_ventanas = user32.EnumWindows
        enumerar_ventanas.argtypes = (
            ctypes.WINFUNCTYPE(
                wintypes.BOOL,
                wintypes.HWND,
                wintypes.LPARAM
            ),
            wintypes.LPARAM
        )
        enumerar_ventanas.restype = wintypes.BOOL
        obtener_clase = user32.GetClassNameW
        obtener_clase.argtypes = (
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int
        )
        obtener_clase.restype = ctypes.c_int
        clase_secundaria = "Shell_SecondaryTrayWnd"

        @ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM
        )
        def recolectar_barra(ventana, _parametro):
            nombre_clase = ctypes.create_unicode_buffer(128)
            obtener_clase(
                ventana,
                nombre_clase,
                len(nombre_clase)
            )
            if nombre_clase.value == clase_secundaria:
                ventanas.add(ventana)
            return True

        enumerar_ventanas(recolectar_barra, 0)

        for ventana in ventanas:
            if visible or user32.IsWindowVisible(ventana):
                mostrar_ventana(ventana, estado)

    def _programar_ocultar_barra_tareas(self):
        if self._revision_barra_tareas is not None:
            return

        self._revision_barra_tareas = self.root.after(
            250,
            self._ocultar_barra_tareas_si_activa
        )

    def _ocultar_barra_tareas_si_activa(self):
        self._revision_barra_tareas = None
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return

        if self.session_id is not None:
            self._mostrar_barra_tareas(True)
            return

        self._mostrar_barra_tareas(False)
        self._programar_ocultar_barra_tareas()

    def _restaurar_barra_tareas_al_salir(self):
        if self._revision_barra_tareas is not None:
            try:
                self.root.after_cancel(
                    self._revision_barra_tareas
                )
            except tk.TclError:
                pass
            self._revision_barra_tareas = None
        self._mostrar_barra_tareas(True)

    def limpiar(self):
        self.admin_refresh_generation += 1
        if self.canvas_desplazamiento is not None:
            for secuencia in ("<MouseWheel>", "<Prior>", "<Next>"):
                self.root.unbind_all(secuencia)
            self.canvas_desplazamiento = None
            self.ventana_desplazamiento = None

        for widget in self.root.winfo_children():
            widget.destroy()

    def crear_tarjeta(self):
        contenedor = tk.Frame(
            self.root,
            bg=COLOR_FONDO
        )
        contenedor.pack(fill="both", expand=True)

        canvas = tk.Canvas(
            contenedor,
            bg=COLOR_FONDO,
            borderwidth=0,
            highlightthickness=0
        )
        barra_desplazamiento = ttk.Scrollbar(
            contenedor,
            orient="vertical",
            command=canvas.yview
        )
        canvas.configure(yscrollcommand=barra_desplazamiento.set)
        barra_desplazamiento.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        tarjeta = tk.Frame(
            canvas,
            bg=COLOR_TARJETA,
            padx=35,
            pady=30
        )

        ventana = canvas.create_window(
            (0, 0),
            window=tarjeta,
            anchor="nw",
            width=max(canvas.winfo_width(), 1)
        )
        self.canvas_desplazamiento = canvas
        self.ventana_desplazamiento = ventana

        def actualizar_region(_evento=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def ajustar_ancho(evento):
            canvas.itemconfigure(ventana, width=evento.width)

        def desplazar_rueda(evento):
            if evento.delta:
                canvas.yview_scroll(
                    -int(evento.delta / 120),
                    "units"
                )

        def desplazar_pagina(evento):
            canvas.yview_scroll(
                -1 if evento.keysym == "Prior" else 1,
                "pages"
            )
            return "break"

        tarjeta.bind("<Configure>", actualizar_region)
        canvas.bind("<Configure>", ajustar_ancho)
        self.root.bind_all("<MouseWheel>", desplazar_rueda, add="+")
        self.root.bind_all("<Prior>", desplazar_pagina, add="+")
        self.root.bind_all("<Next>", desplazar_pagina, add="+")

        marca = tk.Frame(tarjeta, bg=COLOR_TARJETA)
        marca.pack(anchor="center", pady=(0, 18))

        tk.Label(
            marca,
            image=self.logo_image,
            bg=COLOR_TARJETA,
            borderwidth=0
        ).pack(side="left", padx=(0, 14))

        identidad = tk.Frame(marca, bg=COLOR_TARJETA)
        identidad.pack(side="left", anchor="center")

        tk.Label(
            identidad,
            text="Universidad de Durango",
            font=("Segoe UI", 16, "bold"),
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO,
            anchor="w"
        ).pack(anchor="w")

        tk.Label(
            identidad,
            text="Campus Aguascalientes",
            font=("Segoe UI", 11),
            bg=COLOR_TARJETA,
            fg=COLOR_DORADO,
            anchor="w"
        ).pack(anchor="w", pady=(4, 0))

        tk.Frame(
            tarjeta,
            bg=COLOR_DORADO,
            height=2
        ).pack(fill="x", pady=(0, 20))

        return tarjeta

    def _boton_al_entrar(self, evento):
        boton = evento.widget
        if boton.cget("state") == "disabled":
            return

        if not hasattr(boton, "_labmonitor_background"):
            boton._labmonitor_background = boton.cget("background")

        boton.configure(
            background="#963852",
            activebackground="#a74662",
            relief="raised",
            highlightthickness=2,
            highlightbackground=COLOR_DORADO,
            highlightcolor=COLOR_DORADO
        )

    def _boton_al_salir(self, evento):
        boton = evento.widget
        background = getattr(
            boton,
            "_labmonitor_background",
            COLOR_TARJETA
        )
        boton.configure(
            background=background,
            activebackground=COLOR_PRINCIPAL,
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLOR_TARJETA,
            highlightcolor=COLOR_DORADO
        )

    # ======================================
    # CONFIGURACION INICIAL
    # ======================================

    def pantalla_mensaje(self, titulo, mensaje, reintentar=False):
        self.limpiar()
        tarjeta = self.crear_tarjeta()

        tk.Label(
            tarjeta,
            text=titulo,
            font=("Segoe UI", 19, "bold"),
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO,
            wraplength=320
        ).pack(pady=(30, 20))

        tk.Label(
            tarjeta,
            text=mensaje,
            font=("Segoe UI", 11),
            bg=COLOR_TARJETA,
            fg=COLOR_SECUNDARIO,
            wraplength=320,
            justify="center"
        ).pack(pady=15)

        if reintentar:
            tk.Button(
                tarjeta,
                text="Reintentar",
                command=self.consultar_configuracion_inicial,
                bg=COLOR_PRINCIPAL,
                fg="white"
            ).pack(fill="x", pady=15)

    def consultar_configuracion_inicial(self):
        self.pantalla_mensaje(
            "LabMonitor",
            "Consultando configuracion del equipo..."
        )

        threading.Thread(
            target=self._consultar_configuracion,
            daemon=True
        ).start()

    def _consultar_configuracion(self):
        try:
            datos = solicitar_agente("configuration")

            if (
                not isinstance(datos, dict)
                or not isinstance(datos.get("configured"), bool)
            ):
                raise ValueError(
                    "Respuesta de configuracion invalida."
                )

            self.root.after(
                0,
                lambda d=datos: self._configuracion_recibida(d)
            )

        except (ErrorAgente, ValueError) as error:
            mensaje = str(error)

            self.root.after(
                0,
                lambda m=mensaje: self.pantalla_mensaje(
                    "Conexion no disponible",
                    m,
                    reintentar=True
                )
            )

    def _configuracion_recibida(self, datos):
        self.configuracion = datos

        if datos["configured"]:
            self.mostrar_login()
        else:
            self.mostrar_admin_login("setup")

    def mostrar_admin_login(self, modo="setup"):
        self._mostrar_barra_tareas(False)
        self.modo_admin = modo
        self.limpiar()

        tarjeta = self.crear_tarjeta()

        titulo = (
            "Configuracion inicial"
            if modo == "setup"
            else "Acceso administrativo"
        )

        tk.Label(
            tarjeta,
            text=titulo,
            font=("Segoe UI", 19, "bold"),
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(pady=(10, 15))

        tk.Label(
            tarjeta,
            text="Usuario administrador",
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(anchor="w")

        usuario = ttk.Entry(tarjeta)
        usuario.pack(fill="x", pady=(5, 15), ipady=5)

        tk.Label(
            tarjeta,
            text="Contrasena",
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(anchor="w")

        clave = ttk.Entry(tarjeta, show="*")
        clave.pack(fill="x", pady=(5, 15), ipady=5)

        estado = tk.Label(
            tarjeta,
            text="",
            bg=COLOR_TARJETA,
            fg=COLOR_ERROR,
            wraplength=320
        )
        estado.pack(pady=10)

        boton = tk.Button(
            tarjeta,
            text="Ingresar como administrador",
            bg=COLOR_PRINCIPAL,
            fg="white"
        )
        boton.pack(fill="x", ipady=7)

        def enviar():
            nombre = usuario.get().strip()
            password = clave.get()

            if not nombre or not password:
                estado.config(
                    text="Ingresa usuario y contrasena."
                )
                return

            boton.config(state="disabled")

            threading.Thread(
                target=self._autenticar_admin,
                args=(nombre, password, modo, estado, boton),
                daemon=True
            ).start()

        boton.config(command=enviar)

        tk.Button(
            tarjeta,
            text="Cambiar servidor FastAPI",
            command=self._abrir_cambio_servidor,
            bg=COLOR_TARJETA,
            fg=COLOR_DORADO,
            relief="flat",
            cursor="hand2"
        ).pack(fill="x", pady=(9, 2), ipady=5)

        clave.bind(
            "<Return>",
            lambda _event: enviar()
        )

        if (
            modo != "setup"
            and self.configuracion
            and self.configuracion.get("configured")
        ):
            tk.Button(
                tarjeta,
                text="Volver al inicio de sesión de alumnos",
                command=self._volver_desde_admin,
                bg=COLOR_TARJETA,
                fg=COLOR_DORADO,
                relief="flat",
                cursor="hand2"
            ).pack(fill="x", pady=(14, 4), ipady=5)

        usuario.focus_set()

    def _abrir_cambio_servidor(self):
        ventana = tk.Toplevel(self.root)
        ventana.title("Cambiar servidor FastAPI")
        ventana.configure(bg=COLOR_TARJETA)
        ventana.resizable(False, False)
        ventana.transient(self.root)

        contenido = tk.Frame(
            ventana,
            bg=COLOR_TARJETA,
            padx=22,
            pady=18
        )
        contenido.pack(fill="both", expand=True)

        tk.Label(
            contenido,
            text="Cambiar servidor FastAPI",
            font=("Segoe UI", 16, "bold"),
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(pady=(0, 8))

        tk.Label(
            contenido,
            text=(
                "Esta opción usa la contraseña local definida "
                "durante la instalación y no necesita conexión "
                "al servidor actual."
            ),
            bg=COLOR_TARJETA,
            fg=COLOR_SECUNDARIO,
            wraplength=380,
            justify="left"
        ).pack(anchor="w", pady=(0, 12))

        tk.Label(
            contenido,
            text="Usuario local",
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(anchor="w")
        usuario = ttk.Entry(contenido)
        usuario.insert(0, "Sistemas_Admin")
        usuario.configure(state="readonly")
        usuario.pack(fill="x", pady=(4, 10), ipady=4)

        tk.Label(
            contenido,
            text="Contraseña local",
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(anchor="w")
        password = ttk.Entry(contenido, show="*")
        password.pack(fill="x", pady=(4, 10), ipady=4)

        tk.Label(
            contenido,
            text="Nueva URL de FastAPI",
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(anchor="w")
        url = ttk.Entry(contenido)
        url.insert(0, SERVER_URL)
        url.pack(fill="x", pady=(4, 8), ipady=4)

        estado = tk.Label(
            contenido,
            text="",
            bg=COLOR_TARJETA,
            fg=COLOR_ERROR,
            wraplength=380,
            justify="left"
        )
        estado.pack(fill="x", pady=(4, 8))

        boton_guardar = tk.Button(
            contenido,
            text="Guardar y conectar al nuevo servidor",
            bg=COLOR_PRINCIPAL,
            fg="white"
        )
        boton_guardar.pack(fill="x", ipady=7)

        def guardar():
            nueva_url = url.get().strip().rstrip("/")
            clave_local = password.get()
            if not nueva_url.startswith(("http://", "https://")):
                estado.config(
                    text="La URL debe comenzar con http:// o https://."
                )
                return
            if not clave_local:
                estado.config(
                    text="Escribe la contraseña local de administrador."
                )
                return

            boton_guardar.config(state="disabled")
            estado.config(
                text="Validando credencial y actualizando la configuración...",
                fg=COLOR_SECUNDARIO
            )
            threading.Thread(
                target=self._cambiar_servidor_en_hilo,
                args=(
                    "Sistemas_Admin",
                    clave_local,
                    nueva_url,
                    ventana,
                    estado,
                    boton_guardar
                ),
                daemon=True
            ).start()
            password.delete(0, tk.END)

        def cerrar_dialogo():
            if str(boton_guardar["state"]) != "disabled":
                ventana.destroy()

        boton_guardar.config(command=guardar)
        ventana.protocol("WM_DELETE_WINDOW", cerrar_dialogo)
        password.bind("<Return>", lambda _event: guardar())
        url.bind("<Return>", lambda _event: guardar())
        ventana.grab_set()
        password.focus_set()

    def _cambiar_servidor_en_hilo(
        self,
        usuario,
        password,
        url_servidor,
        ventana,
        estado,
        boton
    ):
        try:
            resultado = solicitar_agente(
                "update-server-url",
                server_url=url_servidor,
                local_admin_username=usuario,
                local_admin_password=password
            )
            if (
                not isinstance(resultado, dict)
                or resultado.get("server_url") != url_servidor
                or resultado.get("configured") is not False
            ):
                raise ValueError(
                    "El agente no confirmó el cambio del servidor."
                )
            configuracion = solicitar_agente("configuration")
            self.root.after(
                0,
                lambda: self._servidor_actualizado(
                    resultado["server_url"],
                    configuracion,
                    ventana
                )
            )
        except (ErrorAgente, ValueError) as error:
            mensaje = str(error)
            self.root.after(
                0,
                lambda m=mensaje: self._error_cambiar_servidor(
                    ventana,
                    estado,
                    boton,
                    m
                )
            )

    def _servidor_actualizado(self, url_servidor, configuracion, ventana):
        global SERVER_URL
        SERVER_URL = url_servidor
        self.configuracion = configuracion
        ventana.destroy()
        self.mostrar_admin_login("setup")

    @staticmethod
    def _error_cambiar_servidor(ventana, estado, boton, mensaje):
        try:
            if not ventana.winfo_exists():
                return
        except tk.TclError:
            return
        estado.config(text=mensaje, fg=COLOR_ERROR)
        boton.config(state="normal")

    def _volver_desde_admin(self):
        self.admin_token = None

        if self.configuracion and self.configuracion.get("configured"):
            self.mostrar_login()
        else:
            self.consultar_configuracion_inicial()

    def _autenticar_admin(
        self,
        nombre,
        password,
        modo,
        estado,
        boton
    ):
        try:
            respuesta = requests.post(
                f"{SERVER_URL}/auth/login",
                json={
                    "username": nombre,
                    "password": password
                },
                timeout=10
            )

            respuesta.raise_for_status()
            datos = respuesta.json()
            token = datos.get("access_token")

            if (
                datos.get("user", {}).get("role") != "admin"
                or not token
            ):
                raise ValueError(
                    "La cuenta no tiene permisos de administrador."
                )

            verificar = requests.get(
                f"{SERVER_URL}/admin/laboratories",
                headers={
                    "Authorization": f"Bearer {token}"
                },
                timeout=10
            )

            verificar.raise_for_status()

            # ======================================
            # CORRECCION:
            # FastAPI devuelve un objeto con:
            # {
            #     "total": 1,
            #     "laboratories": [...]
            # }
            # ======================================

            datos_laboratorios = verificar.json()

            if not isinstance(datos_laboratorios, dict):
                raise ValueError(
                    "Respuesta de laboratorios invalida."
                )

            laboratorios = datos_laboratorios.get("laboratories")

            if not isinstance(laboratorios, list):
                raise ValueError(
                    "Respuesta de laboratorios invalida."
                )

            self.root.after(
                0,
                lambda: self._admin_autenticado(
                    token,
                    modo,
                    laboratorios
                )
            )

        except (requests.RequestException, ValueError) as error:
            mensaje = str(error)

            self.root.after(
                0,
                lambda m=mensaje: (
                    estado.config(text=m),
                    boton.config(state="normal")
                )
            )

    def _admin_autenticado(self, token, modo, laboratorios):
        self.admin_token = token

        if modo in ("exit", "controls"):
            self.mostrar_controles_admin(laboratorios)
            return

        if not self.configuracion.get("computer_id"):
            self.pantalla_mensaje(
                "Registrando computadora",
                "El administrador autorizo el registro seguro del equipo..."
            )
            threading.Thread(
                target=self._registrar_computadora,
                args=(token, laboratorios),
                daemon=True
            ).start()
            return

        self.mostrar_asistente(laboratorios)

    def _registrar_computadora(self, token, laboratorios):
        try:
            datos = solicitar_agente(
                "register",
                admin_token=token,
                server_url=SERVER_URL
            )
            if (
                not isinstance(datos, dict)
                or not isinstance(datos.get("computer_id"), int)
            ):
                raise ValueError(
                    "El agente devolvio datos de registro incompletos."
                )
            self.root.after(
                0,
                lambda: self._computadora_registrada(
                    datos,
                    laboratorios
                )
            )
        except (ErrorAgente, ValueError) as error:
            mensaje = str(error)
            self.root.after(
                0,
                lambda m=mensaje: self.pantalla_mensaje(
                    "No se pudo registrar",
                    m,
                    reintentar=True
                )
            )

    def _computadora_registrada(self, datos, laboratorios):
        self.configuracion.update({
            "computer_id": datos["computer_id"],
            "hostname": datos.get("hostname") or self.configuracion["hostname"],
            "display_name": datos.get("hostname") or self.configuracion["hostname"],
            "configured": False,
        })
        self.mostrar_asistente(laboratorios)

    def mostrar_controles_admin(self, laboratorios):
        self.limpiar()
        self.laboratorios_admin = laboratorios
        tarjeta = self.crear_tarjeta()

        tk.Label(
            tarjeta,
            text="Administracion",
            font=("Segoe UI", 19, "bold"),
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(pady=(8, 18))

        tk.Label(
            tarjeta,
            text="Elige una accion para este equipo.",
            bg=COLOR_TARJETA,
            fg=COLOR_SECUNDARIO
        ).pack(pady=(0, 12))

        self.estado_actualizacion_admin = tk.Label(
            tarjeta,
            text="",
            bg=COLOR_TARJETA,
            fg=COLOR_SECUNDARIO
        )
        self.estado_actualizacion_admin.pack(pady=(0, 6))

        self.boton_actualizar_admin = tk.Button(
            tarjeta,
            text="Actualizar configuracion",
            command=self._actualizar_datos_admin,
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        )
        self.boton_actualizar_admin.pack(
            fill="x",
            ipady=7,
            pady=5
        )

        tk.Button(
            tarjeta,
            text="Configurar equipo y laboratorio",
            command=lambda: self.mostrar_asistente(
                self.laboratorios_admin
            ),
            bg=COLOR_PRINCIPAL,
            fg="white"
        ).pack(fill="x", ipady=7, pady=5)

        tk.Button(
            tarjeta,
            text="Activar bloqueo de Windows para esta cuenta",
            command=lambda: self._cambiar_acceso_asignado("Apply"),
            bg=COLOR_PRINCIPAL,
            fg="white"
        ).pack(fill="x", ipady=7, pady=5)

        tk.Button(
            tarjeta,
            text="Desactivar bloqueo de Windows",
            command=lambda: self._cambiar_acceso_asignado("Remove"),
            bg=COLOR_TARJETA,
            fg=COLOR_ADVERTENCIA
        ).pack(fill="x", ipady=7, pady=5)

        tk.Button(
            tarjeta,
            text="Cerrar solo LabMonitor",
            command=self._cerrar_solo_interfaz,
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(fill="x", ipady=7, pady=5)

        detener = tk.Button(
            tarjeta,
            text="Detener agente hasta el proximo reinicio",
            bg=COLOR_TARJETA,
            fg=COLOR_ADVERTENCIA
        )
        detener.config(
            command=lambda: self._confirmar_detencion_servicio(detener)
        )
        detener.pack(fill="x", ipady=7, pady=5)

        tk.Button(
            tarjeta,
            text="Cancelar",
            command=self._volver_desde_admin,
            bg=COLOR_TARJETA,
            fg=COLOR_SECUNDARIO
        ).pack(pady=12)

    def _actualizar_datos_admin(self):
        if not self.admin_token:
            self.estado_actualizacion_admin.config(
                text="Inicia sesion como administrador para actualizar.",
                fg=COLOR_ERROR
            )
            return

        self.boton_actualizar_admin.config(state="disabled")
        generacion = self.admin_refresh_generation
        self.estado_actualizacion_admin.config(
            text="Actualizando laboratorios y equipo...",
            fg=COLOR_SECUNDARIO
        )
        threading.Thread(
            target=self._actualizar_datos_admin_en_hilo,
            args=(self.admin_token, generacion),
            daemon=True
        ).start()

    def _actualizar_datos_admin_en_hilo(self, token, generacion):
        try:
            respuesta = requests.get(
                f"{SERVER_URL}/admin/laboratories",
                headers={
                    "Authorization": f"Bearer {token}"
                },
                timeout=10
            )
            respuesta.raise_for_status()
            datos_laboratorios = respuesta.json()
            laboratorios = (
                datos_laboratorios.get("laboratories")
                if isinstance(datos_laboratorios, dict)
                else None
            )
            if not isinstance(laboratorios, list):
                raise ValueError(
                    "Respuesta de laboratorios invalida."
                )

            configuracion = solicitar_agente("configuration")
            if (
                not isinstance(configuracion, dict)
                or not isinstance(
                    configuracion.get("configured"),
                    bool
                )
            ):
                raise ValueError(
                    "Respuesta de configuracion invalida."
                )

            if generacion != self.admin_refresh_generation:
                return
            self.root.after(
                0,
                lambda: self._datos_admin_actualizados(
                    laboratorios,
                    configuracion,
                    generacion
                )
            )
        except (
            requests.RequestException,
            ValueError,
            ErrorAgente
        ) as error:
            if generacion != self.admin_refresh_generation:
                return
            mensaje = str(error)
            self.root.after(
                0,
                lambda m=mensaje: self._error_actualizar_datos_admin(
                    m,
                    generacion
                )
            )

    def _datos_admin_actualizados(
        self,
        laboratorios,
        configuracion,
        generacion
    ):
        if generacion != self.admin_refresh_generation:
            return
        self.laboratorios_admin = laboratorios
        self.configuracion = configuracion
        self.boton_actualizar_admin.config(state="normal")
        self.estado_actualizacion_admin.config(
            text="Configuracion actualizada.",
            fg=COLOR_PRINCIPAL
        )

    def _error_actualizar_datos_admin(self, mensaje, generacion):
        if generacion != self.admin_refresh_generation:
            return
        self.boton_actualizar_admin.config(state="normal")
        self.estado_actualizacion_admin.config(
            text=f"No se pudo actualizar: {mensaje}",
            fg=COLOR_ERROR
        )

    def _cambiar_acceso_asignado(self, operation):
        if self.cambio_acceso_asignado_en_curso:
            return

        activar = operation == "Apply"
        titulo = (
            "Activar bloqueo de Windows"
            if activar
            else "Desactivar bloqueo de Windows"
        )
        mensaje = (
            "LabMonitor quedará como la única aplicación permitida para "
            "la cuenta de Windows en la que está abierta. La política se "
            "aplicará al próximo inicio de sesión de Windows. Conserva una "
            "cuenta administradora de Windows distinta para recuperación. "
            "¿Continuar?"
            if activar
            else "Se quitará la restricción de Acceso asignado de LabMonitor "
            "en este equipo. ¿Continuar?"
        )
        if not messagebox.askyesno(titulo, mensaje):
            return

        windows_account = os.environ.get("USERNAME", "")
        admin_token = self.admin_token
        self.cambio_acceso_asignado_en_curso = True
        threading.Thread(
            target=self._cambiar_acceso_asignado_en_hilo,
            args=(operation, windows_account, admin_token),
            daemon=True
        ).start()

    def _cambiar_acceso_asignado_en_hilo(
        self,
        operation,
        windows_account,
        admin_token
    ):
        try:
            resultado = solicitar_agente(
                "assigned-access",
                admin_token=admin_token,
                operation=operation,
                windows_account=windows_account
            )
            mensaje = resultado.get("message")
            if not isinstance(mensaje, str) or not mensaje:
                raise ValueError(
                    "El agente no confirmó el cambio del modo quiosco."
                )
            self.root.after(
                0,
                lambda m=mensaje: self._mostrar_resultado_acceso_asignado(
                    m
                )
            )
        except (ErrorAgente, ValueError) as error:
            mensaje = str(error)
            self.root.after(
                0,
                lambda m=mensaje: self._mostrar_resultado_acceso_asignado(
                    m,
                    error=True
                )
            )

    def _mostrar_resultado_acceso_asignado(self, mensaje, error=False):
        self.cambio_acceso_asignado_en_curso = False
        if error:
            messagebox.showerror(
                "No se pudo cambiar el modo quiosco",
                mensaje
            )
        else:
            messagebox.showinfo("LabMonitor", mensaje)

    def _cerrar_solo_interfaz(self):
        if messagebox.askyesno(
            "LabMonitor",
            "?Cerrar solo la ventana de LabMonitor? El agente seguira activo."
        ):
            self.admin_refresh_generation += 1
            self._restaurar_barra_tareas_al_salir()
            self.root.destroy()
        else:
            self._volver_desde_admin()

    def _confirmar_detencion_servicio(self, boton):
        if not messagebox.askyesno(
            "Detener agente",
            "Se solicitara elevacion de Windows para detener LabMonitorAgent. "
            "El servicio volvera a iniciarse automaticamente al reiniciar. "
            "?Continuar?"
        ):
            return

        boton.config(state="disabled")
        threading.Thread(
            target=self._detener_servicio_en_hilo,
            args=(boton,),
            daemon=True
        ).start()

    def _detener_servicio_en_hilo(self, boton):
        try:
            detener_servicio_elevado()
            self.root.after(0, self._servicio_detenido)
        except Exception as error:
            mensaje = str(error)
            self.root.after(
                0,
                lambda m=mensaje: self._error_detencion_servicio(boton, m)
            )

    def _servicio_detenido(self):
        messagebox.showinfo(
            "LabMonitor",
            "El agente se detuvo. Se iniciara nuevamente al reiniciar Windows."
        )
        self.admin_refresh_generation += 1
        self._restaurar_barra_tareas_al_salir()
        self.root.destroy()

    def _error_detencion_servicio(self, boton, mensaje):
        messagebox.showerror(
            "No se pudo detener el agente",
            mensaje
        )
        boton.config(state="normal")

    def mostrar_asistente(self, laboratorios):
        self.limpiar()
        tarjeta = self.crear_tarjeta()

        tk.Label(
            tarjeta,
            text="Configurar computadora",
            font=("Segoe UI", 17, "bold"),
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(pady=(0, 12))

        tk.Label(
            tarjeta,
            text="Nombre visible de la PC",
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(anchor="w")

        nombre = ttk.Entry(tarjeta)
        nombre.pack(fill="x", pady=(4, 12), ipady=4)

        nombre.insert(
            0,
            self.configuracion.get("display_name") or ""
        )

        tk.Label(
            tarjeta,
            text="Laboratorio existente",
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(anchor="w")

        nombres = ["No asignar laboratorio"] + [
            lab["name"]
            for lab in laboratorios
        ]

        selector = ttk.Combobox(
            tarjeta,
            values=nombres,
            state="readonly"
        )
        selector.pack(fill="x", pady=(4, 10))

        laboratorio_actual = self.configuracion.get("laboratory_id")
        indice_actual = next(
            (
                indice + 1
                for indice, laboratorio in enumerate(laboratorios)
                if laboratorio["id"] == laboratorio_actual
            ),
            0
        )
        selector.current(indice_actual)

        tk.Label(
            tarjeta,
            text="O crear laboratorio nuevo",
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(anchor="w")

        nuevo = ttk.Entry(tarjeta)
        nuevo.pack(fill="x", pady=(4, 12), ipady=4)

        estado = tk.Label(
            tarjeta,
            text="",
            bg=COLOR_TARJETA,
            fg=COLOR_ERROR,
            wraplength=320
        )
        estado.pack(pady=6)

        guardar = tk.Button(
            tarjeta,
            text="Guardar configuracion",
            bg=COLOR_PRINCIPAL,
            fg="white"
        )
        guardar.pack(fill="x", ipady=8)

        def enviar():
            nombre_pc = nombre.get().strip()
            nombre_lab = nuevo.get().strip()

            lab = next(
                (
                    x for x in laboratorios
                    if x["name"] == selector.get()
                ),
                None
            )
            sin_asignar = selector.current() == 0

            if not nombre_pc or len(nombre_pc) > 100:
                estado.config(
                    text="Nombre de PC requerido (maximo 100 caracteres)."
                )
                return

            if nombre_lab and len(nombre_lab) > 100:
                estado.config(
                    text="Nombre de laboratorio demasiado largo."
                )
                return

            if not nombre_lab and lab is None and not sin_asignar:
                estado.config(
                    text="Selecciona un laboratorio, crea uno nuevo o elige no asignarlo."
                )
                return

            if not messagebox.askyesno(
                "Activar acceso restringido",
                "Al guardar, LabMonitor activará Acceso asignado para la "
                "cuenta de Windows actual. En el próximo inicio de sesión "
                "esa cuenta solo podrá usar LabMonitor. Se requiere una "
                "cuenta administradora de Windows distinta para recuperar "
                "el equipo. ¿Continuar?"
            ):
                return

            guardar.config(state="disabled")

            threading.Thread(
                target=self._guardar_configuracion,
                args=(
                    nombre_pc,
                    nombre_lab,
                    None if sin_asignar and not nombre_lab else lab,
                    estado,
                    guardar,
                    self.admin_token
                ),
                daemon=True
            ).start()

        guardar.config(command=enviar)

        tk.Button(
            tarjeta,
            text="Cancelar",
            command=self._volver_desde_admin,
            bg=COLOR_TARJETA,
            fg=COLOR_SECUNDARIO
        ).pack(pady=10)

    def _guardar_configuracion(
        self,
        nombre_pc,
        nombre_lab,
        lab,
        estado,
        boton,
        admin_token
    ):
        headers = {
            "Authorization": f"Bearer {self.admin_token}"
        }

        try:
            configuracion_servidor_guardada = False
            if nombre_lab:
                crear = requests.post(
                    f"{SERVER_URL}/admin/laboratories",
                    json={"name": nombre_lab},
                    headers=headers,
                    timeout=10
                )

                if crear.status_code == 409:
                    lista = requests.get(
                        f"{SERVER_URL}/admin/laboratories",
                        headers=headers,
                        timeout=10
                    )

                    lista.raise_for_status()

                    # El endpoint devuelve un objeto,
                    # no una lista directamente.

                    datos_lista = lista.json()

                    if not isinstance(datos_lista, dict):
                        raise ValueError(
                            "Respuesta de laboratorios invalida."
                        )

                    laboratorios_existentes = datos_lista.get(
                        "laboratories"
                    )

                    if not isinstance(laboratorios_existentes, list):
                        raise ValueError(
                            "Respuesta de laboratorios invalida."
                        )

                    lab = next(
                        (
                            x for x in laboratorios_existentes
                            if x["name"].casefold() == nombre_lab.casefold()
                        ),
                        None
                    )

                    if lab is None:
                        crear.raise_for_status()

                else:
                    crear.raise_for_status()
                    respuesta_creacion = crear.json()
                    lab = respuesta_creacion.get("laboratory")
                    if not isinstance(lab, dict) or "id" not in lab:
                        raise ValueError(
                            "El servidor devolvio un laboratorio invalido."
                        )

            equipo_id = self.configuracion["computer_id"]

            respuesta = requests.put(
                f"{SERVER_URL}/admin/computers/{equipo_id}/configuration",
                json={
                    "display_name": nombre_pc,
                    "laboratory_id": lab["id"] if lab else None
                },
                headers=headers,
                timeout=10
            )

            respuesta.raise_for_status()
            configuracion_servidor_guardada = True

            try:
                resultado_quiosco = solicitar_agente(
                    "assigned-access",
                    admin_token=admin_token,
                    operation="Apply",
                    windows_account=os.environ.get("USERNAME", "")
                )
                if (
                    not isinstance(resultado_quiosco, dict)
                    or not isinstance(resultado_quiosco.get("message"), str)
                ):
                    raise ValueError(
                        "Windows no confirmó la activación del modo quiosco."
                    )
                mensaje_quiosco = resultado_quiosco["message"]
            except (ErrorAgente, ValueError) as error:
                mensaje_quiosco = (
                    "La cuenta o edición de Windows no admite el modo "
                    "quiosco: " + str(error) +
                    "\n\nLabMonitor quedó configurado y funcionará a "
                    "pantalla completa, pero Windows no estará bloqueado."
                )

            self.root.after(
                0,
                lambda: self._configuracion_guardada(
                    mensaje_quiosco
                )
            )

        except (
            requests.RequestException,
            ValueError,
            KeyError,
            TypeError
        ) as error:
            mensaje = str(error)
            if configuracion_servidor_guardada:
                mensaje = (
                    "La configuración del equipo ya se guardó en el "
                    "servidor, pero no se pudo activar el bloqueo de "
                    f"Windows: {mensaje}"
                )

            self.root.after(
                0,
                lambda m=mensaje: (
                    estado.config(text=m),
                    boton.config(state="normal")
                )
            )

    def _configuracion_guardada(self, mensaje_quiosco):
        self.admin_token = None

        messagebox.showinfo(
            "LabMonitor",
            "Configuración guardada. " + mensaje_quiosco
        )

        self.consultar_configuracion_inicial()

    # ======================================
    # PANTALLA LOGIN
    # ======================================

    def mostrar_login(self):
        self._mostrar_barra_tareas(False)
        self._programar_ocultar_barra_tareas()
        self.limpiar()
        tarjeta = self.crear_tarjeta()

        tk.Label(
            tarjeta,
            text="LabMonitor",
            font=("Segoe UI", 25, "bold"),
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(pady=(10, 5))

        tk.Label(
            tarjeta,
            text="Acceso a laboratorio",
            font=("Segoe UI", 12),
            bg=COLOR_TARJETA,
            fg=COLOR_SECUNDARIO
        ).pack(pady=(0, 25))

        tk.Label(
            tarjeta,
            text="Matricula",
            font=("Segoe UI", 11),
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(anchor="w")

        self.entrada_matricula = ttk.Entry(
            tarjeta,
            font=("Segoe UI", 12)
        )

        self.entrada_matricula.pack(
            fill="x",
            pady=(5, 20),
            ipady=5
        )

        tk.Label(
            tarjeta,
            text="Contrasena",
            font=("Segoe UI", 11),
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(anchor="w")

        self.entrada_password = ttk.Entry(
            tarjeta,
            font=("Segoe UI", 12),
            show="*"
        )

        self.entrada_password.pack(
            fill="x",
            pady=(5, 25),
            ipady=5
        )

        self.boton_login = tk.Button(
            tarjeta,
            text="Iniciar sesion",
            font=("Segoe UI", 12, "bold"),
            bg=COLOR_PRINCIPAL,
            fg="white",
            relief="flat",
            cursor="hand2",
            command=self.iniciar_sesion
        )

        self.boton_login.pack(
            fill="x",
            ipady=10
        )

        self.estado = tk.Label(
            tarjeta,
            text="",
            font=("Segoe UI", 10),
            bg=COLOR_TARJETA,
            fg=COLOR_SECUNDARIO,
            wraplength=320,
            justify="center"
        )

        self.estado.pack(pady=15)

        self.verificacion_frame = tk.Frame(
            tarjeta,
            bg=COLOR_TARJETA
        )
        tk.Label(
            self.verificacion_frame,
            text="Código de seguridad enviado a tu correo",
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(anchor="w")
        self.entrada_codigo = ttk.Entry(
            self.verificacion_frame,
            font=("Segoe UI", 12),
            justify="center"
        )
        self.entrada_codigo.pack(
            fill="x",
            pady=(5, 8),
            ipady=5
        )
        tk.Button(
            self.verificacion_frame,
            text="Verificar correo",
            command=self.verificar_correo_estudiante,
            bg=COLOR_PRINCIPAL,
            fg="white",
            relief="flat",
            cursor="hand2"
        ).pack(fill="x", ipady=6)
        tk.Button(
            self.verificacion_frame,
            text="Reenviar código",
            command=self.reenviar_codigo_verificacion,
            bg=COLOR_TARJETA,
            fg=COLOR_DORADO,
            relief="flat",
            cursor="hand2"
        ).pack(fill="x", pady=(4, 0))
        self.verificacion_frame.pack_forget()

        tk.Button(
            tarjeta,
            text="Olvidé mi contraseña",
            command=self.solicitar_recuperacion_password,
            bg=COLOR_TARJETA,
            fg=COLOR_DORADO,
            relief="flat",
            cursor="hand2"
        ).pack(fill="x", pady=(0, 4))

        tk.Button(
            tarjeta,
            text="Iniciar sesión como administrador",
            command=lambda: self.mostrar_admin_login("controls"),
            bg=COLOR_TARJETA,
            fg=COLOR_DORADO,
            relief="flat"
        ).pack(fill="x", pady=(0, 5), ipady=5)

        self.entrada_matricula.focus_set()

        self.entrada_password.bind(
            "<Return>",
            lambda evento: self.iniciar_sesion()
        )

    # ======================================
    # INICIAR SESION
    # ======================================

    def iniciar_sesion(self):
        if self.operacion_en_curso:
            return

        matricula = self.entrada_matricula.get().strip()
        password = self.entrada_password.get()

        if not matricula or not password:
            self.estado.config(
                text="Introduce tu matricula y contrasena.",
                fg=COLOR_ERROR
            )
            return

        self.operacion_en_curso = True

        self.boton_login.config(
            state="disabled",
            text="Validando..."
        )

        self.estado.config(
            text="Autenticando y registrando sesion...",
            fg=COLOR_SECUNDARIO
        )

        threading.Thread(
            target=self.procesar_login,
            args=(matricula, password),
            daemon=True
        ).start()

    def procesar_login(self, matricula, password):
        try:
            respuesta = requests.post(
                f"{SERVER_URL}/auth/login",
                json={
                    "username": matricula,
                    "password": password
                },
                timeout=10
            )

            if respuesta.status_code == 401:
                raise ValueError(
                    "Matricula o contrasena incorrecta."
                )

            if respuesta.status_code == 403:
                self.root.after(
                    0,
                    self.mostrar_formulario_verificacion
                )
                raise ValueError(
                    "Verifica tu correo con el código de seguridad "
                    "que recibiste antes de iniciar sesión."
                )

            respuesta.raise_for_status()
            datos = respuesta.json()

            usuario = datos.get("user", {})
            token = datos.get("access_token")

            if usuario.get("role") != "student":
                raise ValueError(
                    "Esta aplicacion es exclusiva para estudiantes."
                )

            if not token:
                raise ValueError(
                    "El servidor no devolvio un token valido."
                )

            sesion = solicitar_agente(
                "start",
                token
            )

            session_id = sesion.get("session_id")

            if not session_id:
                raise ValueError(
                    "El agente no devolvio el ID de sesion."
                )

            self.root.after(
                0,
                lambda: self.login_exitoso(
                    usuario,
                    token,
                    session_id
                )
            )

        except requests.RequestException:
            self.root.after(
                0,
                lambda: self.mostrar_error(
                    "No fue posible conectar con FastAPI."
                )
            )

        except (
            ErrorAgente,
            ValueError,
            KeyError,
            TypeError
        ) as error:
            mensaje = str(error)

            self.root.after(
                0,
                lambda mensaje=mensaje: self.mostrar_error(mensaje)
            )

    def mostrar_formulario_verificacion(self):
        self.verificacion_frame.pack(
            fill="x",
            pady=(0, 10),
            before=self.boton_login
        )
        self.entrada_codigo.focus_set()

    def verificar_correo_estudiante(self):
        if self.operacion_en_curso:
            return

        matricula = self.entrada_matricula.get().strip()
        codigo = self.entrada_codigo.get().strip()
        if not matricula or len(codigo) != 6 or not codigo.isdigit():
            self.estado.config(
                text="Escribe tu matrícula y el código de 6 dígitos.",
                fg=COLOR_ERROR
            )
            return

        self.operacion_en_curso = True
        self.estado.config(
            text="Verificando correo...",
            fg=COLOR_SECUNDARIO
        )
        threading.Thread(
            target=self._verificar_correo_en_hilo,
            args=(matricula, codigo),
            daemon=True
        ).start()

    def _verificar_correo_en_hilo(self, matricula, codigo):
        try:
            respuesta = requests.post(
                f"{SERVER_URL}/auth/verify-email",
                json={"username": matricula, "code": codigo},
                timeout=10
            )
            if not respuesta.ok:
                detalle = respuesta.json().get(
                    "detail",
                    "No fue posible verificar el correo."
                )
                raise ValueError(detalle)

            self.root.after(0, self._correo_verificado)
        except requests.RequestException:
            self.root.after(
                0,
                lambda: self.mostrar_error(
                    "No fue posible conectar con el servidor."
                )
            )
        except (ValueError, TypeError) as error:
            mensaje = str(error)
            self.root.after(
                0,
                lambda mensaje=mensaje: self.mostrar_error(mensaje)
            )

    def _correo_verificado(self):
        self.operacion_en_curso = False
        self.verificacion_frame.pack_forget()
        self.entrada_codigo.delete(0, tk.END)
        self.estado.config(
            text="Correo verificado. Ya puedes iniciar sesión.",
            fg=COLOR_EXITO
        )
        self.boton_login.config(
            state="normal",
            text="Iniciar sesion"
        )

    def reenviar_codigo_verificacion(self):
        if self.operacion_en_curso:
            return
        matricula = self.entrada_matricula.get().strip()
        if not matricula:
            self.estado.config(
                text="Escribe tu matrícula para reenviar el código.",
                fg=COLOR_ERROR
            )
            return

        self.operacion_en_curso = True
        self.estado.config(
            text="Solicitando un nuevo código...",
            fg=COLOR_SECUNDARIO
        )
        threading.Thread(
            target=self._reenviar_codigo_en_hilo,
            args=(matricula,),
            daemon=True
        ).start()

    def _reenviar_codigo_en_hilo(self, matricula):
        try:
            respuesta = requests.post(
                f"{SERVER_URL}/auth/resend-verification",
                json={"username": matricula},
                timeout=10
            )
            respuesta.raise_for_status()
            mensaje = respuesta.json().get(
                "message",
                "Solicitud procesada."
            )
            self.root.after(
                0,
                lambda: self._mostrar_estado_solicitud(mensaje)
            )
        except requests.RequestException:
            self.root.after(
                0,
                lambda: self.mostrar_error(
                    "No fue posible conectar con el servidor."
                )
            )

    def _mostrar_estado_solicitud(self, mensaje):
        self.operacion_en_curso = False
        self.estado.config(text=mensaje, fg=COLOR_SECUNDARIO)
        self.boton_login.config(
            state="normal",
            text="Iniciar sesion"
        )

    def solicitar_recuperacion_password(self):
        correo = simpledialog.askstring(
            "Recuperar contraseña",
            "Escribe el correo electrónico registrado en LabMonitor:",
            parent=self.root
        )
        if not correo:
            return
        if (
            "@" not in correo
            or any(caracter.isspace() for caracter in correo)
        ):
            messagebox.showerror(
                "Correo inválido",
                "Escribe un correo electrónico válido.",
                parent=self.root
            )
            return

        threading.Thread(
            target=self._solicitar_recuperacion_en_hilo,
            args=(correo.strip(),),
            daemon=True
        ).start()

    def _solicitar_recuperacion_en_hilo(self, correo):
        try:
            respuesta = requests.post(
                f"{SERVER_URL}/auth/forgot-password",
                json={"identifier": correo},
                timeout=10
            )
            respuesta.raise_for_status()
            mensaje = respuesta.json().get(
                "message",
                "Si la cuenta existe, recibirás instrucciones por correo."
            )
            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "Recuperación de contraseña",
                    mensaje,
                    parent=self.root
                )
            )
        except requests.RequestException:
            self.root.after(
                0,
                lambda: messagebox.showerror(
                    "LabMonitor",
                    "No fue posible conectar con el servidor.",
                    parent=self.root
                )
            )

    def mostrar_error(self, mensaje):
        self.operacion_en_curso = False

        self.estado.config(
            text=mensaje,
            fg=COLOR_ERROR
        )

        self.boton_login.config(
            state="normal",
            text="Iniciar sesion"
            
        )
        messagebox.showerror(
        "LabMonitor - Error de inicio de sesion",
        mensaje
        )

    # ======================================
    # SESION INICIADA
    # ======================================

    def login_exitoso(self, usuario, token, session_id):
        self.operacion_en_curso = False

        self.usuario = usuario
        self.token = token
        self.session_id = session_id
        self._restaurar_barra_tareas_al_salir()
        self.root.attributes("-fullscreen", False)
        self.root.resizable(True, True)
        self.root.state("zoomed")

        self.cierre_pendiente = False
        self.verificacion_en_curso = False
        self.actividad_en_curso = False

        try:
            self.ultimo_input_tick = obtener_ultimo_input_tick()
        except OSError:
            self.ultimo_input_tick = None

        self.mostrar_sesion()
        self.programar_revision_sesion()
        self.programar_monitoreo_actividad()

    def mostrar_sesion(self):
        self.limpiar()
        tarjeta = self.crear_tarjeta()

        tk.Label(
            tarjeta,
            text="✓",
            font=("Segoe UI", 40),
            bg=COLOR_TARJETA,
            fg=COLOR_EXITO
        ).pack(pady=(10, 5))

        tk.Label(
            tarjeta,
            text="Sesion iniciada",
            font=("Segoe UI", 20, "bold"),
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO
        ).pack(pady=10)

        tk.Label(
            tarjeta,
            text=self.usuario.get("full_name", "Estudiante"),
            font=("Segoe UI", 14),
            bg=COLOR_TARJETA,
            fg=COLOR_TEXTO,
            wraplength=320
        ).pack(pady=10)

        tk.Label(
            tarjeta,
            text=(
                "Matricula: "
                f"{self.usuario.get('username', '')}"
            ),
            font=("Segoe UI", 11),
            bg=COLOR_TARJETA,
            fg=COLOR_SECUNDARIO
        ).pack(pady=5)

        tk.Label(
            tarjeta,
            text=f"ID de sesion: {self.session_id}",
            font=("Segoe UI", 10),
            bg=COLOR_TARJETA,
            fg=COLOR_SECUNDARIO
        ).pack(pady=5)

        tk.Label(
            tarjeta,
            text="Sesion registrada en LabMonitor.",
            font=("Segoe UI", 10),
            bg=COLOR_TARJETA,
            fg=COLOR_EXITO
        ).pack(pady=15)

        self.boton_logout = tk.Button(
            tarjeta,
            text="Cerrar sesion",
            font=("Segoe UI", 12, "bold"),
            bg="#dc2626",
            fg="white",
            relief="flat",
            cursor="hand2",
            command=self.cerrar_sesion
        )

        self.boton_logout.pack(
            fill="x",
            ipady=10,
            pady=10
        )

        self.estado_sesion = tk.Label(
            tarjeta,
            text="",
            font=("Segoe UI", 10),
            bg=COLOR_TARJETA,
            fg=COLOR_SECUNDARIO,
            wraplength=320,
            justify="center"
        )

        self.estado_sesion.pack(pady=10)

    # ======================================
    # REVISION PERIODICA DE SESION
    # ======================================

    def cancelar_revision_sesion(self):
        if self.revision_sesion_programada is not None:
            self.root.after_cancel(
                self.revision_sesion_programada
            )
            self.revision_sesion_programada = None

    def programar_revision_sesion(self):
        if self.session_id is None or self.cierre_pendiente:
            return

        if self.revision_sesion_programada is not None:
            return

        self.revision_sesion_programada = self.root.after(
            SESSION_CHECK_INTERVAL,
            self.verificar_sesion_servidor
        )

    def verificar_sesion_servidor(self):
        self.revision_sesion_programada = None

        if self.session_id is None or self.cierre_pendiente:
            return

        if self.revision_sesion_en_curso or self.operacion_en_curso:
            self.programar_revision_sesion()
            return

        self.revision_sesion_en_curso = True

        session_id = self.session_id
        token = self.token

        threading.Thread(
            target=self.procesar_revision_sesion,
            args=(session_id, token),
            daemon=True
        ).start()

    def procesar_revision_sesion(self, session_id, token):
        try:
            respuesta = solicitar_agente(
                "status",
                token,
                session_id=session_id
            )

            estado = respuesta.get("status", "unknown")

        except Exception:
            estado = "unknown"

        self.root.after(
            0,
            lambda: self.actualizar_revision_sesion(
                session_id,
                estado
            )
        )

    def actualizar_revision_sesion(self, session_id, estado):
        self.revision_sesion_en_curso = False

        if self.session_id != session_id:
            return

        if self.cierre_pendiente:
            return

        if estado == "not_active":
            self.cancelar_revision_sesion()
            self.logout_exitoso()

            messagebox.showinfo(
                "LabMonitor",
                "Tu sesion termino en el servidor. "
                "Puedes volver a iniciar sesion."
            )
            return

        if estado == "different_session":
            self.estado_sesion.config(
                text=(
                    "Se detecto una sesion local diferente. "
                    "Solicita una revision del agente."
                ),
                fg=COLOR_ADVERTENCIA
            )

        elif estado == "unknown":
            self.estado_sesion.config(
                text=(
                    "No se pudo verificar la sesion con el servidor. "
                    "Se intentara nuevamente."
                ),
                fg=COLOR_ADVERTENCIA
            )

        elif estado == "active":
            self.estado_sesion.config(
                text="",
                fg=COLOR_SECUNDARIO
            )

        self.programar_revision_sesion()

    # ======================================
    # ACTIVIDAD DE LA SESION INTERACTIVA
    # ======================================

    def cancelar_monitoreo_actividad(self):
        if self.actividad_programada is not None:
            self.root.after_cancel(self.actividad_programada)
            self.actividad_programada = None

        self.actividad_en_curso = False

    def programar_monitoreo_actividad(self):
        if (
            self.session_id is None
            or self.cierre_pendiente
            or self.actividad_programada is not None
        ):
            return

        self.actividad_programada = self.root.after(
            ACTIVITY_CHECK_INTERVAL,
            self.verificar_actividad_interactiva
        )

    def verificar_actividad_interactiva(self):
        self.actividad_programada = None

        if self.session_id is None or self.cierre_pendiente:
            return

        try:
            tick_actual = obtener_ultimo_input_tick()
        except OSError as error:
            self.estado_sesion.config(
                text=f"No se pudo leer la actividad del usuario: {error}",
                fg=COLOR_ADVERTENCIA
            )
            self.programar_monitoreo_actividad()
            return

        if self.ultimo_input_tick is None:
            self.ultimo_input_tick = tick_actual
            self.programar_monitoreo_actividad()
            return

        if tick_actual == self.ultimo_input_tick:
            self.programar_monitoreo_actividad()
            return

        if self.actividad_en_curso:
            self.programar_monitoreo_actividad()
            return

        self.ultimo_input_tick = tick_actual
        self.actividad_en_curso = True
        session_id = self.session_id
        token = self.token

        threading.Thread(
            target=self.procesar_actividad_interactiva,
            args=(session_id, token),
            daemon=True
        ).start()

    def procesar_actividad_interactiva(self, session_id, token):
        error = None
        token_renovado = None

        try:
            resultado = solicitar_agente(
                "activity",
                token,
                session_id=session_id
            )

            token_renovado = resultado.get("access_token")
        except ErrorAgente as exception:
            error = str(exception)

        self.root.after(
            0,
            lambda: self.finalizar_reporte_actividad(
                session_id,
                error,
                token_renovado
            )
        )

    def finalizar_reporte_actividad(
        self,
        session_id,
        error,
        token_renovado
    ):
        self.actividad_en_curso = False

        if self.session_id != session_id or self.cierre_pendiente:
            return

        if error:
            self.estado_sesion.config(
                text=(
                    "No se pudo sincronizar la actividad. "
                    "Se verificará el estado de la sesión."
                ),
                fg=COLOR_ADVERTENCIA
            )
        else:
            if token_renovado:
                self.token = token_renovado

            self.estado_sesion.config(
                text="",
                fg=COLOR_SECUNDARIO
            )

        self.programar_monitoreo_actividad()

    # ======================================
    # CERRAR SESION
    # ======================================

    def cerrar_sesion(self):
        if self.operacion_en_curso:
            return

        if self.cierre_pendiente:
            return

        if not self.token or not self.session_id:
            return

        self.operacion_en_curso = True
        self.cancelar_revision_sesion()
        self.cancelar_monitoreo_actividad()

        self.boton_logout.config(
            state="disabled",
            text="Cerrando sesion..."
        )

        self.estado_sesion.config(
            text="Registrando salida...",
            fg=COLOR_SECUNDARIO
        )

        threading.Thread(
            target=self.procesar_logout,
            args=(self.token, self.session_id),
            daemon=True
        ).start()

    def procesar_logout(self, token, session_id):
        try:
            resultado = solicitar_agente(
                "end",
                token
            )

            if resultado.get("status") == "pending_close":
                self.root.after(
                    0,
                    lambda: self.mostrar_cierre_pendiente(
                        session_id
                    )
                )
            else:
                self.root.after(
                    0,
                    lambda: self.logout_exitoso_si_coincide(
                        session_id
                    )
                )

        except ErrorAgente as error:
            mensaje = str(error)

            self.root.after(
                0,
                lambda mensaje=mensaje: self.error_logout(mensaje)
            )

    def logout_exitoso_si_coincide(self, session_id):
        if self.session_id != session_id:
            return

        self.logout_exitoso()

    def error_logout(self, mensaje):
        self.operacion_en_curso = False
        self.cierre_pendiente = True

        self.boton_logout.config(
            state="disabled",
            text="Verificando cierre..."
        )

        self.estado_sesion.config(
            text=(
                "No se pudo confirmar el cierre.\n"
                "Comprobando el estado local..."
            ),
            fg=COLOR_ADVERTENCIA
        )

        self.programar_verificacion()

    def mostrar_cierre_pendiente(self, session_id):
        if self.session_id != session_id:
            return

        self.operacion_en_curso = False
        self.cierre_pendiente = True

        self.boton_logout.config(
            state="disabled",
            text="Esperando sincronizacion..."
        )

        self.estado_sesion.config(
            text=(
                "Esperando red. La salida quedó guardada localmente.\n"
                "Al reconectar, se sincronizará automáticamente. "
                "Si no vuelve la conexión, el servidor cerrará la "
                "sesión al vencer el tiempo sin heartbeat."
            ),
            fg=COLOR_ADVERTENCIA
        )

        messagebox.showwarning(
            "Cierre pendiente",
            "No hay conexión con el servidor. "
            "La solicitud de cierre quedó guardada localmente y se "
            "sincronizará automáticamente cuando vuelva la red. "
            "Si no se reconecta, el servidor cerrará la sesión "
            "cuando venza el tiempo sin heartbeat."
        )

        self.programar_verificacion()

    # ======================================
    # VERIFICACION PERIODICA
    # ======================================

    def programar_verificacion(self):
        if not self.cierre_pendiente:
            return

        if self.verificacion_programada is not None:
            return

        self.verificacion_programada = self.root.after(
            VERIFICATION_INTERVAL,
            self.verificar_estado_sesion
        )

    def verificar_estado_sesion(self):
        self.verificacion_programada = None

        if not self.cierre_pendiente:
            return

        if self.verificacion_en_curso:
            self.programar_verificacion()
            return

        self.verificacion_en_curso = True

        token = self.token
        session_id = self.session_id

        threading.Thread(
            target=self.procesar_verificacion,
            args=(token, session_id),
            daemon=True
        ).start()

    def procesar_verificacion(self, token, session_id):
        try:
            resultado = solicitar_agente(
                "status",
                token,
                session_id=session_id
            )

            estado = resultado.get("status")

            self.root.after(
                0,
                lambda: self.actualizar_estado_verificado(
                    session_id,
                    estado
                )
            )

        except ErrorAgente:
            self.root.after(
                0,
                self.reintentar_verificacion
            )

    def actualizar_estado_verificado(self, session_id, estado):
        self.verificacion_en_curso = False

        if self.session_id != session_id:
            return

        if not self.cierre_pendiente:
            return

        if estado == "not_active":
            self.cierre_pendiente = False
            self.logout_exitoso()
            return

        if estado == "pending_close":
            self.boton_logout.config(
                state="disabled",
                text="Esperando sincronizacion..."
            )

            self.estado_sesion.config(
                text=(
                    "Salida registrada localmente.\n"
                    "Esperando conexion con FastAPI..."
                ),
                fg=COLOR_ADVERTENCIA
            )

        elif estado == "active":
            self.cierre_pendiente = False
            self.operacion_en_curso = False
            self.programar_revision_sesion()

            self.boton_logout.config(
                state="normal",
                text="Cerrar sesion"
            )

            self.estado_sesion.config(
                text=(
                    "La sesion sigue activa.\n"
                    "Puedes intentar cerrarla nuevamente."
                ),
                fg=COLOR_ERROR
            )
            return

        elif estado == "different_session":
            self.estado_sesion.config(
                text=(
                    "Se detecto otra sesion local.\n"
                    "Se requiere revisar el estado de LabMonitor."
                ),
                fg=COLOR_ERROR
            )

        else:
            self.estado_sesion.config(
                text="No fue posible determinar el estado de la sesion.",
                fg=COLOR_ERROR
            )

        self.programar_verificacion()

    def reintentar_verificacion(self):
        self.verificacion_en_curso = False

        if self.cierre_pendiente:
            self.estado_sesion.config(
                text=(
                    "Esperando comunicacion con "
                    "el agente de LabMonitor..."
                ),
                fg=COLOR_ADVERTENCIA
            )

            self.programar_verificacion()

    # ======================================
    # CIERRE CONFIRMADO
    # ======================================

    def logout_exitoso(self):
        self.cancelar_revision_sesion()
        self.cancelar_monitoreo_actividad()

        if self.verificacion_programada is not None:
            self.root.after_cancel(
                self.verificacion_programada
            )
            self.verificacion_programada = None

        self.operacion_en_curso = False
        self.cierre_pendiente = False
        self.verificacion_en_curso = False

        self.usuario = None
        self.token = None
        self.session_id = None
        self.root.attributes("-fullscreen", True)
        self.root.resizable(False, False)

        self.mostrar_login()

    # ======================================
    # CERRAR VENTANA
    # ======================================

    def al_cerrar_ventana(self):
        if self.operacion_en_curso:
            messagebox.showwarning(
                "LabMonitor",
                "Espera a que termine la operacion."
            )
            return

        if self.cierre_pendiente:
            messagebox.showwarning(
                "Cierre pendiente",
                "La salida aun se esta sincronizando. "
                "Espera a que termine."
            )
            return

        if self.session_id is not None:
            messagebox.showwarning(
                "Sesion activa",
                "Primero debes cerrar tu sesion "
                "desde el boton de LabMonitor."
            )
            return

        self.mostrar_admin_login("exit")


# ==========================================
# INICIO
# ==========================================

if __name__ == "__main__":
    root = tk.Tk()
    app = LabMonitorClient(root)
    root.mainloop()
