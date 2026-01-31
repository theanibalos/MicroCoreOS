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
2.  **Inyección de Dependencias (DI)**: Los Plugins NO deben buscar herramientas en el contenedor. Deben pedirlas explícitamente en su constructor `__init__`. El Kernel las inyectará automáticamente basándose en el nombre del parámetro (ej: `db`, `logger`, `event_bus`).
3.  **Validación Soberana**: El Plugin es el jefe. Debe validar los `**kwargs` al inicio de `execute` usando los métodos estáticos del Modelo.
4.  **Clean Architecture (Single File)**: El método `execute` debe seguir este orden:
    - **Validación**: Llamar a `Model.validate_field()`.
    - **Lógica**: Procesamiento de datos.
    - **Persistencia**: Uso de las Tools inyectadas.
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

- **DB**: Usa `self.db.execute(sql, params)` con parámetros `?` para evitar SQL Injection.
- **HTTP**: Usa `self.http.add_endpoint(path, method, handler)`.
- **EventBus**: 
    - `self.bus.publish(name, data)`: Dispara y olvida.
    - `self.bus.subscribe(name, callback)`: Escucha eventos.
    - `self.bus.request(name, data, timeout=5)`: Envía y espera respuesta (RPC).
    - **Patrón Respuesta**: Si recibes un evento con `data.get('_metadata', {}).get('reply_to')`, DEBES publicar la respuesta en ese topic incluyendo el mismo `correlation_id`.

---

## 📝 Plantilla de Plugin Estándar (DI Real)

```python
from core.base_plugin import BasePlugin
from domains.midominio.models.mi_model import MiModel

class MiPlugin(BasePlugin):
    def __init__(self, db, logger, event_bus):
        # El Kernel inyecta automáticamente estas herramientas por su nombre
        self.db = db
        self.logger = logger
        self.bus = event_bus

    def on_boot(self):
        # Suscripción a eventos o registro de rutas
        pass

    def execute(self, **kwargs):
        # 1. Validación
        ok, err = MiModel.validate_field(kwargs.get("field"))
        if not ok: return {"success": False, "error": err}

        # 2. Lógica y Persistencia
        # ... lógica usando self.db ...
        return {"success": True, "data": {"status": "procesado"}}
```

---

## 🔧 Guía para Crear Nuevas Tools

Las Tools son componentes de **Infraestructura** (Base de Datos, APIs externas, Hardware, Memoria).
**NO** deben contener lógica de negocio (eso va en Plugins).

### Checklist de Creación:

1.  **Ubicación**: Crear archivo en `tools/nombre_tool.py`.
2.  **Herencia**: Debe heredar de `core.base_tool.BaseTool`.
3.  **Documentación**: El método `get_interface_description` es **VITAL**. Lo que escribas ahí es lo que la IA leerá en `AI_CONTEXT.md` para saber cómo usar tu tool. Sé explícito con los métodos y parámetros.

### Plantilla de Tool

```python
from core.base_tool import BaseTool

class MiTool(BaseTool):
    @property
    def name(self):
        return "mi_tool"

    def setup(self):
        # Se ejecuta al arranque del Kernel (antes de cargar plugins).
        # Úsalo para conectar DBs, abrir sockets, etc.
        print(f"[{self.name}] Setup completo.")

    def get_interface_description(self):
        # ⚠️ IMPORTANTE: Esto es lo que lee la Inteligencia Artificial.
        return """
        Mi Herramienta (mi_tool):
        - accion_a(param1): Hace algo importante. Retorna dict.
        - accion_b(): Hace otra cosa.
        """

    def shutdown(self):
        # Se ejecuta al apagar el sistema (Ctrl+C).
        print(f"[{self.name}] Cerrando recursos...")

    def on_boot_complete(self, container):
        # (Opcional) Se ejecuta cuando TODO el sistema ya arrancó.
        # Útil si necesitas acceder a otras tools inicializadas.
        pass

    # --- MÉTODOS PÚBLICOS (La API de tu Tool) ---
    
    def accion_a(self, param1):
        return {"result": f"Procesado {param1}"}

    def accion_b(self):
        pass
```