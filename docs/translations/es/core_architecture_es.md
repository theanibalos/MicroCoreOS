# Arquitectura Core de MicroCoreOS (Explicación Detallada)

Este documento guarda la explicación arquitectónica profunda de los tres pilares centrales de MicroCoreOS, su manejo de concurrencia, tolerancia a fallos y la filosofía detrás del diseño nativo para Agentes IA.

---

## 1. El Tridente del Núcleo (Core)

La arquitectura base se compone de tres archivos que se dividen las responsabilidades de forma perfecta: El **Kernel** (Director), el **Container** (Bodega) y el **Registry** (Pizarra).

### 1.1 `Container` (La Bodega Segura)
El `Container` (`container.py`) actúa como un **Service Locator** enfocado en concurrencia segura.

- **Única responsabilidad:** Guardar instancias de dependencias (Herramientas/Tools) usando su nombre como llave (`"db"`, `"logger"`, `"event_bus"`) y prestárselas a los plugins que las necesiten.
- **Seguridad (Threading):** Usa un candado `threading.RLock()` en todas sus funciones (`register`, `get`, `has_tool`). Esto garantiza que si dos hilos de ejecución intentan acceder al contenedor en el mismo milisegundo exacto, no haya colisiones de memoria que puedan corromper el diccionario interno.
- **Comportamiento Fail-Fast en Lectura:** Si un plugin pide una herramienta usando `self.container.get("db")` y esta no existe, el programa lanza una excepción inmediata para abortar antes de causar daño silencioso.

### 1.2 `Registry` (La Pizarra de Mapeo Activa)
El `Registry` (`registry.py`) es el **Mapeador Activo del Estado** del sistema. No ejecuta nada, solo recibe reportes de los demás componentes.

- **Única responsabilidad:** Centralizar quién está corriendo, quién falló y los metadatos de los dominios, para poder alimentar a los Dashboards de Observabilidad y a los Agentes IA.
- **La Magia: Copy-on-Write (Fotocopias):** 
  En vez de bloquear el sistema entero cuando el Dashboard quiere leer el estado, el Registry usa `copy.deepcopy()`. 
  - **Los que Escriben (El Kernel):** Bloquean la pizarra rápidamente (`_lock`), cambian un dato y se retiran.
  - **Los que Leen (Dashboards/Agentes):** Al llamar a `get_system_dump()`, reciben una "fotocopia" profunda del estado de la memoria. Pueden hacer lo que quieran con esa fotocopia y mandarla por internet, sin afectar los candados ni el rendimiento de la aplicación central.
- **Inteligencia (Contexto de Negocio):** La función `get_domain_metadata()` lee el código crudo de todos los archivos `models.py` en tiempo de arranque y los mantiene en RAM. Esto permite que la IA le pregunte a la memoria de la aplicación *"¿Qué campos tiene la tabla Usuario?"* en 0 milisegundos sin tocar el disco.

### 1.3 `Kernel` (El Director de Orquesta Finito)
El `Kernel` (`kernel.py`) orquesta la carga de archivos, la inyección de dependencias y el inicio seguro.

- **Ciclo de vida (Boot Completo):**
  1. **Inicializa las Herramientas (Locales):** Carga todas las herramientas de `tools/` de forma estrictamente sincrónica una por una. Si una falla en su `.setup()`, anota "FAIL" en el Registry y **no la inserta en el Container**. Sigue adelante, dejando que el sistema sobreviva.
  2. **Levanta y Verifica Plugins:** Lee los `plugins/`. Revisa sus constructores con introspección para ver qué herramientas piden (Ej: pide "db"). Si la herramienta necesaria no está en el Container porque falló o no existe, el Plugin es marcado como "DEAD".
  3. **Inicia Hilos (Boot Plugins):** Arranca el método `on_boot()` de cada plugin en un hilo `Daemon` diferente concurrentemente.
  4. **Sincronización Total (Join):** Espera estrictamente a que TODOS los hilos de los plugins terminen de configurar sus rutas web y suscripciones antes de seguir (`for t in boot_threads: t.join()`). **Esto elimina condiciones de carrera por completo**.
  5. **Finalización de Tools:** Avisa a las herramientas (`on_boot_complete()`) que ya pueden arrancar motores pesados (como exponer los puertos HTTP en Uvicorn).
- **Abdicación del Trono:** En cuanto imprime *"System Ready"*, **el Kernel deja de existir activamente**. Solo espera a que aprietes `Ctrl+C` para mandar la señal de apagado (`shutdown()`). El sistema en vivo es gobernado por los Disparadores (Triggers).

---

## 2. Inmortalidad Arquitectónica: Manejo de Excepciones No Capturadas

