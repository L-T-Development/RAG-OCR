import { Link } from 'react-router-dom';
import './Navbar.css';

function Navbar() {
  return (
    <nav className="navbar">
      <div className="navbar-brand">
        <i className="fa-solid fa-brain"></i>
        RagOcr Workspace
      </div>
      <Link to="/compare" className="btn btn-primary" style={{ fontSize: '0.8rem' }}>
        <i className="fa-solid fa-code-compare" style={{ marginRight: '6px' }}></i>
        Compare Documents
      </Link>
    </nav>
  );
}

export default Navbar;
