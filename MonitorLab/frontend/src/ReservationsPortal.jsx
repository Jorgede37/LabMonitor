import { useCallback, useEffect, useRef, useState } from 'react'
import logoUad from './assets/uad_logo.png'

const TOKEN_DOCENTE = 'labmonitor.teacher.token'
const ACTIVIDAD_DOCENTE = 'labmonitor.teacher.lastActivity'
const INACTIVIDAD_MAXIMA = 30 * 60 * 1000
const RENOVAR_CADA = 5 * 60 * 1000
const HORARIOS_ESTANDAR = Array.from({ length: 9 }, (_, indice) => {
  const inicio = String(indice + 7).padStart(2, '0')
  const fin = String(indice + 8).padStart(2, '0')
  return {
    start_time: `${inicio}:00`,
    end_time: `${fin}:00`,
    available: true,
  }
})

async function leerJson(respuesta) {
  const texto = await respuesta.text()
  let datos = {}
  if (texto) {
    try {
      datos = JSON.parse(texto)
    } catch {
      datos = { detail: texto }
    }
  }
  if (!respuesta.ok) {
    const error = new Error(datos.detail || `Error HTTP ${respuesta.status}`)
    error.status = respuesta.status
    throw error
  }
  return datos
}

function fechaLocalISO(fecha = new Date()) {
  const partes = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Mexico_City',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(fecha)
  const valores = Object.fromEntries(partes.map(({ type, value }) => [type, value]))
  return `${valores.year}-${valores.month}-${valores.day}`
}

function textoFecha(valor) {
  if (!valor) return 'N/D'
  const [year, month, day] = valor.split('-').map(Number)
  return new Intl.DateTimeFormat('es-MX', {
    dateStyle: 'medium',
    timeZone: 'America/Mexico_City',
  }).format(new Date(Date.UTC(year, month - 1, day, 12)))
}

function intervaloDisponible(slots, inicio, duracion) {
  const horaInicio = Number(inicio.slice(0, 2))
  return Array.from({ length: duracion }, (_, indice) => {
    const hora = String(horaInicio + indice).padStart(2, '0') + ':00'
    return slots.find((slot) => slot.start_time === hora)?.available === true
  }).every(Boolean)
}

function duracionMaxima(slots, inicio) {
  const horaInicio = Number(inicio.slice(0, 2))
  let duracion = 0
  for (let hora = horaInicio; hora < 16; hora += 1) {
    const horaTexto = String(hora).padStart(2, '0') + ':00'
    if (slots.find((slot) => slot.start_time === horaTexto)?.available !== true) break
    duracion += 1
  }
  return duracion
}

function sumarHoras(hora, duracion) {
  return `${String(Number(hora.slice(0, 2)) + duracion).padStart(2, '0')}:00`
}

function coincideTexto(termino, ...valores) {
  const consulta = termino.trim().toLocaleLowerCase('es-MX')
  return !consulta || valores.some((valor) => (
    String(valor ?? '').toLocaleLowerCase('es-MX').includes(consulta)
  ))
}

