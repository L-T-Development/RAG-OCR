FROM ollama/ollama:latest

RUN ollama serve & \
    sleep 10 && \
    ollama pull llama3.1:8b && \
    ollama pull nomic-embed-text && \
    pkill ollama

WORKDIR /app

CMD ["serve"]