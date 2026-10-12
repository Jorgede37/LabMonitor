
import json
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

SERVER_URL = "http://127.0.0.1:8000"
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


# ==========================================
# COMUNICACION CON EL AGENTE
# ==========================================

class ErrorAgente(Exception):
    pass


def solicitar_agente(
    accion,
    student_token,
    session_id=None
):

    solicitud = {
        "action": accion,
        "student_token": student_token
    }

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

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.al_cerrar_ventana
        )

        self.mostrar_login()

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
            text="Autenticando y registrando sesion...",
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

            session_id = sesion.get("session_id")

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

        # Comienza la comprobacion automatica.
        self.programar_verificacion()

    def mostrar_sesion(self):

        self.limpiar()

        tarjeta = self.crear_tarjeta()

        tk.Label(
            tarjeta,
            text="\u2713",
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
                self.error_logout(session_id, mensaje)
            )

    def logout_exitoso_si_coincide(
        self,
        session_id
    ):

        if self.session_id != session_id:
            return

        self.logout_exitoso()

    def error_logout(self, session_id, mensaje):

        if self.session_id != session_id:
            return

        self.operacion_en_curso = False
        self.cierre_pendiente = True

        self.boton_logout.config(
            state="disabled",
            text="Verificando cierre..."
        )

        self.estado_sesion.config(
            text=(
                "No se pudo confirmar el cierre.\n"
                "Comprobando el estado de la sesion..."
            ),
            fg=COLOR_ADVERTENCIA
        )

        self.programar_verificacion()

    # ======================================
    # VERIFICACION PERIODICA
    # ======================================

    def programar_verificacion(self):

        # Verificamos tanto sesiones activas como
        # cierres pendientes de confirmacion.
        if self.session_id is None:
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

        if self.session_id is None:
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

            estado = resultado.get("status", "unknown")

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
                lambda: self.reintentar_verificacion(
                    session_id
                )
            )

    def actualizar_estado_verificado(
        self,
        session_id,
        estado
    ):

        if self.session_id != session_id:
            return

        self.verificacion_en_curso = False

        if estado == "not_active":

            # El servidor confirmo que la sesion
            # termino y SQLite fue sincronizada.
            cierre_automatico = (
                not self.cierre_pendiente
                and not self.operacion_en_curso
            )

            self.logout_exitoso()

            if cierre_automatico:
                messagebox.showinfo(
                    "LabMonitor",
                    "Tu sesion de laboratorio "
                    "fue finalizada automaticamente.\n\n"
                    "Puedes iniciar una nueva sesion "
                    "cuando el servicio este disponible."
                )

            return

        if estado == "pending_close":

            self.cierre_pendiente = True

            self.boton_logout.config(
                state="disabled",
                text="Esperando sincronizacion..."
            )

            self.estado_sesion.config(
                text=(
                    "Salida registrada localmente.\n"
                    "Esperando confirmacion del servidor..."
                ),
                fg=COLOR_ADVERTENCIA
            )

        elif estado == "active":

            if self.cierre_pendiente:

                # El cierre no se confirmo.
                # Se permite volver a intentarlo.
                self.cierre_pendiente = False
                self.operacion_en_curso = False

                self.boton_logout.config(
                    state="normal",
                    text="Cerrar sesion"
                )

                self.estado_sesion.config(
                    text=(
                        "La sesion sigue activa.\n"
                        "Puedes intentar cerrarla nuevamente."
                    ),
                    fg=COLOR_ADVERTENCIA
                )

            elif not self.operacion_en_curso:

                self.estado_sesion.config(
                    text="Sesion activa y verificada.",
                    fg=COLOR_EXITO
                )

        elif estado == "different_session":

            self.estado_sesion.config(
                text=(
                    "Se detecto otra sesion local.\n"
                    "Se requiere revisar LabMonitor."
                ),
                fg=COLOR_ERROR
            )

        else:

            # 'unknown' incluye problemas de red.
            # No se cierra la sesion por ello.
            self.estado_sesion.config(
                text=(
                    "No fue posible comprobar el estado.\n"
                    "Se intentara nuevamente."
                ),
                fg=COLOR_ADVERTENCIA
            )

        self.programar_verificacion()

    def reintentar_verificacion(self, session_id):

        if self.session_id != session_id:
            return

        self.verificacion_en_curso = False

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

        self.root.destroy()


# ==========================================
# INICIO
# ==========================================

if __name__ == "__main__":

    root = tk.Tk()

    app = LabMonitorClient(root)

    root.mainloop()
