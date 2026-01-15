# Project Setup Guide (Post-Clone)

## ❌ Missing Files (Expected)
The following are **NOT** in the repository (for efficiency) and need to be set up manually:
- `backend/models/`: The AI model files.
- `backend/local_chroma_db/`: The vector database.
- `backend/db.sqlite3`: The SQL database.
- `.venv/`: The Python virtual environment.
- `node_modules/`: The frontend dependencies.
- `pdfs/`: Your document files.
- `.env`: Environment variables (if any were used).

---

## 🚀 Setup Steps for New Machine

### 1. Backend Setup
1.  **Open Terminal** in `backend/` folder.
2.  **Create Virtual Environment**:
    ```powershell
    python -m venv .venv
    .\.venv\Scripts\Activate
    ```
3.  **Install Dependencies**:
    ```powershell
    pip install -r requirements.txt
    ```
    *(Note: If you have a GPU, run `pip install -r requirements-cuda.txt` instead)*
4.  **Initialize Database**:
    ```powershell
    python manage.py migrate
    ```
    *This recreates the `db.sqlite3` file.*
5.  **AI Model**:
    The system uses `all-MiniLM-L6-v2`. It will try to load from `backend/models/`.
    *   **Option A (Automatic):** If the folder is missing, the `sentence-transformers` library usually downloads it to your user cache automatically.
    *   **Option B (Manual):** If the app complains "Embedding model not configured", download the model manually from HuggingFace and place it in `backend/models/all-MiniLM-L6-v2/` OR configure the path in the settings after running the app.

### 2. Frontend Setup
1.  **Open Terminal** in `frontend/` folder.
2.  **Install Dependencies**:
    ```powershell
    npm install
    ```

### 3. Ollama Setup
1.  **Download Ollama** from [ollama.com](https://ollama.com).
2.  **Pull the Model**:
    ```powershell
    ollama pull llama3.1:8b
    ```
3.  **Start Server**: Ensure Ollama is running (`ollama serve`).

### 4. Running the App
1.  **Backend**: `python manage.py runserver`
2.  **Frontend**: `npm run dev`

### 5. Data Restoration
-   The databases are empty. You must **re-upload your PDF files** via the UI.
-   The system will re-process them, populate the SQL DB, and generate new Vector Embeddings.
