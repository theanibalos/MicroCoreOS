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

### 🔧 Tool: `logger`
**Interfaz y Capacidades:**
```text
Herramienta de Logs:
        - info(message): Registra información general.
        - error(message): Registra errores críticos.
        - warning(message): Registra advertencias.
```

### 🔧 Tool: `db`
**Interfaz y Capacidades:**
```text
Herramienta SQLite (db):
        - query(sql, params): Ejecuta una consulta de lectura (SELECT).
        - execute(sql, params): Ejecuta una escritura (INSERT, UPDATE, DELETE).
        - commit(): Guarda los cambios en disco.
```

### 🔧 Tool: `event_bus`
**Interfaz y Capacidades:**
```text
Permite publicar eventos con .publish(nombre, datos) y suscribirse con .subscribe(nombre, callback).
```

### 🔧 Tool: `context_manager`
**Interfaz y Capacidades:**
```text
Genera automáticamente el manifiesto AI_CONTEXT.md que sirve de manual técnico para la IA.
```

### 🔧 Tool: `http_server`
**Interfaz y Capacidades:**
```text
Herramienta HTTP Server:
        - add_endpoint(path, method, handler): Registra una nueva URL.
        - El 'handler' debe ser una función que reciba datos (dict) y retorne un dict.
        - Los datos se extraen de JSON body o Query Params automáticamente.
```

