# OficiosYa

OficiosYa conecta clientes y empresas con trabajadores de mantenimiento y reparación. La aplicación conserva las estructuras académicas del trabajo práctico y ahora persiste usuarios, oficios, servicios, proyectos y postulaciones en PostgreSQL mediante SQLAlchemy.

## Estado y alcance

- La ejecución de desarrollo es local: `http://127.0.0.1:5000`. Este proyecto no se publica en Internet.
- PostgreSQL conserva los datos al cerrar Flask o reiniciar Windows. Las estructuras académicas se reconstruyen desde PostgreSQL al atender cada petición.
- La pila LIFO de acciones reversibles solo vive mientras el proceso Flask está activo. No se presenta como persistente.
- El acceso usa contraseña con hash seguro y sesiones Flask. Es una base académica local, no una auditoría de seguridad ni una configuración lista para producción.
- `.env` contiene configuración local y está excluido de Git. No compartas ese archivo.
- Las cuentas ficticias se cargan solo cuando se ejecuta `flask seed-demo`; no se agregan automáticamente.

## Archivos y carpetas

- `app.py`: fábrica Flask, rutas, permisos por rol, formularios, comandos CLI y manejadores de errores.
- `config.py`: configura la conexión, cookies y límites mediante variables de entorno; incluye la configuración de pruebas.
- `extensions.py`: instancias compartidas de SQLAlchemy, Flask-Migrate, Flask-Login y CSRF.
- `db_models.py`: modelos ORM, restricciones, relaciones y tablas de asociación.
- `modelos.py`: reglas de negocio, validación, transacciones e integración de estructuras académicas.
- `estructuras.py`: implementaciones propias de lista enlazada, FIFO, LIFO, árbol, grafo/BFS y tabla hash.
- `migrations/`: historial de cambios de esquema administrado por Alembic/Flask-Migrate.
- `templates/`: páginas Jinja, formularios, perfiles, paneles y vista académica.
- `static/style.css`: identidad visual y estilos adaptables.
- `scripts/backup_db.py`: crea respaldos PostgreSQL en formato custom (`.dump`).
- `scripts/restore_db.py`: restaura un respaldo solo en una conexión local, tras pedir confirmación.
- `test_oficiosya.py`: pruebas de estructuras, reglas, rutas, permisos y persistencia.
- `.env.example`: plantilla de variables de entorno sin credenciales reales.
- `requirements.txt`: dependencias Python.
- `backups/`: destino de respaldos y copia de referencia previa al cambio. No se incluye en Git.
- `instance/`: archivos locales temporales de SQLite para pruebas; no es la base de la aplicación.

## Tablas y relaciones

La migración inicial crea 17 tablas:

| Tabla | Propósito |
|---|---|
| `users` | Datos comunes, correo, hash de contraseña, rol, estado e identificador público. |
| `worker_profiles` | Perfil profesional unido a `users` por herencia ORM. |
| `companies` | Datos empresariales y RUC; unido a `users`. |
| `offices` | Oficios y árbol de categorías mediante `parent_id`. |
| `zones` | Zonas activas. |
| `office_requests` | Propuestas de oficios, decisión y administrador responsable. |
| `projects` | Publicaciones empresariales. |
| `applications` | Postulaciones únicas por proyecto y trabajador. |
| `service_categories` | Categorías Hogar y Empresarial. |
| `services` | Solicitudes de clientes y su estado. |
| `ratings` | Valoraciones, con una por servicio y puntuación de 1 a 5. |
| `worker_offices` | Asociación muchos a muchos entre trabajadores y oficios. |
| `worker_zones` | Asociación muchos a muchos entre trabajadores y zonas. |
| `worker_service_categories` | Categorías de servicio admitidas por cada trabajador. |
| `project_offices` | Oficios necesarios para cada proyecto. |
| `service_category_links` | Categorías asociadas a cada servicio. |
| `zone_connections` | Aristas no dirigidas entre zonas. |

`Cliente` y `Administrador` son subtipos ORM de `Usuario` y usan `users`; `Trabajador` y `Empresa` agregan tablas de perfil. Las claves primarias numéricas son internas. Al crear una cuenta se genera un identificador público como `CLI-000001`, `TRA-000002`, `EMP-000003` o `ADM-000004`, basado en la secuencia de la tabla.

## Requisitos

- Windows 10/11, Visual Studio Code y Python 3.10 o posterior.
- PostgreSQL instalado y en ejecución local.
- pgAdmin es opcional, pero facilita crear bases y revisar tablas.
- PowerShell. No se necesita Node.js ni un servicio externo para ejecutar la aplicación.

## Instalación local en Windows

### 1. Abrir la carpeta y crear el entorno virtual

