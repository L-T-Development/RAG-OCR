# RagOcr Frontend (React + Vite)

This is the React frontend for the RagOcr AI Workspace application.

## Prerequisites

- Node.js 18+ 
- npm or yarn
- Django backend running on port 8000

## Setup

### 1. Install dependencies

```bash
cd frontend
npm install
```

### 2. Install Django CORS headers (one time)

```bash
pip install django-cors-headers
```

### 3. Start the development servers

**Terminal 1 - Django Backend (from project root):**
```bash
python manage.py runserver
```

**Terminal 2 - React Frontend (from frontend folder):**
```bash
cd frontend
npm run dev
```

The React app will run on `http://localhost:3000` and proxy API requests to Django on port 8000.

## Project Structure

```
frontend/
├── src/
│   ├── components/       # Reusable UI components
│   │   ├── Navbar.jsx
│   │   ├── Sidebar.jsx
│   │   ├── ChatArea.jsx
│   │   └── FilesPanel.jsx
│   ├── pages/            # Page components
│   │   ├── Home.jsx
│   │   └── Compare.jsx
│   ├── services/         # API service layer
│   │   └── api.js
│   ├── App.jsx           # Main app with routing
│   ├── main.jsx          # Entry point
│   └── index.css         # Global styles
├── index.html
├── package.json
└── vite.config.js
```

## Available Scripts

- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run preview` - Preview production build

## Features

- **Thread Management**: Create, view, and delete threads/subthreads
- **Document Upload**: Upload PDFs and process them with AI
- **AI Chat**: Ask questions about uploaded documents
- **Document Comparison**: Compare two document versions

## API Proxy

The Vite dev server proxies `/api/*` and `/media/*` requests to the Django backend at `http://127.0.0.1:8000`. This is configured in `vite.config.js`.
