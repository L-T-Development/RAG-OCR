import { Link } from 'react-router-dom';
import './Navbar.css';

function Navbar() {
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
        <Link to="/" className="nav-action-btn nav-home">
          <i className="fa-solid fa-house"></i>
          <span>Home</span>
        </Link>
      </div>
    </nav>
  );
}

export default Navbar;
