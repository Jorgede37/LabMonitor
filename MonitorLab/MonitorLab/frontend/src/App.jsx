
import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'

const INTERVALO_ACTUALIZACION = 5000

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

function traducirEstado(estado) {
  if (estado === 'active') return 'Activo'
  if (estado === 'removed') return 'Desconectado'
  return estado || 'Desconocido'
}

async function leerRespuesta(respuesta) {
  const datos = await respuesta.json()

  if (!respuesta.ok) {
    throw new Error(
      typeof datos.detail === 'string'
        ? datos.detail
        : 'No fue posible completar la solicitud.'
    )
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
        <div className="brand-icon">LM</div>

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

function App() {
  const [rutaActual, setRutaActual] = useState(
    window.location.pathname
  )

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const [token, setToken] = useState(null)
  const [usuario, setUsuario] = useState(null)

  const [estadisticas, setEstadisticas] = useState(null)
  const [computadoras, setComputadoras] = useState([])
  const [detalle, setDetalle] = useState(null)

  const [cargando, setCargando] = useState(false)
  const [actualizando, setActualizando] = useState(false)
  const [error, setError] = useState('')
  const [ultimaActualizacion, setUltimaActualizacion] =
    useState(null)

  const tokenRef = useRef(null)
  const detalleIdRef = useRef(null)
  const actualizandoRef = useRef(false)
  const sesionRef = useRef(0)

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
    detalleIdRef.current = null
    actualizandoRef.current = false

    setToken(null)
    setUsuario(null)
    setEstadisticas(null)
    setComputadoras([])
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

        if (
          idDetalle !== null &&
          detalleIdRef.current === idDetalle
        ) {
          setDetalle(resultados[2])
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
      detalleIdRef.current = null

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

  function verComputadora(id) {
    detalleIdRef.current = id
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
    setDetalle(null)
    setError('')

    if (tokenRef.current) {
      actualizarDatos(tokenRef.current)
    }
  }

  useEffect(() => {
    if (!token) return

    const intervalo = setInterval(() => {
      if (!document.hidden) {
        actualizarDatos(token, true)
      }
    }, INTERVALO_ACTUALIZACION)

    function alVolverVentana() {
      if (!document.hidden) {
        actualizarDatos(token, true)
      }
    }

    document.addEventListener(
      'visibilitychange',
      alVolverVentana
    )

    return () => {
      clearInterval(intervalo)

      document.removeEventListener(
        'visibilitychange',
        alVolverVentana
      )
    }
  }, [token, actualizarDatos])

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

  // LOGIN ADMINISTRATIVO

  if (!token) {
    return (
      <main className="login-page">
        <form
          className="login-card"
          onSubmit={iniciarSesion}
        >
          <div className="brand-icon">LM</div>

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
          <div className="brand-icon small">
            LM
          </div>

          <span>LabMonitor</span>
        </div>

        <div className="sidebar-section">
          <span className="sidebar-label">
            ADMINISTRACIÓN
          </span>

          <button
            className="sidebar-link active"
            onClick={volverDashboard}
          >
            Dashboard
          </button>
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
              {detalleIdRef.current !== null
                ? 'Detalle de computadora'
                : 'Dashboard'}
            </h1>

            <p>
              Panel de administración de LabMonitor
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

        {detalleIdRef.current !== null ? (
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
                                {
                                  componente.component_type
                                }
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
          </>
        )}
      </main>
    </div>
  )
}

export default App
