from django.apps import AppConfig


class ProcessConfig(AppConfig):
    name = 'process'

    def ready(self):
        """Auto-load embedding model when Django starts"""
        import threading
        
        def init_model():
            try:
                from .rag_engine import model_manager
                print("[APP] Auto-loading embedding model...")
                if model_manager.load_model():
                    print("[APP] ✓ Embedding model ready")
                else:
                    print("[APP] ⚠ Model not configured - set path in Settings")
            except Exception as e:
                print(f"[APP] Model init error: {e}")
        
        # Load model in background to not block app startup
        thread = threading.Thread(target=init_model, daemon=True)
        thread.start()
