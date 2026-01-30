import os
from core.base_tool import BaseTool

class ContextTool(BaseTool):
    @property
    def name(self) -> str:
        return "context_manager"

    def setup(self):
        """No requiere inicialización técnica de recursos externos."""
        pass

    def get_interface_description(self) -> str:
        return "Genera automáticamente el manifiesto AI_CONTEXT.md que sirve de manual técnico para la IA."

    def on_boot_complete(self, container):
        """Genera el manifiesto en formato Markdown con estándares de Clean Architecture."""
        
        # 1. Encabezado y Reglas de Arquitectura
        manifest = "# 📜 SYSTEM MANIFEST FOR AI AGENT\n\n"
        manifest += "> **AVISO:** Este archivo es generado automáticamente por el Kernel. No editar manualmente.\n\n"
        
        manifest += "## 🏗️ Estándar de Construcción de Plugins (Single-File Clean Architecture)\n"
        manifest += "Al crear un plugin, el método `execute` debe seguir estrictamente este orden:\n\n"
        manifest += "1. **Extracción y Validación**: Limpiar `kwargs` y validar tipos de datos.\n"
        manifest += "2. **Lógica de Negocio**: Procesamiento, cálculos y uso de modelos del dominio.\n"
        manifest += "3. **Persistencia y Acción**: Uso de tools (`db`, `event_bus`, etc.) para guardar cambios o notificar.\n"
        manifest += "4. **Respuesta**: Retornar un diccionario: `{'success': bool, 'data': ...}` o `{'success': False, 'error': str}`.\n\n"
        
        manifest += "---\n\n"

        # 2. Listado Dinámico de Herramientas
        manifest += "## 🛠️ Herramientas Disponibles (Tools)\n"
        manifest += "Inyectadas mediante el contenedor. Acceso: `self.container.get('nombre_tool')`.\n\n"
        
        for name in container.list_tools():
            # Evitamos que la propia tool de contexto se ensucie a sí misma en el manual si prefieres
            tool = container.get(name)
            health = container.get_health(name)
            status_emoji = "✅" if health["status"] == "OK" else "❌"
            
            manifest += f"### 🔧 Tool: `{name}` (Estado: {status_emoji} {health['status']})\n"
            if health["status"] != "OK":
                manifest += f"> **ALERTA**: {health.get('message', 'Error desconocido')}\n\n"
            
            manifest += "**Interfaz y Capacidades:**\n"
            manifest += f"```text\n{tool.get_interface_description().strip()}\n```\n"
            manifest += "\n"
        
        # 3. Modelos del Dominio (Index via Registry)
        manifest += "## 📦 Modelos del Dominio (Data Structures)\n"
        manifest += "Estructuras de datos registradas. Puedes leer el código directamente en su ruta para detalles.\n\n"
        
        domain_metadata = container.get_domain_metadata()
        for domain_name, data in sorted(domain_metadata.items()):
            manifest += f"### 🧩 Dominios `{domain_name}`\n"
            for key in sorted(data.keys()):
                if key.startswith("model_"):
                    model_name = key.replace("model_", "")
                    manifest += f"- Modelo disponible: `{model_name}`\n"
            manifest += "\n"

        # 4. Escritura del archivo
        try:
            with open("AI_CONTEXT.md", "w", encoding="utf-8") as f:
                f.write(manifest)
            print("[ContextTool] AI_CONTEXT.md actualizado vía Architectural Registry.")
        except Exception as e:
            print(f"[ContextTool] Error al escribir el manifiesto: {e}")