En Visual Studio Code usa **Archivo → Abrir carpeta…** y selecciona la carpeta raíz de OficiosYa. Abre una terminal PowerShell en esa carpeta y ejecuta:

```powershell
py -3 -m venv .venv
```

Si `py` no está disponible, usa `python -m venv .venv`.

Activa el entorno:

```powershell
.\.venv\Scripts\Activate.ps1
```

Si PowerShell indica que no permite ejecutar scripts, habilita la activación solo en esa ventana y vuelve a activarla:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

La política vuelve a su valor anterior al cerrar esa terminal. También puedes omitir la activación y ejecutar cada herramienta con `.\.venv\Scripts\python.exe`.

### 2. Instalar PostgreSQL y crear las bases

Instala PostgreSQL localmente y selecciona también **Command Line Tools** y **pgAdmin 4** si el instalador los ofrece. Anota el puerto (habitualmente `5432`) y la contraseña que definiste para el administrador inicial `postgres`.

En pgAdmin, conéctate al servidor local como `postgres`. Crea un usuario de aplicación separado en **Login/Group Roles → Create → Login/Group Role**:

- Name: `oficiosya_app`.
- En **Definition**, define una contraseña local.
- En **Privileges**, habilita **Can login**. No necesita ser superusuario.

Abre el Query Tool con el administrador `postgres` y ejecuta estas sentencias **una por vez** (PostgreSQL no permite crear una base dentro de una transacción):

```sql
CREATE DATABASE oficiosya OWNER oficiosya_app;
```

```sql
CREATE DATABASE oficiosya_test OWNER oficiosya_app;
```

La base `oficiosya_test` es solo para pruebas automatizadas. La suite elimina y recrea sus tablas, nunca debe configurarse como `oficiosya`.

### 3. Preparar `.env`

Si el archivo local no existe, copia la plantilla:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Abre `.env` en Visual Studio Code y configura la cuenta creada, su contraseña y la base local. Por ejemplo:

```dotenv
DATABASE_URL=postgresql+psycopg://oficiosya_app:TU_PASSWORD_LOCAL@127.0.0.1:5432/oficiosya
SECRET_KEY=PEGA_AQUI_UNA_CLAVE_ALEATORIA_LARGA
FLASK_DEBUG=0
SESSION_COOKIE_SECURE=0
TEST_DATABASE_URL=postgresql+psycopg://oficiosya_app:TU_PASSWORD_LOCAL@127.0.0.1:5432/oficiosya_test
```

Genera una clave secreta aleatoria en PowerShell con:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copia el resultado en `SECRET_KEY`. Reemplaza `TU_PASSWORD_LOCAL`. Para evitar errores al principio, usa una contraseña de desarrollo con letras y números; los caracteres especiales de una URL deben codificarse. No pegues credenciales en el código ni las compartas. En `.env.example` solo hay marcadores de posición.

### 4. Instalar paquetes y preparar el esquema

Con `.venv` activo:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Aplica la migración existente y carga el catálogo de oficios, zonas y categorías:

```powershell
python -m flask --app app db upgrade
python -m flask --app app seed-references
```

`db upgrade` crea las tablas a partir de `migrations/`; no uses `db.create_all()` como sustituto de las migraciones.

### 5. Crear administrador y datos ficticios

El registro web no permite crear administradores. Crea uno desde la terminal; el comando pide los datos y oculta la contraseña:

```powershell
python -m flask --app app create-admin
```

Para una exposición puedes cargar perfiles, servicios y un proyecto ficticios. El comando pide una contraseña compartida por los perfiles demo:

```powershell
python -m flask --app app seed-demo
```

Si ya existen usuarios, `seed-demo` no agrega cambios. Las cuentas demo tienen correos `@oficiosya.test`; guarda la contraseña elegida para entrar.

### 6. Arrancar y detener Flask

```powershell
python app.py
```

Abre **http://127.0.0.1:5000** en el navegador. Deja la terminal abierta mientras uses la aplicación. Para detener el servidor presiona `Ctrl+C` en esa terminal.

## Funcionalidades disponibles

- Registro e inicio de sesión para clientes, trabajadores y empresas; el identificador público o correo se combina con una contraseña.
- Perfiles de trabajadores con múltiples oficios, varias zonas y categorías Hogar/Empresarial.
- Búsqueda por oficio/categoría, zona y categoría de servicio; BFS distingue la zona seleccionada de las zonas vecinas conectadas.
- Solicitudes de servicios con estados pendiente, en proceso, finalizada y cancelada. Cada trabajador atiende en orden FIFO.
- Valoraciones de 1 a 5 una vez finalizado un servicio. La base impide una segunda valoración del mismo servicio.
- Solicitudes de nuevos oficios con detección de nombres iguales o parecidos. El administrador aprueba o rechaza; solo los aprobados entran al catálogo.
- Perfil empresarial, proyectos con oficios, cantidad, ubicación, fecha, duración y presupuesto; trabajadores compatibles pueden postularse.
- Las empresas solo editan, eliminan, cambian estado o resuelven postulaciones de sus propios proyectos. Solo se elimina un proyecto abierto sin postulaciones aceptadas.
- Administración de cuentas y catálogo reservada al rol administrador.
- La vista académica también requiere administrador, porque muestra estructuras, identidades y registros. Una acción de la pila solo puede deshacerla la cuenta que la realizó si sigue compatible y en la cima.

