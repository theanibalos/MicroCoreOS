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

## 📦 Modelos del Dominio (Data Structures)
Estructuras de datos validadas que representan el negocio.

### 🧩 Domain `users`: `user_model.py`
```python
import re

class UserModel:
    def __init__(self, name=None, email=None, id=None):
        self.id = id
        self.name = name
        self.email = email

    @staticmethod
    def validate_name(name):
        if not name or not isinstance(name, str) or len(name) < 3:
            return False, "Debe tener al menos 3 caracteres."
        return True, None

    @staticmethod
    def validate_email(email):
        regex = r'^[a-z0-9]+[\._]?[a-z0-9]+[@]\w+[.]\w+$'
        if not email or not re.match(regex, email):
            return False, "Formato no válido."
        return True, None

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email}
```

