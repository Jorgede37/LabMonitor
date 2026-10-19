
import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import logoUad from './assets/uad_logo.png'

const INTERVALO_ACTUALIZACION = 5000
const TIEMPO_INACTIVIDAD_MS = 30 * 60 * 1000
const INTERVALO_RENOVACION_MS = 5 * 60 * 1000
const CLAVE_TOKEN_ADMIN = 'labmonitor.admin.token'
const CLAVE_USUARIO_ADMIN = 'labmonitor.admin.user'
const CLAVE_ACTIVIDAD_ADMIN = 'labmonitor.admin.lastActivity'
const AREAS_DASHBOARD = [
  { id: 'resumen', label: 'Resumen' },
  { id: 'computadoras', label: 'Computadoras' },
  { id: 'administradores', label: 'Administradores' },
  { id: 'estudiantes', label: 'Estudiantes' },
  { id: 'instalacion', label: 'Instalación' },
  { id: 'alertas', label: 'Alertas de hardware' },
]

function formatearFecha(fecha) {
  if (!fecha) return 'N/D'

  const valor = String(fecha)
  const tieneZona = /(?:Z|[+-]\d{2}:\d{2})$/i.test(valor)
  const fechaUTC = tieneZona ? valor : `${valor}Z`
  const resultado = new Date(fechaUTC)

  if (Number.isNaN(resultado.getTime())) {
    return 'Fecha inválida'
  }

  return resultado.toLocaleString('es-MX', {
    timeZone: 'America/Mexico_City',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
}

function traducirEvento(tipo) {
  const nombres = {
    DEVICE_DISCONNECTED: 'Dispositivo desconectado',
    DEVICE_CONNECTED: 'Dispositivo conectado',
    HARDWARE_ADDED: 'Hardware agregado',
    HARDWARE_REMOVED: 'Hardware retirado',
    HARDWARE_CHANGED: 'Hardware modificado',
    SYSTEM_START: 'Sistema iniciado',
    SYSTEM_SHUTDOWN: 'Sistema apagado',
  }

  return nombres[tipo] || tipo
}

function traducirTipoComponente(tipo) {
  const nombres = {
    cpu: 'Procesador',
    motherboard: 'Tarjeta madre',
    ram: 'Memoria RAM',
    gpu: 'Tarjeta gráfica',
    storage: 'Almacenamiento',
    mouse: 'Mouse',
    keyboard: 'Teclado',
    network: 'Adaptador de red',
  }

  return nombres[tipo] || tipo || 'Sistema'
}

function traducirEstado(estado) {
  if (estado === 'active') return 'Activo'
  if (estado === 'removed') return 'Desconectado'
  return estado || 'Desconocido'
}

function traducirEstadoCorreo(estado) {
  const nombres = {
    sent: 'Enviado',
    pending: 'Pendiente',
    failed: 'Falló',
    not_queued: 'Sin destinatario',
  }

  return nombres[estado] || estado || 'Desconocido'
}

async function leerRespuesta(respuesta) {
  const contenido = await respuesta.text()
  let datos = {}

  if (contenido) {
    try {
      datos = JSON.parse(contenido)
    } catch {
      datos = { detail: contenido }
    }
  }

  if (!respuesta.ok) {
    throw new Error(
      typeof datos.detail === 'string'
        ? datos.detail
        : `No fue posible completar la solicitud (HTTP ${respuesta.status}).`
    )
  }

  if (!contenido) {
    throw new Error('El servidor respondió sin contenido.')
  }

  if (typeof datos !== 'object' || datos === null || Array.isArray(datos)) {
    throw new Error('El servidor respondió con un formato inesperado.')
  }

  return datos
}

function RecuperacionPassword({ volver }) {
  const esRestablecimiento =
    window.location.pathname === '/reset-password'

  const tokenRecuperacion = new URLSearchParams(
    window.location.search
  ).get('token')

  const [identificador, setIdentificador] = useState('')
  const [nueva, setNueva] = useState('')
  const [confirmacion, setConfirmacion] = useState('')
  const [cargando, setCargando] = useState(false)
  const [mensaje, setMensaje] = useState('')
  const [error, setError] = useState('')
  const [completado, setCompletado] = useState(false)

  async function enviar(evento) {
    evento.preventDefault()
    setError('')
    setMensaje('')

    if (esRestablecimiento) {
      if (!tokenRecuperacion) {
        setError('El enlace no contiene un token de recuperación.')
        return
      }

      if (nueva.length < 8) {
        setError('La contraseña debe tener al menos 8 caracteres.')
        return
      }

      if (nueva !== confirmacion) {
        setError('Las contraseñas no coinciden.')
        return
      }
    }

    setCargando(true)

    try {
      const ruta = esRestablecimiento
        ? '/auth/reset-password'
        : '/auth/forgot-password'

      const cuerpo = esRestablecimiento
        ? {
            token: tokenRecuperacion,
            new_password: nueva,
          }
        : {
            identifier: identificador.trim(),
          }

      const respuesta = await fetch(ruta, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(cuerpo),
      })

      const datos = await leerRespuesta(respuesta)

      setMensaje(
        datos.message || 'Solicitud procesada correctamente.'
      )

      setNueva('')
      setConfirmacion('')

      if (esRestablecimiento) {
        setCompletado(true)

        // El token ya se consumió.
        // Lo quitamos de la barra de direcciones.
        window.history.replaceState(
          {},
          '',
          '/reset-password'
        )
      }
    } catch (err) {
      setError(
        err.message || 'Error de conexión con el servidor.'
      )
    } finally {
      setCargando(false)
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={enviar}>
        <img
          className="uad-logo login-logo"
          src={logoUad}
          alt="Universidad de Durango, Campus Aguascalientes"
        />

        <h1>LabMonitor</h1>

        <p className="subtitle">
          {esRestablecimiento
            ? 'Restablecer contraseña'
            : 'Recuperar contraseña de estudiante'}
        </p>

        {!esRestablecimiento && (
          <div className="form-group">
            <label htmlFor="identificador">
              Matrícula o correo electrónico
            </label>

            <input
              id="identificador"
              type="text"
              value={identificador}
              onChange={(e) =>
                setIdentificador(e.target.value)
              }
              placeholder="Escribe tu matrícula o correo"
              autoComplete="username"
              maxLength={254}
              required
            />
          </div>
        )}

        {esRestablecimiento && !completado && (
          <>
            <div className="form-group">
              <label htmlFor="nueva">
                Nueva contraseña
              </label>

              <input
                id="nueva"
                type="password"
                value={nueva}
                onChange={(e) =>
                  setNueva(e.target.value)
                }
                placeholder="Mínimo 8 caracteres"
                minLength={8}
                maxLength={128}
                autoComplete="new-password"
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="confirmacion">
                Confirmar contraseña
              </label>

              <input
                id="confirmacion"
                type="password"
                value={confirmacion}
                onChange={(e) =>
                  setConfirmacion(e.target.value)
                }
                placeholder="Repite tu contraseña"
                minLength={8}
                maxLength={128}
                autoComplete="new-password"
                required
              />
            </div>
          </>
        )}

        {error && (
          <p className="error-message" role="alert">
            {error}
          </p>
        )}

        {mensaje && (
          <p
            role="status"
            style={{
              color: '#16803d',
              marginBottom: '1rem',
            }}
          >
            {mensaje}
          </p>
        )}

        {!completado && (
          <button
            className="primary-button"
            type="submit"
            disabled={
              cargando ||
              (esRestablecimiento && !tokenRecuperacion)
            }
          >
            {cargando
              ? 'Procesando...'
              : esRestablecimiento
                ? 'Cambiar contraseña'
                : 'Enviar enlace de recuperación'}
          </button>
        )}

        <button
          type="button"
          className="back-button"
          onClick={volver}
          style={{ marginTop: '1rem' }}
        >
          Volver al inicio de sesión
        </button>

        <p className="login-footer">
          LabMonitor · Universidad de Durango
        </p>
      </form>
    </main>
  )
}

function RegistroAlumno({ volver }) {
  const [matricula, setMatricula] = useState('')
  const [nombre, setNombre] = useState('')
  const [correo, setCorreo] = useState('')
  const [contrasena, setContrasena] = useState('')
  const [confirmacion, setConfirmacion] = useState('')
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState('')
  const [mensaje, setMensaje] = useState('')

  async function enviar(evento) {
    evento.preventDefault()
    setError('')
    setMensaje('')

    if (!/^[0-9]{10}$/.test(matricula)) {
      setError('La matrícula debe contener exactamente 10 dígitos.')
      return
    }
    if (contrasena.length < 8) {
      setError('La contraseña debe tener al menos 8 caracteres.')
      return
    }
    if (contrasena !== confirmacion) {
      setError('Las contraseñas no coinciden.')
      return
    }

    setCargando(true)
    try {
      const respuesta = await fetch('/users/register', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          student_id: matricula,
          full_name: nombre.trim(),
          email: correo.trim(),
          password: contrasena,
        }),
      })
      const datos = await leerRespuesta(respuesta)
      setMensaje(
        datos.message || 'Tu cuenta de estudiante fue creada correctamente.'
      )
      setMatricula('')
      setNombre('')
      setCorreo('')
      setContrasena('')
      setConfirmacion('')
    } catch (err) {
      setError(err.message || 'No fue posible crear la cuenta.')
    } finally {
      setCargando(false)
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={enviar}>
        <img
          className="uad-logo login-logo"
          src={logoUad}
          alt="Universidad de Durango, Campus Aguascalientes"
        />
        <h1>Crear cuenta</h1>
        <p className="subtitle">Registro de estudiante en LabMonitor</p>

        <div className="form-group">
          <label htmlFor="registro-matricula">Matrícula</label>
          <input
            id="registro-matricula"
            type="text"
            inputMode="numeric"
            autoComplete="username"
            value={matricula}
            onChange={(evento) => setMatricula(evento.target.value)}
            maxLength={10}
            pattern="[0-9]{10}"
            placeholder="10 dígitos"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="registro-nombre">Nombre completo</label>
          <input
            id="registro-nombre"
            type="text"
            autoComplete="name"
            value={nombre}
            onChange={(evento) => setNombre(evento.target.value)}
            maxLength={150}
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="registro-correo">Correo electrónico</label>
          <input
            id="registro-correo"
            type="email"
            autoComplete="email"
            value={correo}
            onChange={(evento) => setCorreo(evento.target.value)}
            maxLength={254}
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="registro-contrasena">Contraseña</label>
          <input
            id="registro-contrasena"
            type="password"
            autoComplete="new-password"
            value={contrasena}
            onChange={(evento) => setContrasena(evento.target.value)}
            minLength={8}
            maxLength={128}
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="registro-confirmacion">Confirmar contraseña</label>
          <input
            id="registro-confirmacion"
            type="password"
            autoComplete="new-password"
            value={confirmacion}
            onChange={(evento) => setConfirmacion(evento.target.value)}
            minLength={8}
            maxLength={128}
            required
          />
        </div>

        {error && <p className="error-message" role="alert">{error}</p>}
        {mensaje && <p className="success-message" role="status">{mensaje}</p>}

        <button className="primary-button" type="submit" disabled={cargando}>
          {cargando ? 'Creando cuenta...' : 'Crear cuenta de estudiante'}
        </button>
        <button
          className="back-button"
          type="button"
          onClick={volver}
          style={{ marginTop: '1rem' }}
        >
          Volver
        </button>
      </form>
    </main>
  )
}

