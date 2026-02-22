import signal
import threading
from dotenv import load_dotenv
from core.kernel import Kernel

def main():
    load_dotenv()

    stop_event = threading.Event()
    app = Kernel()

    def stop_signal_handler(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, stop_signal_handler)
    signal.signal(signal.SIGTERM, stop_signal_handler)

    app.boot()

    print("\n🚀 [MicroCoreOS] System Online. (Ctrl+C to exit)")

    stop_event.wait()

    app.shutdown()
    print("[MicroCoreOS] Shutdown complete. See you soon!")

if __name__ == "__main__":
    main()