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

export function Navigation({ compact = false }) {
  const location = useLocation();
  const { theme, toggleTheme } = useTheme();

  const isActive = (path) => location.pathname === path;

  const linkBase =
    'flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md no-underline transition-colors';
  const linkActive =
    'text-primary border-b-2 border-primary font-medium';
  const linkInactive =
    'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)]';

  return (
    <nav
      className={`fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-4 bg-[var(--color-bg-primary)] border-b border-[var(--color-border)] shadow-sm ${compact ? 'h-10' : 'h-14'}`}
    >
      {/* Left side */}
      <div className="flex items-center gap-6">
        <Link to="/" className="flex items-center gap-2 no-underline">
          <div className="flex items-center justify-center w-7 h-7 rounded-md bg-primary text-white">
            <Sparkles size={18} />
          </div>
          <span className="font-semibold text-base text-[var(--color-text-primary)]">RAG-OCR</span>
        </Link>

        <div className="flex items-center gap-1">
          <Link to="/" className={`${linkBase} ${isActive('/') ? linkActive : linkInactive}`}>
            <Home size={16} />
            Home
          </Link>
          <Link to="/workspace" className={`${linkBase} ${isActive('/workspace') ? linkActive : linkInactive}`}>
            <MessageSquare size={16} />
            Chat
          </Link>
          <Link to="/compare" className={`${linkBase} ${isActive('/compare') ? linkActive : linkInactive}`}>
            <GitCompare size={16} />
            Compare
          </Link>
          <Link to="/reports" className={`${linkBase} ${isActive('/reports') ? linkActive : linkInactive}`}>
            <FileBarChart size={16} />
            Reports
          </Link>
        </div>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-1">
        <button
          className="flex items-center justify-center w-8 h-8 rounded-md text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] transition-colors cursor-pointer border-0 bg-transparent"
          onClick={toggleTheme}
          title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
        >
          {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
        </button>
        <Link
          to="/settings"
          className="flex items-center justify-center w-8 h-8 rounded-md text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] transition-colors no-underline"
          title="Settings"
        >
          <Settings size={18} />
        </Link>
      </div>
    </nav>
  );
}

export default Navigation;
