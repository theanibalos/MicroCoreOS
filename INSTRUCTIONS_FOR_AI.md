# 🤖 Guía de Desarrollo para MicroOS

Eres un desarrollador Senior experto en Clean Architecture. Tu misión es extender este sistema siguiendo reglas estrictas de aislamiento, persistencia segura y validación por contrato.
## 🏗️ Arquitectura del Sistema

- **Kernel**: Orquestador ciego. Carga herramientas y plugins. No se modifica.
- **Tools**: Infraestructura agnóstica (`db`, `http_server`, `logger`, `event_bus`). Acceso vía `self.container.get('tool_name')`.
- **Plugins**: Lógica de Casos de Uso. Viven en `domains/{domain}/plugins/`.
- **Models**: Definición de datos y lógica de validación. Viven en `domains/{domain}/models/`.

---

## 📜 Reglas de Oro para Plugins

1.  **Aislamiento Total**: Prohibido importar otros plugins. La comunicación entre dominios es EXCLUSIVAMENTE vía `event_bus`.
2.  **Validación Soberana**: El Plugin es el jefe. Debe validar los `**kwargs` al inicio de `execute` usando los métodos estáticos del Modelo.
3.  **Clean Architecture (Single File)**: El método `execute` debe seguir este orden:
    - **Validación**: Llamar a `Model.validate_field()`.
    - **Lógica**: Procesamiento de datos.
    - **Persistencia**: Uso de Tools (`db`, `logger`, etc.).
    - **Respuesta**: Retornar SIEMPRE un diccionario `{"success": bool, "data": ..., "error": ...}`.

---

## 🧬 Estándar de Modelos y Validación

Los modelos NO son solo contenedores de datos, son los expertos en validación técnica.

- Usa `@staticmethod` para validar campos individuales.
- Retorna siempre una tupla `(bool, error_message)`.

```python
# Ejemplo de Modelo (domains/users/models/user_model.py)
class UserModel:
    def __init__(self, name, email):
        self.name = name
        self.email = email

    @staticmethod
    def validate_email(email):
        if "@" not in str(email): return False, "Email inválido"
        return True, None
```

---

## 🛠️ Uso de Herramientas (Tools)

- **DB**: Usa `db.execute(sql, params)` con parámetros `?` para evitar SQL Injection.
- **HTTP**: Usa `on_boot` para registrar rutas: `http.add_endpoint(path, method, handler)`.
- **EventBus**: Usa `bus.publish(event_name, data)` y `bus.subscribe(event_name, callback)`.

---

## 📝 Plantilla de Plugin Estándar

```python
from core.base_plugin import BasePlugin
from domains.midominio.models.mi_model import MiModel

class MiPlugin(BasePlugin):
    def on_boot(self):
        # Opcional: Registro de rutas o suscripción a eventos
        pass

    def execute(self, **kwargs):
        # 1. Validación (El Plugin decide qué validar)
        ok, err = MiModel.validate_field(kwargs.get("field"))
        if not ok: return {"success": False, "error": err}

        # 2. Lógica y Persistencia
        db = self.container.get("db")
        # ... lógica ...
        return {"success": True, "data": {"status": "procesado"}}
```