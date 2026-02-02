# 📜 SYSTEM MANIFEST FOR AI AGENT

> **AVISO:** Este archivo es generado automáticamente por el Kernel. No editar manualmente.

## 🏗️ Filosofía y Arquitectura de Ejecución
MicroOS es un sistema modular, asíncrono y resiliente basado en Clean Architecture.

- **Core Resiliente**: El Kernel y Container son el corazón estable. Los fallos en plugins no detienen el sistema.
- **Modelo de Hilos**: Los plugins arrancan en hilos independientes. El Kernel usa `RLock` para seguridad entre hilos.
- **Concurrency Control**: El `event_bus` utiliza un `ThreadPoolExecutor` para manejar eventos de forma eficiente.
- **Inyección de Dependencias**: Los plugins reciben herramientas en el constructor. **Consulta siempre la sección 'Tools' para ver la firma de los métodos.**

## 📐 Estándar de Construcción de Plugins (Single-File Clean Architecture)
Al crear un plugin, el método `execute` debe seguir estrictamente este orden:

1. **Extracción y Validación**: Limpiar `kwargs` y validar tipos de datos usando el Modelo del dominio.
2. **Lógica de Negocio**: Procesamiento, cálculos y uso de lógica interna del dominio.
3. **Persistencia y Acción**: Uso de las tools inyectadas (`self.db`, `self.event_bus`, etc.) para guardar o notificar.
4. **Respuesta**: Retornar un diccionario: `{'success': bool, 'data': ...}` o `{'success': False, 'error': str}`.

---

## 🛠️ Herramientas Disponibles (Tools)
Inyectadas automáticamente por el Kernel. **Debes pedirlas en tu `__init__`** usando el nombre de la tool como parámetro.

### 🔧 Tool: `auth` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Herramienta de Autenticación (auth):
        - verify_token(token): Verifica si un token es válido (SIMULADO).
        - get_user_from_token(token): Retorna datos del usuario (SIMULADO).
```

### 🔧 Tool: `config` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Herramienta de Configuración (config):
        - get(key, default=None): Obtiene un valor de configuración.
```

### 🔧 Tool: `context_manager` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Genera automáticamente el manifiesto AI_CONTEXT.md que sirve de manual técnico para la IA.
```

### 🔧 Tool: `event_bus` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Permite comunicación entre plugins:
        - publish(nombre, datos): Dispara y olvida.
        - subscribe(nombre, callback): Escucha eventos. Usa '*' para escuchar TODOS.
        - request(nombre, datos, timeout=5): Envía y espera respuesta (RPC).
```

### 🔧 Tool: `http_server` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Herramienta HTTP Server (FastAPI):
        - add_endpoint(path, method, handler, tags=None): Registra una nueva URL con tags opcionales.
        - mount_static(path, directory): Sirve archivos estáticos.
        - add_ws_endpoint(path, handler): Registra un endpoint WebSocket.
        - El 'handler' debe recibir un diccionario 'data'.
```

### 🔧 Tool: `logger` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Herramienta de Logs:
        - info(message): Registra información general.
        - error(message): Registra errores críticos.
        - warning(message): Registra advertencias.
        Todos los logs se publican también al event_bus como 'system.log'.
```

### 🔧 Tool: `db` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Herramienta SQLite (db):
        - query(sql, params): Consulta de lectura (SELECT).
        - execute(sql, params): Escritura (INSERT, UPDATE, DELETE).
```

### 🔧 Tool: `state` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Herramienta de Estado (state):
        - set(key, value, namespace='default'): Guarda un valor.
        - get(key, default=None, namespace='default'): Recupera un valor.
        - increment(key, amount=1, namespace='default'): Incremento atómico.
        - delete(key, namespace='default'): Elimina una clave.
```

## 📦 Modelos del Dominio (Data Structures)
Estructuras de datos registradas. Puedes leer el código directamente en su ruta para detalles.

### 🧩 Dominios `home`
- Modelo disponible: `user_model.py`

