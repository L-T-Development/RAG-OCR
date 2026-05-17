import threading
import time

from django.apps import AppConfig


class ProcessConfig(AppConfig):
    name = "process"

    def ready(self):
        """Auto-initialize the Ollama embedding model after Django starts."""
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        def _init():
            time.sleep(0.5)  # wait for DB to be ready
            print("[APP] Initializing embedding model...")
            try:
                from .models import AppConfig as Cfg
                from .pipeline import DEFAULT_OLLAMA_EMBEDDING_MODEL, model_manager

                model_name = Cfg.get_value("ollama_embedding_model", DEFAULT_OLLAMA_EMBEDDING_MODEL)
                if not model_name:
                    model_name = DEFAULT_OLLAMA_EMBEDDING_MODEL
                    Cfg.set_value("ollama_embedding_model", model_name)

                print(f"[APP] Loading Ollama model: {model_name}")
                if model_manager.load_model(model_name):
                    print("[APP] Ollama embedding model ready")
                else:
                    print("[APP] Ollama model will load on first use")

            except Exception as e:
                import traceback
                print(f"[APP] Model init error: {e}")
                traceback.print_exc()
                print("[APP] Model will load on first use")

        threading.Thread(target=_init, daemon=True).start()