function App() {
  const [rutaActual, setRutaActual] = useState(
    window.location.pathname
  )
  const [areaActiva, setAreaActiva] = useState('resumen')

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const [token, setToken] = useState(
    () => window.sessionStorage.getItem(CLAVE_TOKEN_ADMIN)
  )
  const [usuario, setUsuario] = useState(() => {
    try {
      const guardado = window.sessionStorage.getItem(
        CLAVE_USUARIO_ADMIN
      )
      return guardado ? JSON.parse(guardado) : null
    } catch {
      return null
    }
  })

  const [estadisticas, setEstadisticas] = useState(null)
  const [computadoras, setComputadoras] = useState([])
  const [eventosHardware, setEventosHardware] = useState([])
  const [estadoCorreo, setEstadoCorreo] = useState(null)
  const [administradores, setAdministradores] = useState([])
  const [estudiantes, setEstudiantes] = useState([])
  const [nombreEstudiante, setNombreEstudiante] = useState('')
  const [matriculaEstudiante, setMatriculaEstudiante] = useState('')
  const [correoEstudiante, setCorreoEstudiante] = useState('')
  const [passwordEstudiante, setPasswordEstudiante] = useState('')
  const [creandoEstudiante, setCreandoEstudiante] = useState(false)
  const [nombreAdministrador, setNombreAdministrador] = useState('')
  const [usuarioAdministrador, setUsuarioAdministrador] = useState('')
  const [correoAdministrador, setCorreoAdministrador] = useState('')
  const [passwordAdministrador, setPasswordAdministrador] = useState('')
  const [creandoAdministrador, setCreandoAdministrador] = useState(false)
  const [mensajeAdministrador, setMensajeAdministrador] = useState('')
  const [usuarioEnEdicion, setUsuarioEnEdicion] = useState(null)
  const [guardandoUsuario, setGuardandoUsuario] = useState(false)
  const [mensajeUsuarios, setMensajeUsuarios] = useState('')
  const [codigoInstalacion, setCodigoInstalacion] = useState(null)
  const [generandoCodigo, setGenerandoCodigo] = useState(false)
  const [mensajeCodigo, setMensajeCodigo] = useState('')
  const [copiadoCodigo, setCopiadoCodigo] = useState(false)
  const [detalle, setDetalle] = useState(null)
  const [detalleIdActual, setDetalleIdActual] = useState(null)

  const [cargando, setCargando] = useState(false)
  const [actualizando, setActualizando] = useState(false)
  const [error, setError] = useState('')
  const [ultimaActualizacion, setUltimaActualizacion] =
    useState(null)

  const tokenRef = useRef(token)
  const detalleIdRef = useRef(null)
  const actualizandoRef = useRef(false)
  const sesionRef = useRef(0)
  const codigoTimerRef = useRef(null)
  const ultimaActividadRef = useRef(
    Number(window.sessionStorage.getItem(CLAVE_ACTIVIDAD_ADMIN)) ||
      Date.now()
  )
  const ultimaRenovacionRef = useRef(Date.now())

  useEffect(() => {
    function actualizarRuta() {
      setRutaActual(window.location.pathname)
    }

    window.addEventListener('popstate', actualizarRuta)

    return () => {
      window.removeEventListener(
        'popstate',
        actualizarRuta
      )
    }
  }, [])

  function navegar(ruta) {
    window.history.pushState({}, '', ruta)
    setRutaActual(ruta)
    setError('')
  }

  async function solicitarDatos(ruta, jwt) {
    const respuesta = await fetch(ruta, {
      headers: {
        Authorization: `Bearer ${jwt}`,
      },
      cache: 'no-store',
    })

    if (respuesta.status === 401) {
      const errorSesion = new Error(
        'Tu sesión expiró. Inicia sesión nuevamente.'
      )

      errorSesion.codigo = 401
      throw errorSesion
    }

    if (!respuesta.ok) {
      throw new Error(
        `Error al consultar ${ruta} (HTTP ${respuesta.status})`
      )
    }

    return respuesta.json()
  }

  const cerrarSesion = useCallback(() => {
    sesionRef.current += 1

    tokenRef.current = null
    window.sessionStorage.removeItem(CLAVE_TOKEN_ADMIN)
    window.sessionStorage.removeItem(CLAVE_USUARIO_ADMIN)
    window.sessionStorage.removeItem(CLAVE_ACTIVIDAD_ADMIN)
    detalleIdRef.current = null
    setDetalleIdActual(null)
    actualizandoRef.current = false

    setToken(null)
    setUsuario(null)
    setEstadisticas(null)
    setComputadoras([])
    setEventosHardware([])
    setEstadoCorreo(null)
    setAdministradores([])
    setEstudiantes([])
    setUsuarioEnEdicion(null)
    setMensajeUsuarios('')
    setCodigoInstalacion(null)
    setMensajeCodigo('')
    setCopiadoCodigo(false)
    if (codigoTimerRef.current) {
      window.clearTimeout(codigoTimerRef.current)
      codigoTimerRef.current = null
    }
    setDetalle(null)
    setPassword('')
    setError('')
    setUltimaActualizacion(null)
    setActualizando(false)
  }, [])

  const actualizarDatos = useCallback(
    async (jwt, silencioso = false) => {
      if (!jwt || actualizandoRef.current) return

      actualizandoRef.current = true
      const sesionActual = sesionRef.current

      if (!silencioso) {
        setActualizando(true)
      }

      try {
        const idDetalle = detalleIdRef.current

        const solicitudes = [
          solicitarDatos('/admin/dashboard', jwt),
          solicitarDatos('/admin/computers', jwt),
          solicitarDatos('/admin/hardware-events', jwt),
          solicitarDatos('/admin/administrators', jwt),
          solicitarDatos('/admin/students', jwt),
        ]

        if (idDetalle !== null) {
          solicitudes.push(
            solicitarDatos(
              `/admin/computers/${idDetalle}`,
              jwt
            )
          )
        }

        const resultados = await Promise.all(
          solicitudes
        )

        if (
          sesionActual !== sesionRef.current
        ) {
          return
        }

        setEstadisticas(resultados[0].statistics)
        setComputadoras(resultados[1].computers)
        setEventosHardware(resultados[2].events)
        setEstadoCorreo(resultados[2].email)
        setAdministradores(resultados[3].administrators)
        setEstudiantes(resultados[4].students)

        if (
          idDetalle !== null &&
          detalleIdRef.current === idDetalle
        ) {
          setDetalle(resultados[5])
        }

        setUltimaActualizacion(new Date())
        setError('')
      } catch (err) {
        if (
          sesionActual !== sesionRef.current
        ) {
          return
        }

        if (err.codigo === 401) {
          cerrarSesion()
          setError(
            'Tu sesión expiró. Inicia sesión nuevamente.'
          )
        } else {
          setError(err.message)
        }
      } finally {
        actualizandoRef.current = false

        if (
          sesionActual === sesionRef.current
        ) {
          setActualizando(false)
        }
      }
    },
    [cerrarSesion]
  )

  async function iniciarSesion(evento) {
    evento.preventDefault()
    setError('')
    setCargando(true)

    try {
      const respuesta = await fetch('/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username,
          password,
        }),
      })

      const datos = await leerRespuesta(respuesta)

      if (datos.user.role !== 'admin') {
        throw new Error(
          'El dashboard es exclusivo para administradores.'
        )
      }

      sesionRef.current += 1

      tokenRef.current = datos.access_token
      window.sessionStorage.setItem(
        CLAVE_TOKEN_ADMIN,
        datos.access_token
      )
      window.sessionStorage.setItem(
        CLAVE_USUARIO_ADMIN,
        JSON.stringify(datos.user)
      )
      ultimaActividadRef.current = Date.now()
      ultimaRenovacionRef.current = Date.now()
      window.sessionStorage.setItem(
        CLAVE_ACTIVIDAD_ADMIN,
        String(ultimaActividadRef.current)
      )
      detalleIdRef.current = null
      setDetalleIdActual(null)

      setToken(datos.access_token)
      setUsuario(datos.user)
      setPassword('')

      await actualizarDatos(datos.access_token)
    } catch (err) {
      setError(err.message)
    } finally {
      setCargando(false)
    }
  }

  async function crearEstudiante(evento) {
    evento.preventDefault()
    setError('')
    setMensajeUsuarios('')
    setCreandoEstudiante(true)

    try {
      const respuesta = await fetch('/admin/students', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer ' + tokenRef.current,
        },
        body: JSON.stringify({
          full_name: nombreEstudiante.trim(),
          student_id: matriculaEstudiante.trim(),
          email: correoEstudiante.trim(),
          password: passwordEstudiante,
        }),
      })
      const datos = await leerRespuesta(respuesta)
      setMensajeUsuarios(datos.message)
      setNombreEstudiante('')
      setMatriculaEstudiante('')
      setCorreoEstudiante('')
      setPasswordEstudiante('')
      await recargarUsuarios()
    } catch (err) {
      if (err.codigo === 401) cerrarSesion()
      setError(err.message)
    } finally {
      setCreandoEstudiante(false)
    }
  }

  async function crearAdministrador(evento) {
    evento.preventDefault()
    setError('')
    setMensajeAdministrador('')
    setCreandoAdministrador(true)

    try {
      const respuesta = await fetch('/admin/administrators', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokenRef.current}`,
        },
        body: JSON.stringify({
          full_name: nombreAdministrador.trim(),
          username: usuarioAdministrador.trim(),
          email: correoAdministrador.trim(),
          password: passwordAdministrador,
        }),
      })
      const datos = await leerRespuesta(respuesta)
      setMensajeAdministrador(datos.message || 'Administrador creado correctamente.')
      setNombreAdministrador('')
      setUsuarioAdministrador('')
      setCorreoAdministrador('')
      setPasswordAdministrador('')

      const [resultadoAdmins, resultadoEventos] = await Promise.all([
        solicitarDatos('/admin/administrators', tokenRef.current),
        solicitarDatos('/admin/hardware-events', tokenRef.current),
      ])
      setAdministradores(resultadoAdmins.administrators)
      setEstadoCorreo(resultadoEventos.email)
    } catch (err) {
      if (err.codigo === 401) {
        cerrarSesion()
      }
      setError(err.message)
    } finally {
      setCreandoAdministrador(false)
    }
  }

  function editarCuenta(tipo, cuenta) {
    setMensajeUsuarios('')
    setUsuarioEnEdicion({
      tipo,
      id: cuenta.id,
      full_name: cuenta.full_name || '',
      username: cuenta.username || '',
      student_id: cuenta.student_id || '',
      email: cuenta.email || '',
      is_active: Boolean(cuenta.is_active),
      password: '',
    })
  }

  async function recargarUsuarios() {
    const [admins, alumnos, eventos, dashboard] = await Promise.all([
      solicitarDatos('/admin/administrators', tokenRef.current),
      solicitarDatos('/admin/students', tokenRef.current),
      solicitarDatos('/admin/hardware-events', tokenRef.current),
      solicitarDatos('/admin/dashboard', tokenRef.current),
    ])
    setAdministradores(admins.administrators)
    setEstudiantes(alumnos.students)
    setEstadoCorreo(eventos.email)
    setEstadisticas(dashboard.statistics)
  }

  async function guardarEdicionUsuario(evento) {
    evento.preventDefault()
    if (!usuarioEnEdicion) return
    setError('')
    setMensajeUsuarios('')
    setGuardandoUsuario(true)

    const { tipo, id, password: nuevaPassword, ...campos } = usuarioEnEdicion
    const ruta = tipo === 'admin'
      ? `/admin/administrators/${id}`
      : `/admin/students/${id}`
    const datos = tipo === 'admin'
      ? {
          full_name: campos.full_name.trim(),
          username: campos.username.trim(),
          email: campos.email.trim(),
          is_active: campos.is_active,
          ...(nuevaPassword ? { password: nuevaPassword } : {}),
        }
      : {
          full_name: campos.full_name.trim(),
          student_id: campos.student_id.trim(),
          email: campos.email.trim(),
          is_active: campos.is_active,
          ...(nuevaPassword ? { password: nuevaPassword } : {}),
        }

    try {
      const respuesta = await fetch(ruta, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer ' + tokenRef.current,
        },
        body: JSON.stringify(datos),
      })
      const resultado = await leerRespuesta(respuesta)
      setMensajeUsuarios(resultado.message || 'Cuenta actualizada correctamente.')
      setUsuarioEnEdicion(null)
      await recargarUsuarios()
    } catch (err) {
      if (err.codigo === 401) cerrarSesion()
      setError(err.message)
    } finally {
      setGuardandoUsuario(false)
    }
  }

  async function desactivarCuenta(tipo, cuenta) {
    const nombreTipo = tipo === 'admin' ? 'administrador' : 'estudiante'
    if (!window.confirm(
      'Desactivar la cuenta de ' + cuenta.full_name +
      '? Se conservará su historial y podrás reactivarla después.'
    )) return

    setError('')
    setMensajeUsuarios('')
    try {
      const respuesta = await fetch(
        `/admin/${tipo === 'admin' ? 'administrators' : 'students'}/${cuenta.id}`,
        {
          method: 'DELETE',
          headers: {
            Authorization: 'Bearer ' + tokenRef.current,
          },
        }
      )
      const resultado = await leerRespuesta(respuesta)
      setMensajeUsuarios(resultado.message || `Cuenta de ${nombreTipo} desactivada.`)
      if (usuarioEnEdicion?.id === cuenta.id) setUsuarioEnEdicion(null)
      await recargarUsuarios()
    } catch (err) {
      if (err.codigo === 401) cerrarSesion()
      setError(err.message)
    }
  }

  async function eliminarCuentaPermanentemente(tipo, cuenta) {
    const nombreTipo = tipo === 'admin' ? 'administrador' : 'estudiante'
    if (!window.confirm(
      `¿Eliminar permanentemente la cuenta de ${cuenta.full_name}? ` +
      'No se podrá recuperar. Se conservará el historial de actividad, ' +
      'pero quedará anonimizado.'
    )) return

    setError('')
    setMensajeUsuarios('')
    try {
      const respuesta = await fetch(
        `/admin/${tipo === 'admin' ? 'administrators' : 'students'}/${cuenta.id}/permanent`,
        {
          method: 'DELETE',
          headers: {
            Authorization: 'Bearer ' + tokenRef.current,
          },
        }
      )
      const resultado = await leerRespuesta(respuesta)
      setMensajeUsuarios(
        resultado.message || `Cuenta de ${nombreTipo} eliminada permanentemente.`
      )
      if (usuarioEnEdicion?.id === cuenta.id) setUsuarioEnEdicion(null)
      await recargarUsuarios()
    } catch (err) {
      if (err.codigo === 401) cerrarSesion()
      setError(err.message)
    }
  }

  async function cambiarEstadoCuenta(tipo, cuenta) {
    const valores = tipo === 'admin'
      ? {
          full_name: cuenta.full_name,
          username: cuenta.username,
          email: cuenta.email,
        }
      : {
          full_name: cuenta.full_name,
          student_id: cuenta.student_id,
          email: cuenta.email,
        }
    const ruta = `/admin/${tipo === 'admin' ? 'administrators' : 'students'}/${cuenta.id}`
    setError('')
    setMensajeUsuarios('')
    try {
      const respuesta = await fetch(ruta, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer ' + tokenRef.current,
        },
        body: JSON.stringify({
          ...valores,
          is_active: !cuenta.is_active,
        }),
      })
      const resultado = await leerRespuesta(respuesta)
      setMensajeUsuarios(resultado.message || 'Estado de la cuenta actualizado.')
      await recargarUsuarios()
    } catch (err) {
      if (err.codigo === 401) cerrarSesion()
      setError(err.message)
    }
  }

  async function generarCodigoInstalacion() {
    setError('')
    setMensajeCodigo('')
    setCodigoInstalacion(null)
    setCopiadoCodigo(false)
    if (codigoTimerRef.current) {
      window.clearTimeout(codigoTimerRef.current)
      codigoTimerRef.current = null
    }
    setGenerandoCodigo(true)

    try {
      const respuesta = await fetch('/computers/enrollment-code', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenRef.current}`,
        },
      })
      const datos = await leerRespuesta(respuesta)
      const codigo = datos.code || datos.enrollment_code
      if (!codigo) {
        throw new Error('El servidor no devolvió un código de instalación.')
      }

      const expiracion = datos.expires_at || datos.expiresAt || null
      const minutos = datos.expires_in_minutes || datos.expiresInMinutes || null
      const segundos = datos.expires_in_seconds || datos.expiresInSeconds || null
      setCodigoInstalacion({ code: codigo, expiresAt: expiracion, expiresInMinutes: minutos, expiresInSeconds: segundos })
      setMensajeCodigo('Código de un solo uso: cópielo y compártalo de forma segura. No volverá a mostrarse después de cerrarlo.')

      const vigenciaMs = segundos
        ? Number(segundos) * 1000
        : minutos
          ? Number(minutos) * 60 * 1000
          : expiracion
            ? new Date(expiracion).getTime() - Date.now()
            : null
      if (Number.isFinite(vigenciaMs)) {
        codigoTimerRef.current = window.setTimeout(() => {
          setCodigoInstalacion(null)
          setCopiadoCodigo(false)
          codigoTimerRef.current = null
        }, Math.max(0, vigenciaMs))
      }
    } catch (err) {
      if (err.codigo === 401) {
        cerrarSesion()
      }
      setError(err.message)
    } finally {
      setGenerandoCodigo(false)
    }
  }

  async function copiarCodigoInstalacion() {
    if (!codigoInstalacion?.code) return
    try {
      await navigator.clipboard.writeText(codigoInstalacion.code)
      setCopiadoCodigo(true)
    } catch {
      setMensajeCodigo('No se pudo copiar automáticamente. Seleccione y copie el código antes de cerrarlo.')
    }
  }

  function ocultarCodigoInstalacion() {
    if (codigoTimerRef.current) {
      window.clearTimeout(codigoTimerRef.current)
      codigoTimerRef.current = null
    }
    setCodigoInstalacion(null)
    setCopiadoCodigo(false)
    setMensajeCodigo('Código cerrado y eliminado de la pantalla. Si no se utilizó, genere uno nuevo.')
  }

  function verComputadora(id) {
    detalleIdRef.current = id
    setDetalleIdActual(id)
    setDetalle(null)
    setError('')

    async function cargarDetalle() {
      const sesionActual = sesionRef.current

      try {
        setCargando(true)

        const datos = await solicitarDatos(
          `/admin/computers/${id}`,
          tokenRef.current
        )

        if (
          sesionActual === sesionRef.current &&
          detalleIdRef.current === id
        ) {
          setDetalle(datos)
        }
      } catch (err) {
        if (
          sesionActual !== sesionRef.current
        ) {
          return
        }

        if (err.codigo === 401) {
          cerrarSesion()
          setError(
            'Tu sesión expiró. Inicia sesión nuevamente.'
          )
        } else {
          setError(err.message)
        }
      } finally {
        if (
          sesionActual === sesionRef.current
        ) {
          setCargando(false)
        }
      }
    }

    cargarDetalle()
  }

  function volverDashboard() {
    detalleIdRef.current = null
    setDetalleIdActual(null)
    setDetalle(null)
    setError('')

    if (tokenRef.current) {
      actualizarDatos(tokenRef.current)
    }
  }

  function seleccionarArea(area) {
    setAreaActiva(area)
    if (detalleIdRef.current !== null) {
      volverDashboard()
    }
  }

  useEffect(() => {
    if (!token) return

    const sesionInicial = sesionRef.current
    let renovando = false
    let ultimaEscrituraActividad = ultimaActividadRef.current

    async function renovarSesion() {
      if (renovando || !tokenRef.current) return
      renovando = true
      try {
        const respuesta = await fetch('/auth/refresh', {
          method: 'POST',
          headers: {
            Authorization: 'Bearer ' + tokenRef.current,
          },
          cache: 'no-store',
        })
        if (respuesta.status === 401) {
          cerrarSesion()
          setError('Tu sesión expiró. Inicia sesión nuevamente.')
          return
        }
        const datos = await leerRespuesta(respuesta)
        if (sesionInicial !== sesionRef.current) return
        tokenRef.current = datos.access_token
        window.sessionStorage.setItem(
          CLAVE_TOKEN_ADMIN,
          datos.access_token
        )
        ultimaRenovacionRef.current = Date.now()
        await actualizarDatos(datos.access_token, true)
      } catch (err) {
        setError(err.message)
      } finally {
        renovando = false
      }
    }

    function registrarActividad() {
      const ahora = Date.now()
      ultimaActividadRef.current = ahora
      if (ahora - ultimaEscrituraActividad >= 5000) {
        ultimaEscrituraActividad = ahora
        window.sessionStorage.setItem(
          CLAVE_ACTIVIDAD_ADMIN,
          String(ahora)
        )
      }
    }

    function revisarInactividad() {
      if (
        Date.now() - ultimaActividadRef.current >=
        TIEMPO_INACTIVIDAD_MS
      ) {
        cerrarSesion()
        setError('La sesión se cerró por 30 minutos de inactividad.')
        return
      }
      if (
        Date.now() - ultimaRenovacionRef.current >=
        INTERVALO_RENOVACION_MS
      ) {
        renovarSesion()
      }
    }

    const eventosActividad = [
      'pointerdown',
      'keydown',
      'mousemove',
      'scroll',
      'touchstart',
    ]
    eventosActividad.forEach((evento) =>
      window.addEventListener(evento, registrarActividad, {
        passive: true,
      })
    )

    const intervalo = setInterval(() => {
      if (!document.hidden) {
        actualizarDatos(tokenRef.current, true)
      }
    }, INTERVALO_ACTUALIZACION)
    const intervaloInactividad = setInterval(
      revisarInactividad,
      1000
    )

    function alVolverVentana() {
      if (!document.hidden) {
        revisarInactividad()
        if (
          Date.now() - ultimaRenovacionRef.current >=
          INTERVALO_RENOVACION_MS
        ) {
          renovarSesion()
        } else {
          actualizarDatos(tokenRef.current, true)
        }
      }
    }

    document.addEventListener(
      'visibilitychange',
      alVolverVentana
    )
    renovarSesion()

    return () => {
      clearInterval(intervalo)
      clearInterval(intervaloInactividad)
      eventosActividad.forEach((evento) =>
        window.removeEventListener(evento, registrarActividad)
      )

      document.removeEventListener(
        'visibilitychange',
        alVolverVentana
      )
    }
  }, [token, actualizarDatos, cerrarSesion])

  // PANTALLAS DE RECUPERACIÓN

  if (
    rutaActual === '/forgot-password' ||
    rutaActual === '/reset-password'
  ) {
    return (
      <RecuperacionPassword
        key={rutaActual}
        volver={() => navegar('/')}
      />
    )
  }

  if (rutaActual === '/register') {
    return (
      <RegistroAlumno
        volver={() => navegar('/')}
      />
    )
  }

  // LOGIN ADMINISTRATIVO

  if (!token) {
    return (
      <main className="login-page">
        <form
          className="login-card"
          onSubmit={iniciarSesion}
        >
          <img
            className="uad-logo login-logo"
            src={logoUad}
            alt="Universidad de Durango, Campus Aguascalientes"
          />

          <h1>LabMonitor</h1>

          <p className="subtitle">
            Sistema de monitoreo de hardware
          </p>

          <div className="form-group">
            <label htmlFor="username">
              Usuario
            </label>

            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) =>
                setUsername(e.target.value)
              }
              placeholder="Usuario administrador"
              autoComplete="username"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">
              Contraseña
            </label>

            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) =>
                setPassword(e.target.value)
              }
              placeholder="Introduce tu contraseña"
              autoComplete="current-password"
              required
            />
          </div>

          {error && (
            <p className="error-message">
              {error}
            </p>
          )}

          <button
            className="primary-button"
            type="submit"
            disabled={cargando}
          >
            {cargando
              ? 'Iniciando sesión...'
              : 'Iniciar sesión'}
          </button>

          <button
            type="button"
            className="back-button"
            onClick={() =>
              navegar('/forgot-password')
            }
            style={{ marginTop: '1rem' }}
          >
            ¿Olvidaste tu contraseña?
          </button>

          <button
            type="button"
            className="back-button"
            onClick={() => navegar('/register')}
            style={{ marginTop: '1rem' }}
          >
            Crear cuenta de estudiante
          </button>

          <p className="login-footer">
            Acceso exclusivo para personal autorizado
          </p>
        </form>
      </main>
    )
  }

  // DASHBOARD ADMINISTRATIVO

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <img
            className="uad-logo sidebar-logo"
            src={logoUad}
            alt="Universidad de Durango, Campus Aguascalientes"
          />
        </div>

        <div className="sidebar-section">
          <span className="sidebar-label">
            ADMINISTRACIÓN
          </span>

          <nav className="sidebar-navigation" aria-label="Áreas del dashboard">
            {AREAS_DASHBOARD.map((area) => (
              <button
                key={area.id}
                className={`sidebar-link ${
                  areaActiva === area.id ? 'active' : ''
                }`}
                aria-current={areaActiva === area.id ? 'page' : undefined}
                onClick={() => seleccionarArea(area.id)}
              >
                {area.label}
              </button>
            ))}
          </nav>
        </div>

        <div className="sidebar-bottom">
          <span>
            {usuario?.full_name ||
              usuario?.username}
          </span>

          <button onClick={cerrarSesion}>
            Cerrar sesión
          </button>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <h1>
              {detalleIdActual !== null
                ? 'Detalle de computadora'
                : AREAS_DASHBOARD.find(
                    (area) => area.id === areaActiva
                  )?.label || 'Resumen'}
            </h1>

            <p>
              Universidad de Durango · Campus Aguascalientes
            </p>

            <div className="live-status">
              <span className="live-dot" />

              <span>
                Actualización automática cada 5 segundos
              </span>

              {ultimaActualizacion && (
                <span className="last-update">
                  Última consulta:{' '}
                  {ultimaActualizacion.toLocaleTimeString(
                    'es-MX',
                    {
                      timeZone:
                        'America/Mexico_City',
                    }
                  )}
                </span>
              )}

              {actualizando && (
                <span className="last-update">
                  Actualizando...
                </span>
              )}
            </div>
          </div>

          <span className="admin-badge">
            Administrador
          </span>
        </header>

        {error && (
          <p className="error-message">
            {error}
          </p>
        )}

        {detalleIdActual !== null ? (
          <section>
            <button
              className="back-button"
              onClick={volverDashboard}
            >
              ← Volver al dashboard
            </button>

            {!detalle ? (
              <div className="panel">
                <p>
                  Cargando información de la computadora...
                </p>
              </div>
            ) : (
              <>
                <div className="panel">
                  <h2>
                    {detalle.computer.hostname}
                  </h2>

                  <p>
                    {detalle.computer
                      .operating_system ||
                      'Sistema desconocido'}
                  </p>

                  <p>
                    Laboratorio:{' '}
                    {detalle.computer.lab ||
                      'Sin asignar'}
                  </p>
                </div>

                <div className="panel">
                  <h2>
                    Componentes de hardware
                  </h2>

                  <div className="table-container">
                    <table>
                      <thead>
                        <tr>
                          <th>Tipo</th>
                          <th>Fabricante</th>
                          <th>Modelo</th>
                          <th>Estado</th>
                        </tr>
                      </thead>

                      <tbody>
                        {detalle.hardware.map(
                          (componente) => (
                            <tr
                              key={componente.id}
                            >
                              <td>
                                {traducirTipoComponente(
                                  componente.component_type
                                )}
                              </td>

                              <td>
                                {componente.manufacturer ||
                                  'N/D'}
                              </td>

                              <td>
                                {componente.model ||
                                  'N/D'}
                              </td>

                              <td>
                                <span
                                  className={
                                    componente.status ===
                                    'active'
                                      ? 'status-active'
                                      : 'status-inactive'
                                  }
                                >
                                  {traducirEstado(
                                    componente.status
                                  )}
                                </span>
                              </td>
                            </tr>
                          )
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="panel">
                  <h2>
                    Eventos recientes
                  </h2>

                  <div className="table-container">
                    <table>
                      <thead>
                        <tr>
                          <th>Evento</th>
                          <th>Componente</th>
                          <th>Fecha y hora</th>
                        </tr>
                      </thead>

                      <tbody>
                        {detalle.recent_events.map(
                          (evento) => (
                            <tr key={evento.id}>
                              <td>
                                {traducirEvento(
                                  evento.event_type
                                )}
                              </td>

                              <td>
                                {evento.component_type ||
                                  'Sistema'}
                              </td>

                              <td>
                                {formatearFecha(
                                  evento.detected_at
                                )}
                              </td>
                            </tr>
                          )
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}
          </section>
        ) : (
          <>
            {areaActiva === 'resumen' && (
              <section className="stats-grid">
              <div className="stat-card">
                <span>
                  Computadoras
                </span>

                <strong>
                  {estadisticas?.computers ??
                    0}
                </strong>
              </div>

              <div className="stat-card">
                <span>
                  Componentes activos
                </span>

                <strong>
                  {estadisticas
                    ?.active_components ?? 0}
                </strong>
              </div>

              <div className="stat-card">
                <span>
                  Eventos de hardware
                </span>

                <strong>
                  {estadisticas
                    ?.hardware_events ?? 0}
                </strong>
              </div>

              <div className="stat-card">
                <span>
                  Estudiantes
                </span>

                <strong>
                  {estadisticas?.students ??
                    0}
                </strong>
              </div>
              </section>
            )}

            {areaActiva === 'computadoras' && (
              <section className="panel">
              <h2>
                Computadoras registradas
              </h2>

              <p className="section-description">
                Inventario de los equipos registrados en LabMonitor
              </p>

              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>
                        Computadora
                      </th>
                      <th>
                        Laboratorio
                      </th>
                      <th>
                        Componentes
                      </th>
                      <th>
                        Eventos
                      </th>
                      <th>
                        Acciones
                      </th>
                    </tr>
                  </thead>

                  <tbody>
                    {computadoras.map(
                      (equipo) => (
                        <tr key={equipo.id}>
                          <td>
                            <strong>
                              {equipo.hostname}
                            </strong>

                            <small>
                              {
                                equipo.operating_system
                              }
                            </small>
                          </td>

                          <td>
                            {equipo.lab ||
                              'Sin asignar'}
                          </td>

                          <td>
                            {
                              equipo.active_components
                            }
                          </td>

                          <td>
                            {
                              equipo.total_events
                            }
                          </td>

                          <td>
                            <button
                              className="table-button"
                              onClick={() =>
                                verComputadora(
                                  equipo.id
                                )
                              }
                              disabled={cargando}
                            >
                              Ver detalles
                            </button>
                          </td>
                        </tr>
                      )
                    )}

                    {computadoras.length ===
                      0 && (
                      <tr>
                        <td colSpan="5">
                          No hay computadoras registradas.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              </section>
            )}

            {areaActiva === 'administradores' && (
              <>
              {mensajeUsuarios && <p role="status" className="success-message">{mensajeUsuarios}</p>}
              <section className="panel">
              <h2>Administradores</h2>
              <p className="section-description">
                Los administradores activos con correo registrado reciben automáticamente las alertas de hardware.
              </p>
              <form onSubmit={crearAdministrador}>
                <div className="form-group">
                  <label htmlFor="admin-full-name">Nombre completo</label>
                  <input id="admin-full-name" value={nombreAdministrador} onChange={(evento) => setNombreAdministrador(evento.target.value)} required maxLength={150} autoComplete="name" />
                </div>
                <div className="form-group">
                  <label htmlFor="admin-username">Usuario</label>
                  <input id="admin-username" value={usuarioAdministrador} onChange={(evento) => setUsuarioAdministrador(evento.target.value)} required maxLength={50} autoComplete="username" />
                </div>
                <div className="form-group">
                  <label htmlFor="admin-email">Correo Gmail</label>
                  <input id="admin-email" type="email" value={correoAdministrador} onChange={(evento) => setCorreoAdministrador(evento.target.value)} required maxLength={254} autoComplete="email" />
                </div>
                <div className="form-group">
                  <label htmlFor="admin-password">Contraseña (mínimo 8 caracteres)</label>
                  <input id="admin-password" type="password" value={passwordAdministrador} onChange={(evento) => setPasswordAdministrador(evento.target.value)} required minLength={8} maxLength={128} autoComplete="new-password" />
                </div>
                <button className="primary-button" type="submit" disabled={creandoAdministrador}>
                  {creandoAdministrador ? 'Creando administrador…' : 'Crear administrador'}
                </button>
              </form>
              {mensajeAdministrador && <p role="status">{mensajeAdministrador}</p>}
              <div className="table-container">
                <table>
                  <thead><tr><th>Nombre</th><th>Usuario</th><th>Correo de alertas</th><th>Estado</th><th>Acciones</th></tr></thead>
                  <tbody>
                    {administradores.map((admin) => (
                      <tr key={admin.id}>
                        <td>{admin.full_name}</td>
                        <td>{admin.username}</td>
                        <td>{admin.email || 'Sin correo'}</td>
                        <td>{admin.is_active ? 'Activo' : 'Inactivo'}</td>
                        <td>
                          <button className="table-button" type="button" onClick={() => editarCuenta('admin', admin)}>Editar</button>{' '}
                          {admin.is_active ? (
                            <button className="table-button" type="button" onClick={() => desactivarCuenta('admin', admin)} disabled={admin.id === usuario?.id}>Desactivar</button>
                          ) : (
                            <button className="table-button" type="button" onClick={() => cambiarEstadoCuenta('admin', admin)}>Reactivar</button>
                          )}
                          <button className="table-button" type="button" onClick={() => eliminarCuentaPermanentemente('admin', admin)} disabled={admin.id === usuario?.id}>Eliminar permanentemente</button>
                        </td>
                      </tr>
                    ))}
                    {administradores.length === 0 && <tr><td colSpan="5">No hay administradores registrados.</td></tr>}
                  </tbody>
                </table>
              </div>
              {usuarioEnEdicion?.tipo === 'admin' && (
                <form className="account-edit-form" onSubmit={guardarEdicionUsuario}>
                  <h3>Editar administrador</h3>
                  <div className="form-group">
                    <label htmlFor="edit-admin-name">Nombre completo</label>
                    <input id="edit-admin-name" value={usuarioEnEdicion.full_name} onChange={(evento) => setUsuarioEnEdicion({ ...usuarioEnEdicion, full_name: evento.target.value })} required maxLength={150} />
                  </div>
                  <div className="form-group">
                    <label htmlFor="edit-admin-username">Usuario</label>
                    <input id="edit-admin-username" value={usuarioEnEdicion.username} onChange={(evento) => setUsuarioEnEdicion({ ...usuarioEnEdicion, username: evento.target.value })} required maxLength={50} />
                  </div>
                  <div className="form-group">
                    <label htmlFor="edit-admin-email">Correo de alertas</label>
                    <input id="edit-admin-email" type="email" value={usuarioEnEdicion.email} onChange={(evento) => setUsuarioEnEdicion({ ...usuarioEnEdicion, email: evento.target.value })} required maxLength={254} />
                  </div>
                  <div className="form-group">
                    <label htmlFor="edit-admin-password">Nueva contraseña (opcional)</label>
                    <input id="edit-admin-password" type="password" value={usuarioEnEdicion.password} onChange={(evento) => setUsuarioEnEdicion({ ...usuarioEnEdicion, password: evento.target.value })} minLength={8} maxLength={128} autoComplete="new-password" />
                  </div>
                  <label className="account-active-control">
                    <input type="checkbox" checked={usuarioEnEdicion.is_active} onChange={(evento) => setUsuarioEnEdicion({ ...usuarioEnEdicion, is_active: evento.target.checked })} />
                    Cuenta activa
                  </label>
                  <button className="primary-button" type="submit" disabled={guardandoUsuario}>{guardandoUsuario ? 'Guardando…' : 'Guardar cambios'}</button>{' '}
                  <button className="table-button" type="button" onClick={() => setUsuarioEnEdicion(null)}>Cancelar</button>
                </form>
              )}
              </section>
              </>
            )}

            {areaActiva === 'estudiantes' && (
              <>
              {mensajeUsuarios && <p role="status" className="success-message">{mensajeUsuarios}</p>}
              <section className="panel">
              <h2>Estudiantes</h2>
              <p className="section-description">
                Las cuentas nuevas deben verificar su correo con el código de seguridad antes de iniciar sesión en LabMonitor. Desactivar conserva la cuenta; eliminar permanentemente borra sus datos de acceso y conserva el historial anonimizado.
              </p>
              <form className="account-edit-form" onSubmit={crearEstudiante}>
                <h3>Dar de alta estudiante</h3>
                <div className="form-group">
                  <label htmlFor="new-student-name">Nombre completo</label>
                  <input id="new-student-name" value={nombreEstudiante} onChange={(evento) => setNombreEstudiante(evento.target.value)} required maxLength={150} />
                </div>
                <div className="form-group">
                  <label htmlFor="new-student-id">Matrícula (10 dígitos)</label>
                  <input id="new-student-id" value={matriculaEstudiante} onChange={(evento) => setMatriculaEstudiante(evento.target.value)} required minLength={10} maxLength={10} inputMode="numeric" pattern="[0-9]{10}" />
                </div>
                <div className="form-group">
                  <label htmlFor="new-student-email">Correo electrónico</label>
                  <input id="new-student-email" type="email" value={correoEstudiante} onChange={(evento) => setCorreoEstudiante(evento.target.value)} required maxLength={254} />
                </div>
                <div className="form-group">
                  <label htmlFor="new-student-password">Contraseña temporal (mínimo 8 caracteres)</label>
                  <input id="new-student-password" type="password" value={passwordEstudiante} onChange={(evento) => setPasswordEstudiante(evento.target.value)} required minLength={8} maxLength={128} autoComplete="new-password" />
                </div>
                <button className="primary-button" type="submit" disabled={creandoEstudiante}>
                  {creandoEstudiante ? 'Creando cuenta…' : 'Crear cuenta y enviar código'}
                </button>
              </form>
              <p className="section-description">
                Enlace general para compartir con estudiantes:{' '}
                <a
                  href={`${window.location.origin}/register`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {`${window.location.origin}/register`}
                </a>
              </p>
              <div className="table-container">
                <table>
                  <thead><tr><th>Nombre</th><th>Matrícula</th><th>Correo</th><th>Verificación</th><th>Estado</th><th>Acciones</th></tr></thead>
                  <tbody>
                    {estudiantes.map((estudiante) => (
                      <tr key={estudiante.id}>
                        <td>{estudiante.full_name}</td>
                        <td>{estudiante.student_id || estudiante.username}</td>
                        <td>{estudiante.email || 'Sin correo'}</td>
                        <td>{estudiante.email_verified ? 'Verificado' : 'Pendiente'}</td>
                        <td>{estudiante.is_active ? 'Activo' : 'Inactivo'}</td>
                        <td>
                          <button className="table-button" type="button" onClick={() => editarCuenta('student', estudiante)}>Editar</button>{' '}
                          {estudiante.is_active ? (
                            <button className="table-button" type="button" onClick={() => desactivarCuenta('student', estudiante)}>Desactivar</button>
                          ) : (
                            <button className="table-button" type="button" onClick={() => cambiarEstadoCuenta('student', estudiante)}>Reactivar</button>
                          )}
                          <button className="table-button" type="button" onClick={() => eliminarCuentaPermanentemente('student', estudiante)}>Eliminar permanentemente</button>
                        </td>
                      </tr>
                    ))}
                    {estudiantes.length === 0 && <tr><td colSpan="6">No hay estudiantes registrados.</td></tr>}
                  </tbody>
                </table>
              </div>
              {usuarioEnEdicion?.tipo === 'student' && (
                <form className="account-edit-form" onSubmit={guardarEdicionUsuario}>
                  <h3>Editar estudiante</h3>
                  <div className="form-group">
                    <label htmlFor="edit-student-name">Nombre completo</label>
                    <input id="edit-student-name" value={usuarioEnEdicion.full_name} onChange={(evento) => setUsuarioEnEdicion({ ...usuarioEnEdicion, full_name: evento.target.value })} required maxLength={150} />
                  </div>
                  <div className="form-group">
                    <label htmlFor="edit-student-id">Matrícula</label>
                    <input id="edit-student-id" value={usuarioEnEdicion.student_id} onChange={(evento) => setUsuarioEnEdicion({ ...usuarioEnEdicion, student_id: evento.target.value })} required minLength={10} maxLength={10} inputMode="numeric" />
                  </div>
                  <div className="form-group">
                    <label htmlFor="edit-student-email">Correo</label>
                    <input id="edit-student-email" type="email" value={usuarioEnEdicion.email} onChange={(evento) => setUsuarioEnEdicion({ ...usuarioEnEdicion, email: evento.target.value })} required maxLength={254} />
                  </div>
                  <div className="form-group">
                    <label htmlFor="edit-student-password">Nueva contraseña (opcional)</label>
                    <input id="edit-student-password" type="password" value={usuarioEnEdicion.password} onChange={(evento) => setUsuarioEnEdicion({ ...usuarioEnEdicion, password: evento.target.value })} minLength={8} maxLength={128} autoComplete="new-password" />
                  </div>
                  <label className="account-active-control">
                    <input type="checkbox" checked={usuarioEnEdicion.is_active} onChange={(evento) => setUsuarioEnEdicion({ ...usuarioEnEdicion, is_active: evento.target.checked })} />
                    Cuenta activa
                  </label>
                  <button className="primary-button" type="submit" disabled={guardandoUsuario}>{guardandoUsuario ? 'Guardando…' : 'Guardar cambios'}</button>{' '}
                  <button className="table-button" type="button" onClick={() => setUsuarioEnEdicion(null)}>Cancelar</button>
                </form>
              )}
              </section>
              </>
            )}

            {areaActiva === 'instalacion' && (
              <section className="panel">
              <h2>Código de instalación de equipos</h2>
              <p className="section-description">
                Genere un código de un solo uso para inscribir un equipo. Compártalo solo con personal autorizado; el servidor lo invalida según su vigencia.
              </p>
              <button className="primary-button" type="button" onClick={generarCodigoInstalacion} disabled={generandoCodigo}>
                {generandoCodigo ? 'Generando código…' : 'Generar código de instalación'}
              </button>
              {codigoInstalacion && (
                <div role="status" aria-live="polite">
                  <p><strong>{mensajeCodigo}</strong></p>
                  <p className="enrollment-code-value">{codigoInstalacion.code}</p>
                  {codigoInstalacion.expiresAt && <p>Expira: {formatearFecha(codigoInstalacion.expiresAt)}</p>}
                  {!codigoInstalacion.expiresAt && codigoInstalacion.expiresInMinutes && <p>Vigencia: {codigoInstalacion.expiresInMinutes} minutos.</p>}
                  {!codigoInstalacion.expiresAt && !codigoInstalacion.expiresInMinutes && codigoInstalacion.expiresInSeconds && <p>Vigencia: {Math.ceil(codigoInstalacion.expiresInSeconds / 60)} minutos.</p>}
                  <button className="table-button" type="button" onClick={copiarCodigoInstalacion}>{copiadoCodigo ? 'Copiado' : 'Copiar código'}</button>{' '}
                  <button className="table-button" type="button" onClick={ocultarCodigoInstalacion}>Cerrar y ocultar</button>
                </div>
              )}
              {!codigoInstalacion && mensajeCodigo && <p role="status">{mensajeCodigo}</p>}
              </section>
            )}

            {areaActiva === 'alertas' && (
              <>
              <section
              className={`mail-status-panel ${
                estadoCorreo?.ready &&
                estadoCorreo?.worker_running
                  ? 'mail-status-ready'
                  : 'mail-status-warning'
              }`}
            >
              <div>
                <h2>Alertas de hardware por correo</h2>
                <p>
                  SMTP:{' '}
                  {estadoCorreo?.smtp_configured
                    ? 'configurado'
                    : 'incompleto'}
                  {' · Destinatarios: '}
                  {estadoCorreo?.recipient_count ?? 0}
                  {' · Worker: '}
                  {estadoCorreo?.worker_running
                    ? 'activo'
                    : 'detenido'}
                </p>
              </div>
              <strong>
                {estadoCorreo?.ready &&
                estadoCorreo?.worker_running
                  ? 'Envío habilitado'
                  : 'Revisar configuración de correo'}
              </strong>
              </section>

              <section className="panel">
              <h2>Eventos recientes de hardware</h2>
              <p className="section-description">
                Cambios detectados en todos los equipos y estado
                de entrega de cada alerta por correo.
              </p>

              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Fecha</th>
                      <th>Computadora</th>
                      <th>Evento</th>
                      <th>Componente</th>
                      <th>Cambio</th>
                      <th>Correo</th>
                    </tr>
                  </thead>

                  <tbody>
                    {eventosHardware.map((evento) => (
                      <tr key={evento.id}>
                        <td>
                          {formatearFecha(evento.detected_at)}
                        </td>
                        <td>
                          <strong>{evento.hostname}</strong>
                          <small>{evento.lab || 'Sin laboratorio'}</small>
                        </td>
                        <td>{traducirEvento(evento.event_type)}</td>
                        <td>
                          {traducirTipoComponente(
                            evento.component_type
                          )}
                          <small>
                            {evento.model ||
                              evento.hardware_identifier ||
                              'N/D'}
                          </small>
                        </td>
                        <td className="hardware-change">
                          {evento.previous_value || 'N/D'}
                          {' -> '}
                          {evento.new_value || 'N/D'}
                        </td>
                        <td>
                          <span
                            className={`mail-badge mail-${evento.email_status}`}
                          >
                            {traducirEstadoCorreo(evento.email_status)}
                          </span>
                          {evento.email_status === 'sent' && (
                            <small>
                              {evento.sent_notifications ?? 0} enviado(s)
                            </small>
                          )}
                          {evento.email_status === 'pending' && (
                            <small>
                              {evento.pending_notifications ?? 0} pendiente(s)
                            </small>
                          )}
                          {evento.email_status === 'failed' && (
                            <small>
                              {evento.failed_notifications ?? 0} con error
                            </small>
                          )}
                        </td>
                      </tr>
                    ))}

                    {eventosHardware.length === 0 && (
                      <tr>
                        <td colSpan="6">
                          Todavía no hay eventos de hardware registrados.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              </section>
              </>
            )}
          </>
        )}
      </main>
    </div>
  )
}

export default App
