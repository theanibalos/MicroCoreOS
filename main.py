from core.kernel import Kernel

if __name__ == "__main__":
    app = Kernel()
    app.boot()
    
    print("\n--- [Ejecutando Flujo Desacoplado] ---")
    
    # Solo llamamos a UN plugin. El segundo se activará por el Bus de Eventos.
    app.run_plugin("CreateUserPlugin", name="Anibal", email="anibal@example.com")