## Estructuras académicas: dónde participan

- **POO:** `Usuario` es la base ORM; `Cliente`, `Trabajador`, `Empresa` y `Administrador` son tipos relacionados. `Plataforma` coordina validaciones y reglas.
- **Listas enlazadas propias:** en `estructuras.py`; `Plataforma.reconstruir_indices()` mantiene las colecciones runtime de clientes, trabajadores y solicitudes para la vista y recorridos académicos. PostgreSQL conserva la fuente duradera.
- **Cola FIFO:** cada trabajador recibe una `ColaFIFO` reconstruida con servicios pendientes ordenados por fecha e ID. `Plataforma.atender_siguiente()` compara y atiende su primera solicitud.
- **Pila LIFO:** `PilaLIFO` registra operaciones reversibles en memoria. `deshacer(actor_id)` examina solo la cima y no permite revertir acciones de otra cuenta ni estados incompatibles.
- **Árbol general:** `ArbolOficios` se hidrata desde `offices`. `descendientes()` incluye el nodo elegido y sus hijos; `trabajadores_disponibles()` lo usa para filtrar por categoría padre.
- **Grafo no dirigido y BFS:** `GrafoZonas` se reconstruye desde `zones` y `zone_connections`. BFS calcula distancia 0 en la zona de origen y distancia 1 para vecinas si el filtro las incluye.
- **Tabla hash propia:** `TablaHash` indexa los identificadores públicos en buckets con encadenamiento y rehash. El login por identificador y `Plataforma.buscar_usuario()` consultan el hash; el login por correo usa la columna indexada de SQL.

Los modelos relacionales usan listas ORM y SQL para persistencia y relaciones. Eso no reemplaza las implementaciones propias que intervienen en las búsquedas y demostraciones académicas.

## Migraciones de esquema

Cuando cambies modelos, crea una revisión y revísala antes de aplicarla:

```powershell
python -m flask --app app db migrate -m "describe el cambio"
python -m flask --app app db upgrade
```

Para ver la revisión aplicada:

```powershell
python -m flask --app app db current
```

No edites una migración que ya aplicaste en una base compartida; crea una revisión nueva. La versión entregada contiene la revisión inicial `412ae3696843`.

## Pruebas automatizadas

Las pruebas requieren que PostgreSQL esté iniciado si `TEST_DATABASE_URL` en `.env` apunta a PostgreSQL. La base debe existir y su nombre debe terminar en `_test` (por ejemplo `oficiosya_test`). La suite valida este límite antes de borrar tablas.

```powershell
python -m unittest -v
```

Comprueba estructuras, registro y hash, relaciones de oficios, filtro por categoría/zona y BFS, similitud de propuestas, aprobación/rechazo, orden FIFO, estados, valoraciones duplicadas, deshacer, empresas/proyectos/postulaciones, permisos, renderizado de rutas y persistencia al crear otra instancia sobre SQLite temporal. Ejecutar la suite con `TEST_DATABASE_URL` PostgreSQL valida también los modelos y operaciones sobre esa base aislada. No apuntes la variable al nombre `oficiosya`.

Para hacer una verificación rápida del esquema migrado, después de preparar PostgreSQL:

```powershell
python -m flask --app app db check
```

## Copias de seguridad y restauración

Los scripts necesitan `pg_dump`/`pg_restore` instalados junto con PostgreSQL y accesibles por `PATH`. Si no lo están, define `POSTGRES_BIN` en la terminal actual con la carpeta `bin` de PostgreSQL:

```powershell
$env:POSTGRES_BIN = "C:\Program Files\PostgreSQL\VERSION\bin"
```

Crea el respaldo desde la raíz del proyecto:

```powershell
python scripts/backup_db.py
```

El respaldo se guarda en `backups/` con fecha y extensión `.dump`. Para restaurar, indica la ruta del archivo y confirma escribiendo `RESTAURAR` cuando se solicite:

```powershell
python scripts/restore_db.py .\backups\oficiosya_AAAAmmdd_HHMMSS.dump
```

La restauración reemplaza objetos de la base local indicada por `DATABASE_URL`. Revisa dos veces el destino antes de confirmar. El script rechaza destinos PostgreSQL remotos.

