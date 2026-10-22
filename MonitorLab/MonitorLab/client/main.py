import json
import os
import threading
import tkinter as tk

from tkinter import ttk, messagebox

import requests

import win32con
import win32file
import win32pipe
import pywintypes


# ==========================================
# CONFIGURACION
# ==========================================

SERVER_URL = os.environ.get("LABMONITOR_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")

PIPE_NAME = r"\\.\pipe\LabMonitorStudent"

COLOR_FONDO = "#0f172a"
COLOR_TARJETA = "#1e293b"
COLOR_TEXTO = "#f8fafc"
COLOR_SECUNDARIO = "#94a3b8"
COLOR_PRINCIPAL = "#2563eb"
COLOR_ERROR = "#f87171"
COLOR_EXITO = "#22c55e"
COLOR_ADVERTENCIA = "#fbbf24"

VERIFICATION_INTERVAL = 5000
SESSION_CHECK_INTERVAL = 10000


# ==========================================
# COMUNICACION CON EL AGENTE
# ==========================================

class ErrorAgente(Exception):
    pass


def solicitar_agente(
    accion,
    student_token=None,
    session_id=None
):

    solicitud = {
        "action": accion
    }

    if student_token is not None:
        solicitud["student_token"] = student_token

    if session_id is not None:
        solicitud["session_id"] = session_id

    try:

        win32pipe.WaitNamedPipe(
            PIPE_NAME,
            5000
        )

        pipe = win32file.CreateFile(
            PIPE_NAME,
            win32con.GENERIC_READ
            | win32con.GENERIC_WRITE,
            0,
            None,
            win32con.OPEN_EXISTING,
            0,
            None
        )

    except pywintypes.error as error:

        raise ErrorAgente(
            "No fue posible conectar con el agente. "
            "Comprueba que local_bridge.py "
            "este ejecutandose."
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
                "El agente devolvio "
                "una respuesta invalida."
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

        self.root.geometry("450x500")
        self.root.resizable(False, False)
        self.root.configure(bg=COLOR_FONDO)

        self.usuario = None
        self.token = None
        self.session_id = None

        self.operacion_en_curso = False

        self.cierre_pendiente = False
        self.verificacion_en_curso = False
        self.verificacion_programada = None
        self.revision_sesion_programada = None
        self.revision_sesion_en_curso = False

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.al_cerrar_ventana
        )

        self.configuracion = None
        self.admin_token = None
        self.modo_admin = None
        self.consultar_configuracion_inicial()

    # ======================================
    # INTERFAZ GENERAL
    # ======================================

    def limpiar(self):

        for widget in self.root.winfo_children():
            widget.destroy()

    def crear_tarjeta(self):

        tarjeta = tk.Frame(
            self.root,
            bg=COLOR_TARJETA,
            padx=35,
            pady=30
        )

        tarjeta.pack(
            expand=True,
            fill="both",
            padx=25,
            pady=25
        )

        return tarjeta

    # ======================================
    # CONFIGURACION INICIAL
    # ======================================

    def pantalla_mensaje(self, titulo, mensaje, reintentar=False):
        self.limpiar()
        tarjeta = self.crear_tarjeta()
        tk.Label(tarjeta, text=titulo, font=("Segoe UI", 19, "bold"),
                 bg=COLOR_TARJETA, fg=COLOR_TEXTO,
                 wraplength=320).pack(pady=(30, 20))
        tk.Label(tarjeta, text=mensaje, font=("Segoe UI", 11),
                 bg=COLOR_TARJETA, fg=COLOR_SECUNDARIO,
                 wraplength=320, justify="center").pack(pady=15)
        if reintentar:
            tk.Button(tarjeta, text="Reintentar",
                      command=self.consultar_configuracion_inicial,
                      bg=COLOR_PRINCIPAL, fg="white").pack(fill="x", pady=15)

    def consultar_configuracion_inicial(self):
        self.pantalla_mensaje("LabMonitor", "Consultando configuracion del equipo...")
        threading.Thread(target=self._consultar_configuracion, daemon=True).start()

    def _consultar_configuracion(self):
        try:
            datos = solicitar_agente("configuration")
            if not isinstance(datos, dict) or not isinstance(datos.get("configured"), bool):
                raise ValueError("Respuesta de configuracion invalida.")
            self.root.after(0, lambda d=datos: self._configuracion_recibida(d))
        except (ErrorAgente, ValueError) as error:
            mensaje = str(error)
            self.root.after(0, lambda m=mensaje: self.pantalla_mensaje(
                "Conexion no disponible", m, reintentar=True))

    def _configuracion_recibida(self, datos):
        self.configuracion = datos
        if datos["configured"]:
            self.mostrar_login()
        else:
            self.mostrar_admin_login("setup")

    def mostrar_admin_login(self, modo="setup"):
        self.modo_admin = modo
        self.limpiar()
        tarjeta = self.crear_tarjeta()
        titulo = "Configuracion inicial" if modo == "setup" else "Acceso administrativo"
        tk.Label(tarjeta, text=titulo, font=("Segoe UI", 19, "bold"),
                 bg=COLOR_TARJETA, fg=COLOR_TEXTO).pack(pady=(10, 15))
        tk.Label(tarjeta, text="Usuario administrador", bg=COLOR_TARJETA,
                 fg=COLOR_TEXTO).pack(anchor="w")
        usuario = ttk.Entry(tarjeta)
        usuario.pack(fill="x", pady=(5, 15), ipady=5)
        tk.Label(tarjeta, text="Contrasena", bg=COLOR_TARJETA,
                 fg=COLOR_TEXTO).pack(anchor="w")
        clave = ttk.Entry(tarjeta, show="*")
        clave.pack(fill="x", pady=(5, 15), ipady=5)
        estado = tk.Label(tarjeta, text="", bg=COLOR_TARJETA,
                          fg=COLOR_ERROR, wraplength=320)
        estado.pack(pady=10)
        boton = tk.Button(tarjeta, text="Ingresar como administrador",
                          bg=COLOR_PRINCIPAL, fg="white")
        boton.pack(fill="x", ipady=7)

        def enviar():
            nombre = usuario.get().strip()
            password = clave.get()
            if not nombre or not password:
                estado.config(text="Ingresa usuario y contrasena.")
                return
            boton.config(state="disabled")
            threading.Thread(target=self._autenticar_admin,
                             args=(nombre, password, modo, estado, boton),
                             daemon=True).start()

        boton.config(command=enviar)
        clave.bind("<Return>", lambda _event: enviar())
        tk.Button(tarjeta, text="Volver", command=self._volver_desde_admin,
                  bg=COLOR_TARJETA, fg=COLOR_SECUNDARIO).pack(pady=12)
        usuario.focus_set()

    def _volver_desde_admin(self):
        self.admin_token = None
        if self.configuracion and self.configuracion.get("configured"):
            self.mostrar_login()
        else:
            self.consultar_configuracion_inicial()

    def _autenticar_admin(self, nombre, password, modo, estado, boton):
        try:
            respuesta = requests.post(
                f"{SERVER_URL}/auth/login",
                json={"username": nombre, "password": password},
                timeout=10
            )
            respuesta.raise_for_status()
            datos = respuesta.json()
            token = datos.get("access_token")
            if datos.get("user", {}).get("role") != "admin" or not token:
                raise ValueError("La cuenta no tiene permisos de administrador.")
            # Verificar autorizacion efectiva en un endpoint protegido.
            verificar = requests.get(
                f"{SERVER_URL}/admin/laboratories",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10
            )
            verificar.raise_for_status()
            laboratorios = verificar.json()
            if not isinstance(laboratorios, list):
                raise ValueError("Respuesta de laboratorios invalida.")
            self.root.after(0, lambda: self._admin_autenticado(
                token, modo, laboratorios))
        except (requests.RequestException, ValueError) as error:
            mensaje = str(error)
            self.root.after(0, lambda m=mensaje: (
                estado.config(text=m), boton.config(state="normal")))

    def _admin_autenticado(self, token, modo, laboratorios):
        self.admin_token = token
        if modo == "exit":
            if messagebox.askyesno("LabMonitor", "¿Cerrar solo la ventana de LabMonitor?"):
                self.root.destroy()
            else:
                self._volver_desde_admin()
            return
        self.mostrar_asistente(laboratorios)

    def mostrar_asistente(self, laboratorios):
        self.limpiar()
        tarjeta = self.crear_tarjeta()
        tk.Label(tarjeta, text="Configurar computadora",
                 font=("Segoe UI", 17, "bold"), bg=COLOR_TARJETA,
                 fg=COLOR_TEXTO).pack(pady=(0, 12))
        tk.Label(tarjeta, text="Nombre visible de la PC", bg=COLOR_TARJETA,
                 fg=COLOR_TEXTO).pack(anchor="w")
        nombre = ttk.Entry(tarjeta)
        nombre.pack(fill="x", pady=(4, 12), ipady=4)
        nombre.insert(0, self.configuracion.get("display_name") or "")
        tk.Label(tarjeta, text="Laboratorio existente", bg=COLOR_TARJETA,
                 fg=COLOR_TEXTO).pack(anchor="w")
        nombres = [lab["name"] for lab in laboratorios]
        selector = ttk.Combobox(tarjeta, values=nombres, state="readonly")
        selector.pack(fill="x", pady=(4, 10))
        if nombres:
            selector.current(0)
        tk.Label(tarjeta, text="O crear laboratorio nuevo", bg=COLOR_TARJETA,
                 fg=COLOR_TEXTO).pack(anchor="w")
        nuevo = ttk.Entry(tarjeta)
        nuevo.pack(fill="x", pady=(4, 12), ipady=4)
        estado = tk.Label(tarjeta, text="", bg=COLOR_TARJETA,
                          fg=COLOR_ERROR, wraplength=320)
        estado.pack(pady=6)
        guardar = tk.Button(tarjeta, text="Guardar configuracion",
                            bg=COLOR_PRINCIPAL, fg="white")
        guardar.pack(fill="x", ipady=8)

        def enviar():
            nombre_pc = nombre.get().strip()
            nombre_lab = nuevo.get().strip()
            lab = next((x for x in laboratorios if x["name"] == selector.get()), None)
            if not nombre_pc or len(nombre_pc) > 100:
                estado.config(text="Nombre de PC requerido (maximo 100 caracteres).")
                return
            if nombre_lab and len(nombre_lab) > 100:
                estado.config(text="Nombre de laboratorio demasiado largo.")
                return
            if not nombre_lab and lab is None:
                estado.config(text="Selecciona o crea un laboratorio.")
                return
            guardar.config(state="disabled")
            threading.Thread(target=self._guardar_configuracion,
                             args=(nombre_pc, nombre_lab, lab, estado, guardar),
                             daemon=True).start()

        guardar.config(command=enviar)
        tk.Button(tarjeta, text="Cancelar", command=self._volver_desde_admin,
                  bg=COLOR_TARJETA, fg=COLOR_SECUNDARIO).pack(pady=10)

    def _guardar_configuracion(self, nombre_pc, nombre_lab, lab, estado, boton):
        headers = {"Authorization": f"Bearer {self.admin_token}"}
        try:
            if nombre_lab:
                crear = requests.post(
                    f"{SERVER_URL}/admin/laboratories",
                    json={"name": nombre_lab}, headers=headers, timeout=10)
                if crear.status_code == 409:
                    # Otro administrador pudo crear el mismo laboratorio.
                    lista = requests.get(f"{SERVER_URL}/admin/laboratories",
                                         headers=headers, timeout=10)
                    lista.raise_for_status()
                    lab = next((x for x in lista.json()
                                if x["name"].casefold() == nombre_lab.casefold()), None)
                    if lab is None:
                        crear.raise_for_status()
                else:
                    crear.raise_for_status()
                    lab = crear.json()
            equipo_id = self.configuracion["computer_id"]
            respuesta = requests.put(
                f"{SERVER_URL}/admin/computers/{equipo_id}/configuration",
                json={"display_name": nombre_pc, "laboratory_id": lab["id"]},
                headers=headers, timeout=10)
            respuesta.raise_for_status()
            self.root.after(0, self._configuracion_guardada)
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            mensaje = str(error)
            self.root.after(0, lambda m=mensaje: (
                estado.config(text=m), boton.config(state="normal")))

    def _configuracion_guardada(self):
        self.admin_token = None
        messagebox.showinfo("LabMonitor", "Configuracion guardada en el servidor.")
        self.consultar_configuracion_inicial()

    # ======================================
    # PANTALLA LOGIN
    # ======================================

    def mostrar_login(self):

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

        tk.Button(
            tarjeta, text="Administracion",
            command=lambda: self.mostrar_admin_login("setup"),
            bg=COLOR_TARJETA, fg=COLOR_SECUNDARIO,
            relief="flat"
        ).pack(pady=(0, 5))

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

        matricula = (
            self.entrada_matricula.get().strip()
        )

        password = self.entrada_password.get()

        if not matricula or not password:

            self.estado.config(
                text=(
                    "Introduce tu matricula "
                    "y contrasena."
                ),
                fg=COLOR_ERROR
            )

            return

        self.operacion_en_curso = True

        self.boton_login.config(
            state="disabled",
            text="Validando..."
        )

        self.estado.config(
            text=(
                "Autenticando y registrando sesion..."
            ),
            fg=COLOR_SECUNDARIO
        )

        threading.Thread(
            target=self.procesar_login,
            args=(matricula, password),
            daemon=True
        ).start()

    def procesar_login(
        self,
        matricula,
        password
    ):

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

            respuesta.raise_for_status()

            datos = respuesta.json()

            usuario = datos.get("user", {})
            token = datos.get("access_token")

            if usuario.get("role") != "student":

                raise ValueError(
                    "Esta aplicacion es exclusiva "
                    "para estudiantes."
                )

            if not token:

                raise ValueError(
                    "El servidor no devolvio "
                    "un token valido."
                )

            sesion = solicitar_agente(
                "start",
                token
            )

            session_id = sesion.get(
                "session_id"
            )

            if not session_id:

                raise ValueError(
                    "El agente no devolvio "
                    "el ID de sesion."
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
                lambda mensaje=mensaje:
                self.mostrar_error(mensaje)
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

    # ======================================
    # SESION INICIADA
    # ======================================

    def login_exitoso(
        self,
        usuario,
        token,
        session_id
    ):

        self.operacion_en_curso = False

        self.usuario = usuario
        self.token = token
        self.session_id = session_id

        self.cierre_pendiente = False
        self.verificacion_en_curso = False

        self.mostrar_sesion()
        self.programar_revision_sesion()

    def mostrar_sesion(self):

        self.limpiar()

        tarjeta = self.crear_tarjeta()

        tk.Label(
            tarjeta,
            text="âœ“",
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
            text=self.usuario.get(
                "full_name",
                "Estudiante"
            ),
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
            text=(
                f"ID de sesion: {self.session_id}"
            ),
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
            self.root.after_cancel(self.revision_sesion_programada)
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
                "status", token, session_id=session_id
            )
            estado = respuesta.get("status", "unknown")
        except (ErrorAgente, Exception):
            estado = "unknown"

        self.root.after(
            0,
            lambda: self.actualizar_revision_sesion(session_id, estado)
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
            # Evitar borrar el estado visual ante una inconsistencia.
            self.estado_sesion.config(
                text="Se detecto una sesion local diferente. "
                     "Solicita una revision del agente.",
                fg=COLOR_ADVERTENCIA
            )
        elif estado == "unknown":
            self.estado_sesion.config(
                text="No se pudo verificar la sesion con el servidor. "
                     "Se intentara nuevamente.",
                fg=COLOR_ADVERTENCIA
            )
        elif estado == "active":
            self.estado_sesion.config(text="", fg=COLOR_SECUNDARIO)

        self.programar_revision_sesion()

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

    def procesar_logout(
        self,
        token,
        session_id
    ):

        try:

            solicitar_agente(
                "end",
                token
            )

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
                lambda mensaje=mensaje:
                self.error_logout(mensaje)
            )

    def logout_exitoso_si_coincide(
        self,
        session_id
    ):

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

    # ======================================
    # VERIFICACION PERIODICA
    # ======================================

    def programar_verificacion(self):

        if not self.cierre_pendiente:
            return

        if self.verificacion_programada is not None:
            return

        self.verificacion_programada = (
            self.root.after(
                VERIFICATION_INTERVAL,
                self.verificar_estado_sesion
            )
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

    def procesar_verificacion(
        self,
        token,
        session_id
    ):

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

    def actualizar_estado_verificado(
        self,
        session_id,
        estado
    ):

        self.verificacion_en_curso = False

        if self.session_id != session_id:
            return

        if not self.cierre_pendiente:
            return

        if estado == "not_active":

            # No existe una sesion activa local.
            # En esta prueba controlada asumimos
            # que el cierre ya fue recuperado.
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

            # El agente sigue considerando
            # que la sesion esta activa.
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
                    "Se requiere revisar el estado "
                    "de LabMonitor."
                ),
                fg=COLOR_ERROR
            )

        else:

            self.estado_sesion.config(
                text=(
                    "No fue posible determinar "
                    "el estado de la sesion."
                ),
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
