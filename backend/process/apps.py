from django.apps import AppConfig
import time


class ProcessConfig(AppConfig):
    name = 'process'

    def ready(self):
        """Django startup - auto-configure embedding model"""
        # Only run once (Django calls ready() multiple times during reload)
        if not hasattr(self, '_initialized'):
            self._initialized = True
            
            # Delay to ensure database is ready
            import threading
            
            def init_model():
                """Initialize model after Django is fully ready"""
                time.sleep(0.5)  # Small delay to ensure DB is ready
                print("[APP] Initializing embedding model...")
                
                # Import here to avoid circular imports
                from .models import AppConfig as AppConfigModel
                from . import rag_engine
                
                try:
                    # Check if model path is configured in database
                    saved_path = AppConfigModel.get_value('embedding_model_path', None)
                    
                    if not saved_path:
                        # First time setup - save default relative path to database
                        default_path = "models/all-MiniLM-L6-v2"
                        print(f"[APP] Setting default model path: {default_path}")
                        AppConfigModel.set_value('embedding_model_path', default_path)
                        saved_path = default_path
                    else:
                        print(f"[APP] Using configured model path: {saved_path}")
                    
                    # Load the model
                    if rag_engine.model_manager.load_model(saved_path):
                        print("[APP] ✓ Embedding model ready!")
                    else:
                        print("[APP] Model will load on first use")
                        
                except Exception as e:
                    print(f"[APP] Model auto-config error: {e}")
                    print("[APP] Model will load on first use")
            
            # Run initialization in a thread to avoid blocking Django startup
            threading.Thread(target=init_model, daemon=True).start()