## Uso paso a paso para probar desde el navegador

1. Entra a inicio y filtra por `Electricidad`, zona `Asunción` y categoría `Hogar`; activa y desactiva zonas vecinas para observar la diferencia BFS.
2. Registra un cliente y anota el identificador emitido. Cierra sesión y vuelve a entrar con el correo o ID y contraseña.
3. Registra un trabajador con varios oficios, zonas y categorías. Abre su perfil y verifica las relaciones; también prueba editar el perfil.
4. Como cliente, abre el perfil del trabajador, completa el servicio y envíalo. En el panel del trabajador verifica su posición en la cola.
5. Si hay más de una solicitud, intenta atender la segunda primero y confirma que la aplicación indica cuál es la siguiente. Atiende en orden y finaliza el servicio.
6. Vuelve al cliente, registra una puntuación y comentario. Intenta valorar de nuevo el mismo servicio para comprobar la restricción.
7. Como trabajador, envía una solicitud de oficio y revisa su estado. Entra como administrador y apruébala o recházala; confirma que el catálogo cambia solo al aprobar.
8. Como empresa, publica un proyecto. Como trabajador compatible, consulta el detalle y postúlate. Como empresa, revisa la postulación y acéptala o recházala.
9. Cambia de empresa e intenta abrir o modificar el proyecto ajeno. El backend debe responder con acceso denegado.
10. Entra como administrador a **Vista académica** para mostrar árbol, zonas/grafo, buckets, cola FIFO, pila LIFO, listas enlazadas y registros persistidos.
11. Crea desde la cuenta administradora una subcategoría y usa Deshacer mientras esa acción siga en la cima. El panel impide deshacer una acción de otra cuenta.

## Seguridad y preparación para publicación futura

- Contraseñas guardadas con `werkzeug.security` como hash; no se recuperan en texto plano.
- Formularios POST protegidos por CSRF con Flask-WTF. No se utiliza GET para cambiar estados.
- Las rutas validan rol en el servidor; las plantillas no son el control de acceso.
- Consultas ORM parametrizadas, llaves foráneas, restricciones de estado y relaciones únicas reducen errores de integridad e inyección SQL.
- `SECRET_KEY`, `DATABASE_URL`, `TEST_DATABASE_URL` y `SESSION_COOKIE_SECURE` son variables de entorno. `SESSION_COOKIE_SECURE=0` es para HTTP local; detrás de HTTPS en un entorno futuro debe ser `1`.
- Para una futura publicación se puede reemplazar `DATABASE_URL` por una URL remota PostgreSQL sin cambiar los modelos. Antes de exponerlo habría que revisar HTTPS/proxy, permisos y backups, secretos, política de sesiones, límites, monitoreo, actualizaciones y despliegue; esta versión no configura un servidor público.

## Errores frecuentes

- **“Base de datos no disponible”:** confirma que el servicio PostgreSQL esté iniciado, que `oficiosya` exista y que usuario, contraseña, host y puerto coincidan con `.env`.
- **Contraseña con `@`, `:` o `/`:** codifica esos caracteres para URL o usa temporalmente una clave local de letras y números.
- **“SECRET_KEY”:** completa `SECRET_KEY` en `.env` y vuelve a iniciar la aplicación.
- **No encuentra `flask`:** activa `.venv` o llama `.\.venv\Scripts\python.exe -m flask`.
- **No encuentra `pg_dump`:** agrega la carpeta `bin` al `PATH` o configura `POSTGRES_BIN` como se mostró arriba.
- **Error de migración “relation already exists”:** revisa `flask db current` antes de ejecutar; no combines `db.create_all()` con las migraciones.
- **Error de acceso a `oficiosya_test`:** crea la base separada, revisa `TEST_DATABASE_URL` y asegúrate de que termina en `_test`.
- **PowerShell no activa el entorno:** usa `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` solo en esa terminal o ejecuta directamente el Python de `.venv`.

## Limitaciones actuales

- Aún debe instalarse y configurarse PostgreSQL en la computadora de ejecución; la conexión real PostgreSQL depende de ese servicio y de las credenciales locales.
- La pila LIFO no es persistente y se vacía cuando se reinicia Flask.
- La comparación de oficios parecidos usa una similitud de texto heurística; el administrador debe revisar propuestas.
- La cobertura de zonas es un grafo didáctico, no cálculo geográfico de distancia/tiempo.
- No hay recuperación de contraseña, verificación de correo, integración de pagos, notificaciones ni carga de fotos habilitada.
- Los scripts de backup/restore y la migración PostgreSQL deben probarse en la instalación local real con `pg_dump`, `pg_restore` y servicio disponibles.
