from django.apps import AppConfig


class ProcessConfig(AppConfig):
    name = 'process'

    def ready(self):
        """Django startup - defer model loading for faster startup"""
        # Model will be loaded on first API request (lazy loading)
        print("[APP] Ready (model will load on first request)")
