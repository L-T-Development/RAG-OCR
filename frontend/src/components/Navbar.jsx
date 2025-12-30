import { Link } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { api } from '../services/api';
import './Navbar.css';

function Navbar() {
  const [modelStatus, setModelStatus] = useState(null);

  useEffect(() => {
    const checkModelStatus = async () => {
      try {
        const result = await api.getModelStatus();
        if (result.ok) {
          setModelStatus(result.data);
        }
      } catch (error) {
        console.error('Failed to check model status:', error);
      }
    };

    checkModelStatus();
    // Check status every 30 seconds
    const interval = setInterval(checkModelStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  const getStatusColor = () => {
    if (!modelStatus) return '#888';
    if (modelStatus.loaded) return '#4caf50';
    if (modelStatus.error) return '#f44336';
    return '#ff9800';
  };

  const getStatusTitle = () => {
    if (!modelStatus) return 'Model status unknown';
    if (modelStatus.loaded) return `Model loaded (${modelStatus.device?.toUpperCase()})`;
    if (modelStatus.error) return `Model error: ${modelStatus.error}`;
    return 'Model not configured';
  };

  return (
    <nav className="navbar">
      <Link to="/" className="navbar-brand">
        <div className="brand-icon">
          <i className="fa-solid fa-cube"></i>
        </div>
        <span className="brand-text">RAG<span className="brand-accent">OCR</span></span>
        <span className="brand-divider">|</span>
        <span className="brand-subtitle">Workspace</span>
      </Link>
      <div className="navbar-actions">
        <Link to="/compare" className="nav-action-btn">
          <i className="fa-solid fa-code-compare"></i>
          <span>Compare</span>
        </Link>
        <Link to="/settings" className="nav-action-btn nav-settings" title={getStatusTitle()}>
          <i className="fa-solid fa-gear"></i>
          <span>Settings</span>
          <span 
            className="model-status-dot" 
            style={{ backgroundColor: getStatusColor() }}
            title={getStatusTitle()}
          />
        </Link>
        <Link to="/" className="nav-action-btn nav-home">
          <i className="fa-solid fa-house"></i>
          <span>Home</span>
        </Link>
      </div>
    </nav>
  );
}

export default Navbar;
