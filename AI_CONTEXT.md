# 📜 SYSTEM MANIFEST FOR AI AGENT

> **AVISO:** Este archivo es generado automáticamente por el Kernel. No editar manualmente.

## 🏗️ Estándar de Construcción de Plugins (Single-File Clean Architecture)
Al crear un plugin, el método `execute` debe seguir estrictamente este orden:

1. **Extracción y Validación**: Limpiar `kwargs` y validar tipos de datos.
2. **Lógica de Negocio**: Procesamiento, cálculos y uso de modelos del dominio.
3. **Persistencia y Acción**: Uso de tools (`db`, `event_bus`, etc.) para guardar cambios o notificar.
4. **Respuesta**: Retornar un diccionario: `{'success': bool, 'data': ...}` o `{'success': False, 'error': str}`.

---

## 🛠️ Herramientas Disponibles (Tools)
Inyectadas mediante el contenedor. Acceso: `self.container.get('nombre_tool')`.

### 🔧 Tool: `logger` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Herramienta de Logs:
        - info(message): Registra información general.
        - error(message): Registra errores críticos.
        - warning(message): Registra advertencias.
```

### 🔧 Tool: `db` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Herramienta SQLite (db):
        - query(sql, params): Consulta de lectura (SELECT).
        - execute(sql, params): Escritura (INSERT, UPDATE, DELETE).
```

### 🔧 Tool: `event_bus` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Permite publicar eventos con .publish(nombre, datos) y suscribirse con .subscribe(nombre, callback).
```

### 🔧 Tool: `context_manager` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Genera automáticamente el manifiesto AI_CONTEXT.md que sirve de manual técnico para la IA.
```

### 🔧 Tool: `http_server` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Herramienta HTTP Server:
        - add_endpoint(path, method, handler): Registra una nueva URL.
        - El 'handler' debe ser una función que reciba datos (dict) y retorne un dict.
        - Los datos se extraen de JSON body o Query Params automáticamente.
```

### 🔧 Tool: `config` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Herramienta de Configuración (config):
        - get(key, default=None): Obtiene un valor de configuración.
```

### 🔧 Tool: `auth` (Estado: ✅ OK)
**Interfaz y Capacidades:**
```text
Herramienta de Autenticación (auth):
        - verify_token(token): Verifica si un token es válido (SIMULADO).
        - get_user_from_token(token): Retorna datos del usuario (SIMULADO).
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

### 🧩 Dominios `users`
- Modelo disponible: `user_model.py`