export default function ReservationsPortal() {
  const [token, setToken] = useState(
    () => window.sessionStorage.getItem(TOKEN_DOCENTE)
  )
  const tokenRef = useRef(token)
  const lastActivityRef = useRef(0)
  const lastRefreshRef = useRef(0)
  const [modo, setModo] = useState(
    window.location.pathname === '/docentes/registro' ? 'registro' : 'login'
  )
  const [matricula, setMatricula] = useState('')
  const [nombre, setNombre] = useState('')
  const [password, setPassword] = useState('')
  const [fechaReserva, setFechaReserva] = useState(fechaLocalISO())
  const [laboratorios, setLaboratorios] = useState([])
  const [laboratoryId, setLaboratoryId] = useState('')
  const [materia, setMateria] = useState('')
  const [horarios, setHorarios] = useState([])
  const [horario, setHorario] = useState('')
  const [duracion, setDuracion] = useState(1)
  const [reservaEnEdicion, setReservaEnEdicion] = useState(null)
  const [reservas, setReservas] = useState([])
  const [offsetPropio, setOffsetPropio] = useState(0)
  const [hayMasPropias, setHayMasPropias] = useState(false)
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [error, setError] = useState('')
  const [mensaje, setMensaje] = useState('')
  const [cargando, setCargando] = useState(false)

  const cerrarSesion = useCallback(() => {
    tokenRef.current = null
    window.sessionStorage.removeItem(TOKEN_DOCENTE)
    window.sessionStorage.removeItem(ACTIVIDAD_DOCENTE)
    setToken(null)
    setReservas([])
    setHorarios([])
    setMateria('')
    setHorario('')
    setDuracion(1)
    setReservaEnEdicion(null)
  }, [])

  const cargarReservas = useCallback(async (
    fechaInicio = '',
    fechaFin = '',
    offset = 0
  ) => {
    if (!tokenRef.current) return
    const filtros = new URLSearchParams({
      limit: '100',
      offset: String(offset),
    })
    if (fechaInicio) filtros.set('from', fechaInicio)
    if (fechaFin) filtros.set('to', fechaFin)
    const respuesta = await fetch(`/reservations?${filtros}`, {
      headers: { Authorization: `Bearer ${tokenRef.current}` },
      cache: 'no-store',
    })
    const datos = await leerJson(respuesta)
    if (!Array.isArray(datos.reservations)) {
      throw new Error('El servidor respondió con un historial de reservas inválido.')
    }
    setReservas(datos.reservations)
    setOffsetPropio(offset)
    setHayMasPropias(datos.reservations.length === 100)
  }, [])

  useEffect(() => {
    if (!token) return undefined
    lastActivityRef.current =
      Number(window.sessionStorage.getItem(ACTIVIDAD_DOCENTE)) || Date.now()
    lastRefreshRef.current = Date.now()
    let renewing = false
    let lastPersistedActivity = lastActivityRef.current

    async function renovarSesion() {
      if (renewing || !tokenRef.current) return
      renewing = true
      try {
        const respuesta = await fetch('/auth/refresh', {
          method: 'POST',
          headers: { Authorization: `Bearer ${tokenRef.current}` },
          cache: 'no-store',
        })
        const datos = await leerJson(respuesta)
        tokenRef.current = datos.access_token
        window.sessionStorage.setItem(TOKEN_DOCENTE, datos.access_token)
        lastRefreshRef.current = Date.now()
      } catch {
        cerrarSesion()
        setError('Tu sesión terminó. Inicia sesión nuevamente.')
      } finally {
        renewing = false
      }
    }

    function registrarActividad() {
      lastActivityRef.current = Date.now()
      if (lastActivityRef.current - lastPersistedActivity >= 5000) {
        lastPersistedActivity = lastActivityRef.current
        window.sessionStorage.setItem(
          ACTIVIDAD_DOCENTE,
          String(lastActivityRef.current)
        )
      }
    }

    function revisarSesion() {
      if (Date.now() - lastActivityRef.current >= INACTIVIDAD_MAXIMA) {
        cerrarSesion()
        setError('La sesión se cerró por 30 minutos de inactividad.')
      } else if (Date.now() - lastRefreshRef.current >= RENOVAR_CADA) {
        renovarSesion()
      }
    }

    const eventos = ['pointerdown', 'keydown', 'mousemove', 'scroll', 'touchstart']
    eventos.forEach((evento) => window.addEventListener(evento, registrarActividad, { passive: true }))
    const intervalo = window.setInterval(revisarSesion, 1000)
    renovarSesion()

    return () => {
      window.clearInterval(intervalo)
      eventos.forEach((evento) => window.removeEventListener(evento, registrarActividad))
    }
  }, [token, cerrarSesion])

  useEffect(() => {
    if (!token || !fechaReserva || !laboratoryId) return undefined
    let vigente = true
    async function cargarDisponibilidad() {
      setError('')
      try {
        const parametros = new URLSearchParams({
          date: fechaReserva,
          laboratory_id: laboratoryId,
        })
        if (reservaEnEdicion !== null) {
          parametros.set('exclude_id', String(reservaEnEdicion))
        }
        const respuesta = await fetch(
          `/reservations/availability?${parametros}`,
          {
            headers: { Authorization: `Bearer ${tokenRef.current}` },
            cache: 'no-store',
          }
        )
        const datos = await leerJson(respuesta)
        if (!vigente) return
        if (!Array.isArray(datos.slots)) {
          throw new Error('El servidor respondió con horarios inválidos. Actualiza la página e inténtalo de nuevo.')
        }
        const slots = datos.slots
        setHorarios(slots)
        setHorario((actual) => (
          slots.some((slot) => (
            slot.start_time === actual &&
            intervaloDisponible(slots, actual, duracion)
          ))
            ? actual
            : slots.find((slot) => (
              intervaloDisponible(slots, slot.start_time, duracion)
            ))?.start_time || ''
        ))
      } catch (err) {
        if (vigente) {
          setError(err.message)
          if (err.status === 401 || err.status === 403) cerrarSesion()
        }
      }
    }
    cargarDisponibilidad()
    return () => { vigente = false }
  }, [token, fechaReserva, laboratoryId, duracion, reservaEnEdicion, cerrarSesion])

  useEffect(() => {
    if (!token) return undefined
    let vigente = true
    async function cargarLaboratorios() {
      try {
        const respuesta = await fetch('/reservations/laboratories', {
          headers: { Authorization: `Bearer ${tokenRef.current}` },
          cache: 'no-store',
        })
        const datos = await leerJson(respuesta)
        if (!Array.isArray(datos.laboratories)) {
          throw new Error('El servidor respondió con laboratorios inválidos.')
        }
        if (!vigente) return
        setLaboratorios(datos.laboratories)
        setLaboratoryId((actual) => (
          datos.laboratories.some((laboratorio) => String(laboratorio.id) === actual)
            ? actual
            : String(datos.laboratories[0]?.id || '')
        ))
      } catch (err) {
        if (!vigente) return
        setError(err.message)
        if (err.status === 401 || err.status === 403) cerrarSesion()
      }
    }
    cargarLaboratorios()
    return () => { vigente = false }
  }, [token, cerrarSesion])

  useEffect(() => {
    if (!token) return
    cargarReservas().catch((err) => {
      setError(err.message)
      if (err.status === 401 || err.status === 403) cerrarSesion()
    })
  }, [token, cargarReservas, cerrarSesion])

  async function iniciarSesion(evento) {
    evento.preventDefault()
    setError('')
    setMensaje('')
    setCargando(true)
    try {
      const respuesta = await fetch('/auth/teacher-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: matricula.trim(), password }),
      })
      const datos = await leerJson(respuesta)
      if (datos.user.role !== 'teacher') {
        throw new Error('Este acceso es exclusivo para docentes.')
      }
      tokenRef.current = datos.access_token
      window.sessionStorage.setItem(TOKEN_DOCENTE, datos.access_token)
      lastActivityRef.current = Date.now()
      lastRefreshRef.current = Date.now()
      window.sessionStorage.setItem(ACTIVIDAD_DOCENTE, String(lastActivityRef.current))
      setToken(datos.access_token)
      setPassword('')
    } catch (err) {
      setError(err.message)
    } finally {
      setCargando(false)
    }
  }

  async function registrarDocente(evento) {
    evento.preventDefault()
    setError('')
    setMensaje('')
    setCargando(true)
    try {
      const respuesta = await fetch('/users/teachers/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          matricula: matricula.trim(),
          full_name: nombre.trim(),
          password,
        }),
      })
      const datos = await leerJson(respuesta)
      setMensaje(datos.message)
      setModo('login')
      setNombre('')
      setPassword('')
    } catch (err) {
      setError(err.message)
    } finally {
      setCargando(false)
    }
  }

  async function reservar(evento) {
    evento.preventDefault()
    setError('')
    setMensaje('')
    setCargando(true)
    try {
      const editando = reservaEnEdicion !== null
      const respuesta = await fetch(
        editando ? `/reservations/${reservaEnEdicion}` : '/reservations',
        {
        method: editando ? 'PUT' : 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokenRef.current}`,
        },
        body: JSON.stringify({
          laboratory_id: Number(laboratoryId),
          reservation_date: fechaReserva,
          start_time: horario,
          end_time: sumarHoras(horario, duracion),
          subject: materia.trim(),
        }),
        }
      )
      const datos = await leerJson(respuesta)
      setMensaje(datos.message)
      setMateria('')
      setReservaEnEdicion(null)
      await Promise.all([
        cargarReservas(desde, hasta, offsetPropio),
        fetch(`/reservations/availability?date=${encodeURIComponent(fechaReserva)}&laboratory_id=${encodeURIComponent(laboratoryId)}`, {
          headers: { Authorization: `Bearer ${tokenRef.current}` },
          cache: 'no-store',
        }).then(leerJson).then((availability) => {
          if (!Array.isArray(availability.slots)) {
            throw new Error('El servidor respondió con horarios inválidos. Actualiza la página e inténtalo de nuevo.')
          }
          const slots = availability.slots
          setHorarios(slots)
          setHorario((actual) => (
            slots.some((slot) => (
              slot.start_time === actual &&
              intervaloDisponible(slots, actual, duracion)
            ))
              ? actual
              : slots.find((slot) => (
                intervaloDisponible(slots, slot.start_time, duracion)
              ))?.start_time || ''
          ))
        }),
      ])
    } catch (err) {
      setError(err.message)
    } finally {
      setCargando(false)
    }
  }

  function iniciarEdicion(reserva) {
    setError('')
    setMensaje('')
    setReservaEnEdicion(reserva.id)
    setLaboratoryId(String(reserva.laboratory_id))
    setFechaReserva(reserva.reservation_date)
    setHorario(reserva.start_time)
    setDuracion(
      Number(reserva.end_time.slice(0, 2)) -
      Number(reserva.start_time.slice(0, 2))
    )
    setMateria(reserva.subject)
  }

  async function cancelarReserva(reserva) {
    if (!window.confirm(`¿Cancelar la reserva ${reserva.start_time}–${reserva.end_time} del ${reserva.reservation_date}?`)) {
      return
    }
    setError('')
    setMensaje('')
    setCargando(true)
    try {
      const respuesta = await fetch(`/reservations/${reserva.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${tokenRef.current}` },
      })
      const datos = await leerJson(respuesta)
      setMensaje(datos.message)
      if (reservaEnEdicion === reserva.id) {
        setReservaEnEdicion(null)
        setMateria('')
      }
      await cargarReservas(desde, hasta, offsetPropio)
      const parametros = new URLSearchParams({
        date: fechaReserva,
        laboratory_id: laboratoryId,
      })
      const disponibilidad = await fetch(
        `/reservations/availability?${parametros}`,
        { headers: { Authorization: `Bearer ${tokenRef.current}` } }
      ).then(leerJson)
      if (Array.isArray(disponibilidad.slots)) setHorarios(disponibilidad.slots)
    } catch (err) {
      setError(err.message)
    } finally {
      setCargando(false)
    }
  }

  async function filtrarReservas(evento) {
    evento.preventDefault()
    setError('')
    try {
      await cargarReservas(desde, hasta, 0)
    } catch (err) {
      setError(err.message)
    }
  }

  if (!token) {
    return (
      <main className="login-page">
        <form className="login-card" onSubmit={modo === 'login' ? iniciarSesion : registrarDocente}>
          <img className="uad-logo login-logo" src={logoUad} alt="Universidad de Durango, Campus Aguascalientes" />
          <h1>{modo === 'login' ? 'Reservas de laboratorio' : 'Registro docente'}</h1>
          <p className="subtitle">Acceso al laboratorio de cómputo</p>
          {modo === 'registro' && (
            <div className="form-group">
              <label htmlFor="teacher-name">Nombre completo</label>
              <input id="teacher-name" value={nombre} onChange={(evento) => setNombre(evento.target.value)} maxLength={150} autoComplete="name" required />
            </div>
          )}
          <div className="form-group">
            <label htmlFor="teacher-id">Matrícula</label>
            <input id="teacher-id" value={matricula} onChange={(evento) => setMatricula(evento.target.value)} maxLength={50} autoComplete="username" required />
          </div>
          <div className="form-group">
            <label htmlFor="teacher-password">Contraseña</label>
            <input id="teacher-password" type="password" value={password} onChange={(evento) => setPassword(evento.target.value)} minLength={8} maxLength={128} autoComplete={modo === 'login' ? 'current-password' : 'new-password'} required />
          </div>
          {error && <p className="error-message" role="alert">{error}</p>}
          {mensaje && <p className="success-message" role="status">{mensaje}</p>}
          <button className="primary-button" type="submit" disabled={cargando}>
            {cargando ? 'Procesando…' : modo === 'login' ? 'Iniciar sesión' : 'Crear cuenta'}
          </button>
          <button className="back-button" type="button" onClick={() => { setModo(modo === 'login' ? 'registro' : 'login'); setError(''); setMensaje('') }}>
            {modo === 'login' ? 'Crear cuenta docente' : 'Ya tengo una cuenta'}
          </button>
          <a className="back-button" href="/">Ir al acceso administrativo</a>
        </form>
      </main>
    )
  }

  return (
    <main className="reservations-page">
      <header className="reservations-header">
        <div className="reservations-brand">
          <img className="uad-logo" src={logoUad} alt="Universidad de Durango" />
          <div><span>PORTAL DOCENTE</span><h1>Reserva de laboratorio</h1></div>
        </div>
        <button className="table-button" type="button" onClick={cerrarSesion}>Cerrar sesión</button>
      </header>
      <section className="reservations-content">
        <div className="reservations-heading">
          <div><p className="section-kicker">LABORATORIO DE CÓMPUTO</p><h2>Agenda de uso</h2></div>
          <p>Lunes a sábado · 07:00 a 16:00</p>
        </div>
        {error && <p className="error-message" role="alert">{error}</p>}
        {mensaje && <p className="success-message" role="status">{mensaje}</p>}
        <section className="reservation-columns">
          <form className="panel reservation-form" onSubmit={reservar}>
            <h2>{reservaEnEdicion === null ? 'Nueva reserva' : 'Modificar reserva'}</h2>
            <div className="form-group">
              <label htmlFor="teacher-reservation-laboratory">Laboratorio</label>
              <select
                id="teacher-reservation-laboratory"
                value={laboratoryId}
                onChange={(evento) => setLaboratoryId(evento.target.value)}
                required
              >
                <option value="">Selecciona un laboratorio</option>
                {laboratorios.map((laboratorio) => (
                  <option key={laboratorio.id} value={laboratorio.id}>{laboratorio.name}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="reservation-date">Fecha</label>
              <input id="reservation-date" type="date" value={fechaReserva} min={fechaLocalISO()} onChange={(evento) => setFechaReserva(evento.target.value)} required />
            </div>
            <fieldset className="slot-picker">
              <legend>Horario</legend>
              <div className="slot-grid">
                {horarios.map((slot) => (
                  <button key={slot.start_time} type="button" className={`slot-option ${horario === slot.start_time ? 'selected' : ''}`} disabled={!slot.available} aria-pressed={horario === slot.start_time} onClick={() => { setHorario(slot.start_time); setDuracion(1) }}>
                    {slot.start_time}–{slot.end_time}
                  </button>
                ))}
              </div>
            </fieldset>
            <div className="form-group">
              <label htmlFor="reservation-duration">Duración</label>
              <select
                id="reservation-duration"
                value={duracion}
                disabled={!horario}
                onChange={(evento) => setDuracion(Number(evento.target.value))}
              >
                {Array.from(
                  { length: Math.max(1, duracionMaxima(horarios, horario)) },
                  (_, indice) => indice + 1
                ).map((horas) => (
                  <option key={horas} value={horas}>
                    {horas} {horas === 1 ? 'hora' : 'horas'}
                  </option>
                ))}
              </select>
              {horario && <p className="section-description">{horario}–{sumarHoras(horario, duracion)}</p>}
            </div>
            <div className="form-group">
              <label htmlFor="reservation-subject">Materia</label>
              <input id="reservation-subject" value={materia} onChange={(evento) => setMateria(evento.target.value)} maxLength={150} required />
            </div>
            <button className="primary-button" type="submit" disabled={cargando || !laboratoryId || !intervaloDisponible(horarios, horario, duracion) || !materia.trim()}>
              {cargando ? 'Guardando…' : reservaEnEdicion === null ? 'Confirmar reserva' : 'Guardar cambios'}
            </button>
            {reservaEnEdicion !== null && (
              <button className="back-button" type="button" onClick={() => { setReservaEnEdicion(null); setMateria('') }}>
                Dejar de modificar
              </button>
            )}
          </form>
          <section className="panel reservation-list">
            <div className="reservation-list-heading"><h2>Mis reservas</h2><span>{reservas.length} registros</span></div>
            <form className="reservation-filters" onSubmit={filtrarReservas}>
              <div className="form-group"><label htmlFor="reservation-from">Desde</label><input id="reservation-from" type="date" value={desde} onChange={(evento) => setDesde(evento.target.value)} /></div>
              <div className="form-group"><label htmlFor="reservation-to">Hasta</label><input id="reservation-to" type="date" value={hasta} onChange={(evento) => setHasta(evento.target.value)} /></div>
              <button className="table-button" type="submit">Filtrar</button>
            </form>
            <div className="table-container">
              <table>
                <thead><tr><th>Fecha</th><th>Laboratorio</th><th>Horario</th><th>Materia</th><th>Estado</th><th>Acciones</th></tr></thead>
                <tbody>
                  {reservas.map((reserva) => (
                    <tr key={reserva.id}>
                      <td>{textoFecha(reserva.reservation_date)}</td>
                      <td>{reserva.laboratory_name}</td>
                      <td>{reserva.start_time}–{reserva.end_time}</td>
                      <td>{reserva.subject}</td>
                      <td>{reserva.status === 'cancelled' ? 'Cancelada' : 'Confirmada'}</td>
                      <td>{reserva.status === 'confirmed' && (
                        <>
                          <button className="table-button" type="button" onClick={() => iniciarEdicion(reserva)}>Modificar</button>{' '}
                          <button className="table-button" type="button" disabled={cargando} onClick={() => cancelarReserva(reserva)}>Cancelar</button>
                        </>
                      )}</td>
                    </tr>
                  ))}
                  {reservas.length === 0 && <tr><td colSpan="6">No hay reservas para mostrar.</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="reservation-pagination">
              <button className="table-button" type="button" disabled={offsetPropio === 0} onClick={() => cargarReservas(desde, hasta, Math.max(0, offsetPropio - 100))}>Anterior</button>
              <span>{reservas.length ? offsetPropio + 1 : 0}–{offsetPropio + reservas.length}</span>
              <button className="table-button" type="button" disabled={!hayMasPropias} onClick={() => cargarReservas(desde, hasta, offsetPropio + 100)}>Siguiente</button>
            </div>
          </section>
        </section>
      </section>
    </main>
  )
}

export function ReservationsAdminPanel({ token, onUnauthorized }) {
  const [reservas, setReservas] = useState([])
  const [docentesPendientes, setDocentesPendientes] = useState([])
  const [docentes, setDocentes] = useState([])
  const [laboratorios, setLaboratorios] = useState([])
  const [laboratoryId, setLaboratoryId] = useState('')
  const [nombreLaboratorio, setNombreLaboratorio] = useState('')
  const [laboratorioEnEdicion, setLaboratorioEnEdicion] = useState(null)
  const [busquedaLaboratorios, setBusquedaLaboratorios] = useState('')
  const [busquedaDocentes, setBusquedaDocentes] = useState('')
  const [busquedaPendientes, setBusquedaPendientes] = useState('')
  const [busquedaReservas, setBusquedaReservas] = useState('')
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [matricula, setMatricula] = useState('')
  const [reservaEnEdicion, setReservaEnEdicion] = useState(null)
  const [teacherUserId, setTeacherUserId] = useState('')
  const [fechaReserva, setFechaReserva] = useState(fechaLocalISO())
  const [horarios, setHorarios] = useState([])
  const [horario, setHorario] = useState('')
  const [duracion, setDuracion] = useState(1)
  const [bloquesSeleccionados, setBloquesSeleccionados] = useState([])
  const [materia, setMateria] = useState('')
  const [reservaRecurrente, setReservaRecurrente] = useState(false)
  const [fechaFinalSerie, setFechaFinalSerie] = useState(fechaLocalISO())
  const [diasSerie, setDiasSerie] = useState([])
  const [offset, setOffset] = useState(0)
  const [hayMas, setHayMas] = useState(false)
  const [estadoReservas, setEstadoReservas] = useState('confirmed')
  const [error, setError] = useState('')
  const [mensaje, setMensaje] = useState('')
  const [cargando, setCargando] = useState(false)

  const laboratoriosFiltrados = laboratorios.filter((laboratorio) => (
    coincideTexto(busquedaLaboratorios, laboratorio.name)
  ))
  const docentesFiltrados = docentes.filter((docente) => (
    coincideTexto(busquedaDocentes, docente.full_name, docente.matricula)
  ))
  const docentesPendientesFiltrados = docentesPendientes.filter((docente) => (
    coincideTexto(busquedaPendientes, docente.full_name, docente.matricula)
  ))
  const reservasFiltradas = reservas.filter((reserva) => (
    coincideTexto(
      busquedaReservas,
      reserva.laboratory_name,
      reserva.teacher_name,
      reserva.matricula,
      reserva.subject,
      reserva.reservation_date,
      reserva.start_time,
      reserva.end_time,
    )
  ))

  const consultar = useCallback(async (filtros = {}) => {
    setCargando(true)
    setError('')
    const fechaInicio = filtros.desde || ''
    const fechaFin = filtros.hasta || ''
    const matriculaFiltro = filtros.matricula || ''
    const estado = filtros.estado || estadoReservas
    const parametros = new URLSearchParams({
      limit: '100',
      offset: String(filtros.offset ?? 0),
      status: estado,
    })
    if (fechaInicio) parametros.set('from', fechaInicio)
    if (fechaFin) parametros.set('to', fechaFin)
    if (matriculaFiltro) parametros.set('matricula', matriculaFiltro)
    try {
      const respuesta = await fetch(`/admin/reservations?${parametros}`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: 'no-store',
      })
      const datos = await leerJson(respuesta)
      if (
        !Array.isArray(datos.reservations) ||
        !Array.isArray(datos.pending_teachers) ||
        !Array.isArray(datos.laboratories)
      ) {
        throw new Error('El servidor respondió con información de reservas inválida.')
      }
      setReservas(datos.reservations)
      setDocentesPendientes(datos.pending_teachers)
      setDocentes(datos.teachers)
      setLaboratorios(datos.laboratories)
      setLaboratoryId((actual) => (
        datos.laboratories.some((laboratorio) => String(laboratorio.id) === actual)
          ? actual
          : String(datos.laboratories[0]?.id || '')
      ))
      setHayMas(datos.reservations.length === 100)
    } catch (err) {
      setError(err.message)
      if (err.status === 401 || err.status === 403) onUnauthorized()
    } finally {
      setCargando(false)
    }
  }, [estadoReservas, onUnauthorized, token])

  useEffect(() => {
    async function cargar() {
      await consultar({ offset: 0 })
    }
    cargar()
  }, [consultar])

  useEffect(() => {
    if (!fechaReserva || !laboratoryId) return undefined
    if (reservaRecurrente && reservaEnEdicion === null) return undefined
    let vigente = true
    async function cargarHorariosAdmin() {
      const parametros = new URLSearchParams({
        date: fechaReserva,
        laboratory_id: laboratoryId,
      })
      if (reservaEnEdicion !== null) {
        parametros.set('exclude_id', String(reservaEnEdicion))
      }
      try {
        const respuesta = await fetch(`/reservations/availability?${parametros}`, {
          headers: { Authorization: `Bearer ${token}` },
          cache: 'no-store',
        })
        const datos = await leerJson(respuesta)
        if (!vigente) return
        if (!Array.isArray(datos.slots)) {
          throw new Error('El servidor respondió con horarios inválidos.')
        }
        setHorarios(datos.slots)
      } catch (err) {
        if (!vigente) return
        setError(err.message)
        if (err.status === 401 || err.status === 403) onUnauthorized()
      }
    }
    cargarHorariosAdmin()
    return () => { vigente = false }
  }, [token, fechaReserva, laboratoryId, reservaEnEdicion, reservaRecurrente, onUnauthorized])

  function seleccionarBloqueAdmin(hora) {
    const estaSeleccionado = bloquesSeleccionados.includes(hora)
    const siguientes = estaSeleccionado
      ? bloquesSeleccionados.filter((bloque) => bloque !== hora)
      : [...bloquesSeleccionados, hora].sort()
    const horasNumericas = siguientes.map((bloque) => Number(bloque.slice(0, 2)))
    const esContinuo = horasNumericas.every(
      (valor, indice) => indice === 0 || valor === horasNumericas[indice - 1] + 1
    )
    if (!esContinuo) {
      setError('Selecciona bloques de horas consecutivos, sin dejar espacios.')
      return
    }
    if (siguientes.length > duracion) {
      setError(`Selecciona exactamente ${duracion} ${duracion === 1 ? 'bloque' : 'bloques'} horarios.`)
      return
    }
    setError('')
    setBloquesSeleccionados(siguientes)
    setHorario(siguientes[0] || '')
  }

  async function crearLaboratorio(evento) {
    evento.preventDefault()
    setError('')
    setMensaje('')
    setCargando(true)
    try {
      const respuesta = await fetch('/admin/laboratories', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ name: nombreLaboratorio.trim() }),
      })
      const datos = await leerJson(respuesta)
      setNombreLaboratorio('')
      setMensaje(datos.message)
      await consultar({ offset, desde, hasta, matricula })
      setLaboratoryId(String(datos.laboratory.id))
    } catch (err) {
      setError(err.message)
      if (err.status === 401 || err.status === 403) onUnauthorized()
    } finally {
      setCargando(false)
    }
  }

  async function guardarLaboratorio(evento) {
    evento.preventDefault()
    if (laboratorioEnEdicion === null) return
    setError('')
    setMensaje('')
    setCargando(true)
    try {
      const respuesta = await fetch(
        `/admin/laboratories/${laboratorioEnEdicion.id}`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
              Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            name: laboratorioEnEdicion.name.trim(),
          }),
        }
      )
      const datos = await leerJson(respuesta)
      setLaboratorioEnEdicion(null)
      setMensaje(datos.message)
      await consultar({ offset, desde, hasta, matricula })
    } catch (err) {
      setError(err.message)
      if (err.status === 401 || err.status === 403) onUnauthorized()
    } finally {
      setCargando(false)
    }
  }

  async function eliminarLaboratorio(laboratorio) {
    if (!window.confirm(
      `¿Eliminar el laboratorio "${laboratorio.name}"? Esta acción no se puede deshacer.`
    )) return

    setError('')
    setMensaje('')
    setCargando(true)
    try {
      const respuesta = await fetch(
        `/admin/laboratories/${laboratorio.id}`,
        {
          method: 'DELETE',
          headers: { Authorization: `Bearer ${token}` },
        }
      )
      const datos = await leerJson(respuesta)
      if (laboratorioEnEdicion?.id === laboratorio.id) {
        setLaboratorioEnEdicion(null)
      }
      setMensaje(datos.message)
      await consultar({ offset, desde, hasta, matricula })
    } catch (err) {
      setError(err.message)
      if (err.status === 401 || err.status === 403) onUnauthorized()
    } finally {
      setCargando(false)
    }
  }

  async function aprobar(teacherId) {
    setError('')
    try {
      const respuesta = await fetch(`/admin/reservations/teachers/${teacherId}/approve`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      await leerJson(respuesta)
      await consultar({ offset, desde, hasta, matricula })
    } catch (err) {
      setError(err.message)
      if (err.status === 401 || err.status === 403) onUnauthorized()
    }
  }

  function iniciarEdicionReserva(reserva) {
    setReservaEnEdicion(reserva.id)
    setReservaRecurrente(false)
    setLaboratoryId(String(reserva.laboratory_id))
    setTeacherUserId(String(reserva.teacher_user_id))
    setFechaReserva(reserva.reservation_date)
    const inicio = Number(reserva.start_time.slice(0, 2))
    const fin = Number(reserva.end_time.slice(0, 2))
    const bloques = Array.from({ length: fin - inicio }, (_, indice) => (
      `${String(inicio + indice).padStart(2, '0')}:00`
    ))
    setBloquesSeleccionados(bloques)
    setHorario(reserva.start_time)
    setDuracion(bloques.length)
    setMateria(reserva.subject)
    setError('')
  }

  function limpiarEditorReserva() {
    setReservaEnEdicion(null)
    setTeacherUserId('')
    setReservaRecurrente(false)
    setDiasSerie([])
    setFechaFinalSerie(fechaLocalISO())
    setFechaReserva(fechaLocalISO())
    setHorario('')
    setDuracion(1)
    setBloquesSeleccionados([])
    setMateria('')
  }

  async function guardarReservaAdmin(evento) {
    evento.preventDefault()
    setError('')
    setMensaje('')
    setCargando(true)
    const editando = reservaEnEdicion !== null
    const endpoint = editando
      ? `/admin/reservations/${reservaEnEdicion}`
      : reservaRecurrente
        ? '/admin/reservations/recurring'
        : '/admin/reservations'
    try {
      const respuesta = await fetch(
        endpoint,
        {
          method: editando ? 'PUT' : 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            teacher_user_id: Number(teacherUserId),
            laboratory_id: Number(laboratoryId),
            ...(reservaRecurrente && !editando
              ? {
                start_date: fechaReserva,
                end_date: fechaFinalSerie,
                weekdays: diasSerie,
              }
              : { reservation_date: fechaReserva }),
            start_time: horario,
            end_time: sumarHoras(horario, duracion),
            subject: materia.trim(),
          }),
        }
      )
      const datos = await leerJson(respuesta)
      setMensaje(datos.message)
      if (Array.isArray(datos.conflicts) && datos.conflicts.length > 0) {
        setMensaje(`${datos.message} Fechas omitidas: ${datos.conflicts.map(textoFecha).join(', ')}.`)
      }
      await consultar({ offset, desde, hasta, matricula })
      limpiarEditorReserva()
    } catch (err) {
      setError(err.message)
      if (err.status === 401 || err.status === 403) onUnauthorized()
    } finally {
      setCargando(false)
    }
  }

  async function cancelarReservaAdmin(reserva) {
    if (!window.confirm(`¿Cancelar la reserva ${reserva.start_time}–${reserva.end_time} del ${reserva.reservation_date}?`)) {
      return
    }
    setError('')
    setMensaje('')
    try {
      const respuesta = await fetch(`/admin/reservations/${reserva.id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      const datos = await leerJson(respuesta)
      await consultar({ offset, desde, hasta, matricula })
      setMensaje(datos.message)
      if (reservaEnEdicion === reserva.id) limpiarEditorReserva()
    } catch (err) {
      setError(err.message)
      if (err.status === 401 || err.status === 403) onUnauthorized()
    }
  }

  function filtrar(evento) {
    evento.preventDefault()
    setOffset(0)
    consultar({ offset: 0, desde, hasta, matricula, estado: estadoReservas })
  }

  function cambiarVistaReservas(estado) {
    setEstadoReservas(estado)
    setOffset(0)
    consultar({ offset: 0, desde, hasta, matricula, estado })
  }

  return (
    <>
      {error && <p className="error-message" role="alert">{error}</p>}
      {mensaje && <p className="success-message" role="status">{mensaje}</p>}
      <section className="panel">
        <div className="reservation-section-heading">
          <span className="reservation-step">1</span>
          <div>
            <h2>Laboratorios</h2>
            <p className="section-description">Agrega laboratorios al catálogo compartido con LabMonitor.</p>
          </div>
        </div>
        <form
          className="reservation-admin-form laboratory-admin-form"
          onSubmit={laboratorioEnEdicion ? guardarLaboratorio : crearLaboratorio}
        >
          <div className="form-group">
            <label htmlFor="new-laboratory-name">
              {laboratorioEnEdicion ? 'Editar nombre del laboratorio' : 'Nombre del laboratorio'}
            </label>
            <input
              id="new-laboratory-name"
              value={laboratorioEnEdicion?.name ?? nombreLaboratorio}
              onChange={(evento) => {
                if (laboratorioEnEdicion) {
                  setLaboratorioEnEdicion({
                    ...laboratorioEnEdicion,
                    name: evento.target.value,
                  })
                } else {
                  setNombreLaboratorio(evento.target.value)
                }
              }}
              maxLength={100}
              required
            />
          </div>
          <div className="laboratory-form-actions">
            <button
              className="primary-button"
              type="submit"
              disabled={cargando || !(laboratorioEnEdicion?.name ?? nombreLaboratorio).trim()}
            >
              {cargando
                ? (laboratorioEnEdicion ? 'Guardando…' : 'Creando…')
                : (laboratorioEnEdicion ? 'Guardar cambios' : 'Crear laboratorio')}
            </button>
            {laboratorioEnEdicion && (
              <button
                className="table-button"
                type="button"
                disabled={cargando}
                onClick={() => setLaboratorioEnEdicion(null)}
              >
                Cancelar
              </button>
            )}
          </div>
        </form>
        <div className="section-search-row">
          <div className="form-group section-search">
            <label htmlFor="search-laboratories">Buscar laboratorios</label>
            <input
              id="search-laboratories"
              type="search"
              value={busquedaLaboratorios}
              onChange={(evento) => setBusquedaLaboratorios(evento.target.value)}
              placeholder="Nombre del laboratorio"
            />
          </div>
          <span className="section-result-count">
            {laboratoriosFiltrados.length} de {laboratorios.length} laboratorios
          </span>
        </div>
        {laboratoriosFiltrados.length > 0 ? (
          <div className="laboratory-admin-list">
            {laboratoriosFiltrados.map((laboratorio) => (
              <div className="laboratory-admin-row" key={laboratorio.id}>
                <span>{laboratorio.name}</span>
                <div className="laboratory-admin-actions">
                  <button
                    className="table-button"
                    type="button"
                    disabled={cargando}
                    onClick={() => {
                      setError('')
                      setMensaje('')
                      setLaboratorioEnEdicion({
                        id: laboratorio.id,
                        name: laboratorio.name,
                      })
                    }}
                  >
                    Editar
                  </button>
                  <button
                    className="table-button laboratory-delete-button"
                    type="button"
                    disabled={cargando}
                    onClick={() => eliminarLaboratorio(laboratorio)}
                  >
                    Eliminar
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="section-description">
            {laboratorios.length === 0
              ? 'No hay laboratorios disponibles.'
              : 'No se encontraron laboratorios con esa búsqueda.'}
          </p>
        )}
        <div className="reservation-laboratory-footer">
          <button
            className="table-button"
            type="button"
            disabled={cargando}
            onClick={() => consultar({ offset, desde, hasta, matricula })}
          >
            Actualizar lista de laboratorios
          </button>
        </div>
      </section>
      <section className="panel">
        <div className="reservation-section-heading">
          <span className="reservation-step">2</span>
          <div>
            <h2>{reservaEnEdicion === null ? 'Crear reserva' : 'Modificar reserva'}</h2>
            <p className="section-description">Selecciona un docente, laboratorio y horario.</p>
          </div>
        </div>
        <form className="reservation-admin-form" onSubmit={guardarReservaAdmin}>
          <div className="form-group">
            <label htmlFor="admin-reservation-teacher-select">Docente</label>
            <input
              id="search-reservation-teachers"
              type="search"
              aria-label="Buscar docentes por nombre o matrícula"
              value={busquedaDocentes}
              onChange={(evento) => setBusquedaDocentes(evento.target.value)}
              placeholder="Buscar docente por nombre o matrícula"
            />
            <select
              id="admin-reservation-teacher-select"
              value={teacherUserId}
              onChange={(evento) => setTeacherUserId(evento.target.value)}
              required
            >
              <option value="">Selecciona un docente</option>
              {docentesFiltrados.map((docente) => (
                <option key={docente.id} value={docente.id}>
                  {docente.full_name} · {docente.matricula}
                </option>
              ))}
            </select>
            {docentesFiltrados.length === 0 && docentes.length > 0 && (
              <small>No se encontraron docentes con esa búsqueda.</small>
            )}
          </div>
          <div className="form-group">
            <label htmlFor="admin-reservation-laboratory">Laboratorio</label>
            <select
              id="admin-reservation-laboratory"
              value={laboratoryId}
              onChange={(evento) => {
                setLaboratoryId(evento.target.value)
                setBloquesSeleccionados([])
                setHorario('')
                setDuracion(1)
              }}
              required
            >
              <option value="">Selecciona un laboratorio</option>
              {laboratorios.map((laboratorio) => (
                <option key={laboratorio.id} value={laboratorio.id}>{laboratorio.name}</option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="admin-booking-date">{reservaRecurrente ? 'Desde' : 'Fecha'}</label>
            <input
              id="admin-booking-date"
              type="date"
              min={fechaLocalISO()}
              value={fechaReserva}
              onChange={(evento) => {
                const nuevaFecha = evento.target.value
                setFechaReserva(nuevaFecha)
                setFechaFinalSerie((actual) => actual < nuevaFecha ? nuevaFecha : actual)
                setBloquesSeleccionados([])
                setHorario('')
                setDuracion(1)
              }}
              required
            />
          </div>
          {reservaEnEdicion === null && (
            <label className="reservation-series-toggle">
              <input
                type="checkbox"
                checked={reservaRecurrente}
                onChange={(evento) => {
                  const activo = evento.target.checked
                  setReservaRecurrente(activo)
                  setBloquesSeleccionados([])
                  setHorario('')
                  setDuracion(1)
                  if (activo) {
                    setHorarios(HORARIOS_ESTANDAR)
                  }
                }}
              />
              Crear serie en días seleccionados
            </label>
          )}
          {reservaRecurrente && reservaEnEdicion === null && (
            <>
              <p className="section-description reservation-series-description">
                Se repetirá en los días elegidos hasta la fecha final. Las fechas ocupadas se omitirán; el periodo máximo es de un año.
              </p>
              <div className="form-group">
                <label htmlFor="admin-series-end-date">Hasta</label>
                <input
                  id="admin-series-end-date"
                  type="date"
                  min={fechaReserva}
                  value={fechaFinalSerie}
                  onChange={(evento) => setFechaFinalSerie(evento.target.value)}
                  required
                />
              </div>
              <fieldset className="weekday-picker">
                <legend>Repetir cada semana</legend>
                {[
                  ['Lunes', 0],
                  ['Martes', 1],
                  ['Miércoles', 2],
                  ['Jueves', 3],
                  ['Viernes', 4],
                  ['Sábado', 5],
                ].map(([dia, valor]) => (
                  <label key={valor}>
                    <input
                      type="checkbox"
                      checked={diasSerie.includes(valor)}
                      onChange={(evento) => setDiasSerie((actuales) => (
                        evento.target.checked
                          ? [...actuales, valor]
                          : actuales.filter((actual) => actual !== valor)
                      ))}
                    />
                    {dia}
                  </label>
                ))}
              </fieldset>
            </>
          )}
          <fieldset className="slot-picker">
            <legend>Bloques horarios</legend>
            <p className="section-description">
              Elige la duración y después marca todos los bloques horarios consecutivos para habilitar la reserva.
            </p>
            <div className="form-group reservation-duration-choice">
              <label htmlFor="admin-reservation-duration">Duración deseada</label>
              <select
                id="admin-reservation-duration"
                value={duracion}
                onChange={(evento) => {
                  setDuracion(Number(evento.target.value))
                  setBloquesSeleccionados([])
                  setHorario('')
                  setError('')
                }}
              >
                {Array.from({ length: 9 }, (_, indice) => indice + 1).map((horas) => (
                  <option key={horas} value={horas}>
                    {horas} {horas === 1 ? 'hora' : 'horas'}
                  </option>
                ))}
              </select>
            </div>
            <div className="slot-grid">
              {horarios.map((slot) => {
                const seleccionado = bloquesSeleccionados.includes(slot.start_time)
                return (
                <button key={slot.start_time} type="button" className={`slot-option ${seleccionado ? 'selected' : ''}`} disabled={!reservaRecurrente && !slot.available && !seleccionado} aria-pressed={seleccionado} onClick={() => seleccionarBloqueAdmin(slot.start_time)}>
                  {slot.start_time}–{slot.end_time}
                </button>
                )
              })}
            </div>
          </fieldset>
          <div className="reservation-selection-summary">
            <strong>
              {bloquesSeleccionados.length
                ? `${bloquesSeleccionados.length} ${bloquesSeleccionados.length === 1 ? 'hora seleccionada' : 'horas seleccionadas'}`
                : 'Aún no seleccionas un horario'}
            </strong>
            {horario && <span>{horario}–{sumarHoras(horario, bloquesSeleccionados.length)}</span>}
          </div>
          <div className="form-group">
            <label htmlFor="admin-reservation-subject">Materia</label>
            <input id="admin-reservation-subject" value={materia} onChange={(evento) => setMateria(evento.target.value)} maxLength={150} required />
          </div>
          <button className="primary-button" type="submit" disabled={cargando || !teacherUserId || !laboratoryId || bloquesSeleccionados.length !== duracion || !(reservaRecurrente ? diasSerie.length > 0 && fechaFinalSerie >= fechaReserva : intervaloDisponible(horarios, horario, duracion)) || !materia.trim()}>
            {cargando ? 'Guardando…' : reservaEnEdicion === null ? reservaRecurrente ? 'Crear serie de reservas' : 'Crear reserva' : 'Guardar cambios'}
          </button>
          {reservaEnEdicion !== null && <button className="back-button" type="button" onClick={limpiarEditorReserva}>Dejar de modificar</button>}
        </form>
      </section>
      <section className="panel">
        <div className="reservation-section-heading">
          <span className="reservation-step">3</span>
          <div className="reservation-list-heading">
            <h2>Autorizaciones docentes</h2>
            <span>{docentesPendientes.length} pendientes</span>
          </div>
        </div>
        <div className="section-search-row">
          <div className="form-group section-search">
            <label htmlFor="search-pending-teachers">Buscar docentes pendientes</label>
            <input
              id="search-pending-teachers"
              type="search"
              value={busquedaPendientes}
              onChange={(evento) => setBusquedaPendientes(evento.target.value)}
              placeholder="Nombre o matrícula"
            />
          </div>
          <span className="section-result-count">
            {docentesPendientesFiltrados.length} de {docentesPendientes.length} docentes pendientes
          </span>
        </div>
        {docentesPendientesFiltrados.length === 0 ? <p className="section-description">
          {docentesPendientes.length === 0
            ? 'No hay cuentas pendientes de autorización.'
            : 'No se encontraron docentes pendientes con esa búsqueda.'}
        </p> : (
          <div className="table-container">
            <table>
              <thead><tr><th>Docente</th><th>Matrícula</th><th>Fecha de registro</th><th>Acción</th></tr></thead>
              <tbody>{docentesPendientesFiltrados.map((docente) => (
                <tr key={docente.id}>
                  <td>{docente.full_name}</td><td>{docente.matricula}</td><td>{docente.created_at ? textoFecha(docente.created_at.slice(0, 10)) : 'N/D'}</td>
                  <td><button className="table-button" type="button" onClick={() => aprobar(docente.id)}>Autorizar</button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
      <section className="panel">
        <div className="reservation-section-heading">
          <span className="reservation-step">4</span>
          <div>
            <h2>Historial de reservas</h2>
            <p className="section-description">Las reservas canceladas se consultan por separado.</p>
          </div>
        </div>
        <div className="reservation-history-toolbar">
          <div className="reservation-status-tabs" role="group" aria-label="Filtrar reservas por estado">
            <button
              className={`reservation-status-tab ${estadoReservas === 'confirmed' ? 'active' : ''}`}
              type="button"
              aria-pressed={estadoReservas === 'confirmed'}
              onClick={() => cambiarVistaReservas('confirmed')}
            >
              Confirmadas
            </button>
            <button
              className={`reservation-status-tab ${estadoReservas === 'cancelled' ? 'active' : ''}`}
              type="button"
              aria-pressed={estadoReservas === 'cancelled'}
              onClick={() => cambiarVistaReservas('cancelled')}
            >
              Canceladas
            </button>
          </div>
          <span className="reservation-result-count">
            {cargando ? 'Actualizando…' : `${reservas.length} registros`}
          </span>
        </div>
        <form className="reservation-filters" onSubmit={filtrar}>
          <div className="form-group"><label htmlFor="admin-reservation-from">Desde</label><input id="admin-reservation-from" type="date" value={desde} onChange={(evento) => setDesde(evento.target.value)} /></div>
          <div className="form-group"><label htmlFor="admin-reservation-to">Hasta</label><input id="admin-reservation-to" type="date" value={hasta} onChange={(evento) => setHasta(evento.target.value)} /></div>
          <div className="form-group"><label htmlFor="admin-reservation-teacher">Matrícula docente</label><input id="admin-reservation-teacher" value={matricula} onChange={(evento) => setMatricula(evento.target.value)} maxLength={50} /></div>
          <button className="table-button" type="submit" disabled={cargando}>Filtrar</button>
        </form>
        <div className="section-search-row">
          <div className="form-group section-search">
            <label htmlFor="search-reservations">Buscar en reservas cargadas</label>
            <input
              id="search-reservations"
              type="search"
              value={busquedaReservas}
              onChange={(evento) => setBusquedaReservas(evento.target.value)}
              placeholder="Docente, matrícula, laboratorio o materia"
            />
          </div>
          <span className="section-result-count">
            {reservasFiltradas.length} de {reservas.length} en esta página
          </span>
        </div>
        <div className="table-container">
          <table className="reservation-history-table">
            <thead><tr><th>Fecha</th><th>Laboratorio</th><th>Horario</th><th>Docente</th><th>Matrícula</th><th>Materia</th><th>Estado</th><th>Acciones</th></tr></thead>
            <tbody>
              {reservasFiltradas.map((reserva) => (
                <tr key={reserva.id}>
                  <td>{textoFecha(reserva.reservation_date)}</td>
                  <td>{reserva.laboratory_name}</td>
                  <td>{reserva.start_time}–{reserva.end_time}</td>
                  <td>{reserva.teacher_name}</td>
                  <td>{reserva.matricula}</td>
                  <td>{reserva.subject}</td>
                  <td>{estadoReservas === 'cancelled' ? 'Cancelada' : 'Confirmada'}</td>
                  <td>
                    {estadoReservas === 'confirmed' && (
                      <div className="reservation-actions">
                        <button className="table-button" type="button" onClick={() => iniciarEdicionReserva(reserva)}>Modificar</button>
                        <button className="table-button reservation-cancel-button" type="button" onClick={() => cancelarReservaAdmin(reserva)}>Cancelar</button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {reservasFiltradas.length === 0 && (
                <tr>
                  <td colSpan="8">
                    {reservas.length > 0
                      ? 'No se encontraron reservas con esa búsqueda en esta página.'
                      : estadoReservas === 'cancelled'
                        ? 'No hay reservas canceladas para los filtros seleccionados.'
                        : 'No hay reservas confirmadas para los filtros seleccionados.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="reservation-pagination">
          <button className="table-button" type="button" disabled={offset === 0 || cargando} onClick={() => { const siguiente = Math.max(0, offset - 100); setOffset(siguiente); consultar({ offset: siguiente, desde, hasta, matricula }) }}>Anterior</button>
          <span>{offset + 1}–{offset + reservas.length}</span>
          <button className="table-button" type="button" disabled={!hayMas || cargando} onClick={() => { const siguiente = offset + 100; setOffset(siguiente); consultar({ offset: siguiente, desde, hasta, matricula }) }}>Siguiente</button>
        </div>
      </section>
    </>
  )
}