MicroCoreOS está diseñado en el paradigma **"Resilience through Isolation" (Resiliencia por Aislamiento)** para evitar crashear el servidor si un código de producto (escrito por un humano apresurado o una IA caótica) está mal hecho.

Usa **Tres Escudos de Aislamiento**:

1. **Escudo 1: Falla Rápida en el Arranque (El Kernel)**
   El Kernel aísla fallos letales (mala contraseña en MySQL o mal importado) usando grandes bloques `try/except` envolventes durante el `boot()`. Las piezas defectuosas son omitidas y declaradas "DEAD", permitiendo que el sistema inicie sin ellas para dar servicio en partes no afectadas.

2. **Escudo 2: Tráfico Web y Protocolos HTTP (HttpServerTool)**
   Si el `Route Endpoint` de un plugin lanza un *ValueError* espantoso porque un usuario mandó datos horribles, la excepción viaja de abajo hacia arriba. FastApi (`HttpServerTool`) captura la excepción masiva internamente, guarda el texto del error y **responde con un `HTTP 500 JSON` ordenado**. El hilo web se limpia y sigue aceptando clientes.

3. **Escudo 3: Eventos Asíncronos Rotos (El Aislamiento de Hilos Nativos)**
   - Si se dispara un evento y el callback explota: El `ThreadPoolExecutor` del `EventBus` aísla ese trabajo. El hilo-obrero absorbe la excepción y la silencia (con un print al Log), pero los otros 9 hilos-obreros siguen procesando eventos pacíficamente.
   - Si un hilo paralelo (`threading.Thread()`) lanzado manualmente falla: El Operativo (OS/Linux) caza exclusivamente el hilo rebelde y lo asfixia. **En Python, los errores no cruzan la barrera de los hilos.** El hilo principal (`MainThread`, el servidor web) nunca sabrá de esto, garantizando estabilidad masiva al núcleo.

---

## 3. Filosofía Futura: Contratos e Interfaces y Base de Datos

### 3.1 Interfaces Segregadas (Sin Magia)
El sistema depende completamente del texto estático de los contratos (Por ejemplo: `publisher`, `subscribe`, `query`, `execute`).

Tus componentes base son intercambiables. Dado que todos los Plugins asumen la promesa sintáctica y ocultan cómo funciona adentro, si quisieras migrar tu procesamiento local y síncrono por la versión gigante `Celery/Redis`:
1. Solo reescribes el contenido `.publish()` dentro de una nueva `RedisEventBusTool`.
2. Todos tus Plugins del repositorio mantienen su código intocablemente igual a `self.eb.publish("...", data)`.

**La Inversión de Control** garantiza compatibilidad infinita hacia el futuro.

### 3.2 SQL Crudo y la Libertad de Herramientas (ORMs bienvenidos)

Es común preguntar si no usar un ORM (SQLAlchemy, Prisma) hará imposible migrar de PostgreSQL a otra base en el futuro. **MicroCoreOS usa la Inteligencia Artificial a favor en esta decisión, pero es una arquitectura "Agnóstica por Diseño":**

**La Filosofía por Defecto: SQL Crudo**
MicroCoreOS incluye por defecto una herramienta de SQL crudo por las siguientes razones:
1. **Puro y Directo:** Le ordenas SQL plano, recibes Datos Planos. Todo el control descansa en los índices de la BD, no en CPU de Python.
2. **Refactorización AI:** Si necesitas migrar SQLite a PostgreSQL, las herramientas de IA pueden traducir un bloque gigante de consultas planas de un dialecto a otro en 5 segundos sin errores.
3. **Lenguaje Universal IA:** Las IA escriben "Select *" maravillosamente. Se les dificulta la "sintaxis local" que traen ORMs extraños o APIs propensas a cambios. Escribiendo SQL garantizas que cualquier IA domina tu negocio.

**La Libertad Absoluta: Trae tu propio ORM**
A pesar de la filosofía por defecto, **MicroCoreOS no te prohíbe nada**. 
* Si tu equipo humano prefiere SQLAlchemy o SQLModel, **es 100% bienvenido**.
* Solo tienes que crear un archivo `orm_tool.py`, heredar de `BaseTool`, inicializar el ORM en `setup()`, ¡y listo! Tus plugins pueden empezar a pedir `self.orm` de la bodega y tú seguirás disfrutando de toda la inyección de dependencias y el aislamiento de fallos del Kernel.

El código se mantiene **Cero Boilerplate. Sólido como Roca. Blanco y negro.**, y la decisión final entre SQL y ORM siempre queda en manos del arquitecto de software de cada proyecto específico.
