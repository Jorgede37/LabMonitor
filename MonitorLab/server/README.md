# Ejecutar LabMonitor en Windows

Esta guia instala la API y el dashboard para una prueba en una red local. El servidor debe ser un equipo confiable y permanecer encendido. No expongas el servidor Vite de desarrollo directamente a Internet; para produccion usa un despliegue con servidor web, HTTPS, firewall y supervision de servicios.

## Requisitos

- Windows 10/11 de 64 bits.
- Python 3.14 de 64 bits.
- Node.js 24 LTS y npm.
- SQL Server con la base `LabMonitor` ya creada y su esquema aplicado.
- Microsoft ODBC Driver 17 for SQL Server de 64 bits.
- Permisos de Windows para conectarse a la base. La API usa autenticacion integrada de Windows, por lo que la cuenta de Windows que ejecuta Uvicorn debe tener acceso a la base.

## 1. Copiar el proyecto e instalar dependencias

Copia el proyecto a la computadora anfitriona y abre PowerShell en la carpeta del proyecto. No copies carpetas `venv`, `node_modules` ni archivos `.env` de otra computadora.

En la carpeta `server`, crea e instala el entorno de Python:

```powershell
Set-Location .\server
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
Copy-Item .\.env.example .\.env
```

Instala las dependencias del dashboard en otra terminal:

```powershell
Set-Location .\frontend
npm.cmd ci
```

## 2. Configurar SQL Server y secretos

Edita `server\.env` con un editor de texto. Ajusta `SQL_SERVER` al servidor o instancia SQL, por ejemplo `localhost\SQLEXPRESS` si SQL Server Express corre en la misma computadora. Conserva `SQL_DATABASE=LabMonitor`, salvo que la base tenga otro nombre.

La cuenta de Windows que ejecutara la API debe tener permiso de lectura y escritura en la base. Si SQL Server esta en otra computadora, su administrador debe habilitar TCP/IP, permitir la conexion desde el servidor LabMonitor y conceder permisos a la cuenta de Windows utilizada por Uvicorn.

Genera una clave JWT nueva, sin compartirla ni reutilizar la de otra maquina:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copia el resultado en `JWT_SECRET_KEY`. Deja `COMPUTADORA_PRUEBA_ID=all` para que el worker no quede limitado al equipo de prueba con ID 2. Si se necesitan correos, configura tambien las variables `SMTP_*` con las credenciales correspondientes; no guardes el archivo `.env` en repositorios ni lo compartas.

> La API no crea la base ni las tablas automaticamente. Antes de continuar, restaura un respaldo SQL o crea la base e importa el script de esquema aprobado.

## 3. Crear el primer administrador

Desde PowerShell, dentro de `server`, ejecuta el asistente. Debe conectarse a la base ya preparada:

```powershell
.\.venv\Scripts\python.exe -m app.create_admin
```

Escribe un nombre de usuario, nombre completo y una contrasena de al menos 12 caracteres.

## 4. Arrancar la API y el dashboard

Abre una terminal para la API, desde la carpeta `server`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

En una segunda terminal, desde la carpeta `frontend`:

```powershell
npm.cmd run dev -- --host 0.0.0.0 --port 5173
```

En la misma computadora, valida la API en `http://127.0.0.1:8000/` y el dashboard en `http://127.0.0.1:5173`.

## 5. Abrir el dashboard desde otra PC de la misma red

1. Obtén la IP local de la computadora anfitriona con `ipconfig`.
2. En la otra PC, abre `http://IP_DEL_SERVIDOR:5173`, sustituyendo el texto por la IP real.
3. Si no carga, pide al administrador de Windows/TI que permita TCP 5173 desde la red local autorizada. No desactives el firewall ni configures redireccionamiento de puertos en el router.
4. Para que los equipos monitoreados reporten directamente a la API, permite TCP 8000 solo desde la VLAN/red autorizada y configura LabMonitor con `http://IP_DEL_SERVIDOR:8000`.

El puerto 5173 es el servidor de desarrollo de Vite: úsalo solo para pruebas temporales en una red confiable. No es una configuracion de produccion, no ofrece HTTPS ni debe publicarse en Internet. Para acceso externo hace falta un despliegue revisado por TI, con HTTPS y controles de acceso de red.

## Detener los procesos

En cada terminal, pulsa `Ctrl+C`. Si la consola se cierra, termina el proceso correspondiente desde el Administrador de tareas; no finalices otros procesos de Python o Node que no pertenezcan a LabMonitor.
