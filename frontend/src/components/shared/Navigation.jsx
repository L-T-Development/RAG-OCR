import { Link, useLocation } from 'react-router-dom';
import { useTheme } from '../../context/ThemeContext';
import {
  Sparkles,
  MessageSquare,
  GitCompare,
  Settings,
  Moon,
  Sun,
  Home,
  FileBarChart
} from 'lucide-react';
import './Navigation.css';

export function Navigation({ compact = false }) {
  const location = useLocation();
  const { theme, toggleTheme } = useTheme();

  const isActive = (path) => location.pathname === path;

  return (
    <nav className={`nav ${compact ? 'nav--compact' : ''}`}>
      <div className="nav__left">
        <Link to="/" className="nav__logo">
          <div className="nav__logo-icon">
            <Sparkles size={18} />
          </div>
          <span className="nav__logo-text">RAG-OCR</span>
        </Link>

        <div className="nav__links">
          <Link 
            to="/" 
            className={`nav__link ${isActive('/') ? 'nav__link--active' : ''}`}
          >
            <Home size={16} />
            Home
          </Link>
          <Link 
            to="/workspace" 
            className={`nav__link ${isActive('/workspace') ? 'nav__link--active' : ''}`}
          >
            <MessageSquare size={16} />
            Chat
          </Link>
          {/* <Link 
            to="/compare" 
            className={`nav__link ${isActive('/compare') ? 'nav__link--active' : ''}`}
          >
            <GitCompare size={16} />
            Compare
          </Link> */}
          {/* <Link 
            to="/reports" 
            className={`nav__link ${isActive('/reports') ? 'nav__link--active' : ''}`}
          >
            <FileBarChart size={16} />
            Reports
          </Link> */}
        </div>
      </div>

      <div className="nav__right">
        <button 
          className="nav__btn" 
          onClick={toggleTheme}
          title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
        >
          {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
        </button>
        <Link to="/settings" className="nav__btn" title="Settings">
          <Settings size={18} />
        </Link>
      </div>
    </nav>
  );
}

export default Navigation;
