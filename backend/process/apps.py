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
                    # Check provider type and model configuration
                    provider = AppConfigModel.get_value('embedding_provider', rag_engine.DEFAULT_EMBEDDING_PROVIDER)
                    print(f"[APP] Using embedding provider: {provider}")
                    
                    if provider == 'ollama':
                        # Use Ollama embedding model
                        ollama_model = AppConfigModel.get_value('ollama_embedding_model', rag_engine.DEFAULT_OLLAMA_EMBEDDING_MODEL)
                        if not ollama_model:
                            ollama_model = rag_engine.DEFAULT_OLLAMA_EMBEDDING_MODEL
                            print(f"[APP] Setting default Ollama model: {ollama_model}")
                            AppConfigModel.set_value('ollama_embedding_model', ollama_model)
                        
                        print(f"[APP] Loading Ollama model: {ollama_model}")
                        if rag_engine.model_manager.load_model(ollama_model, provider_type='ollama'):
                            print("[APP] ✓ Ollama embedding model ready!")
                        else:
                            print("[APP] Ollama model will load on first use")
                    else:
                        # Use sentence-transformers model
                        saved_path = AppConfigModel.get_value('embedding_model_path', None)
                        
                        if not saved_path:
                            # First time setup - save default relative path
                            default_path = rag_engine.DEFAULT_EMBEDDING_MODEL
                            print(f"[APP] Setting default model path: {default_path}")
                            AppConfigModel.set_value('embedding_model_path', default_path)
                            saved_path = default_path
                        else:
                            print(f"[APP] Using configured model path: {saved_path}")
                        
                        # Load the model
                        if rag_engine.model_manager.load_model(saved_path, provider_type='sentence-transformers'):
                            print("[APP] ✓ Embedding model ready!")
                        else:
                            print("[APP] Model will load on first use")
                        
                except Exception as e:
                    print(f"[APP] Model auto-config error: {e}")
                    import traceback
                    traceback.print_exc()
                    print("[APP] Model will load on first use")
            
            # Run initialization in a thread to avoid blocking Django startup
            threading.Thread(target=init_model, daemon=True).start()
