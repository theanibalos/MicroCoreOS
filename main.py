import signal
import threading
from dotenv import load_dotenv
from core.kernel import Kernel

def main():
    # 0. Carga Estándar del Entorno (Dotenv)
    # En local lee el .env, en Prod usa las variables del sistema (K8s/Docker)
    load_dotenv()
    
    stop_event = threading.Event()
    app = Kernel()

    def stop_signal_handler(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, stop_signal_handler)
    signal.signal(signal.SIGTERM, stop_signal_handler)

    app.boot()

    print("\n🚀 [MicroOS] Sistema Online. (Ctrl+C para salir)")
    
    stop_event.wait() # Suspensión eficiente del hilo principal

    app.shutdown() # Limpieza final
    print("[MicroOS] Apagado completo. ¡Hasta pronto!")

if __name__ == "__main__":
    main()