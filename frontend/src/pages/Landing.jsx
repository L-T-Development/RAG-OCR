import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Navigation } from '../components/shared/Navigation';
import './Landing.css';

function Landing() {
  const [isVisible, setIsVisible] = useState(false);
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });
  const [activeFeature, setActiveFeature] = useState(0);

  useEffect(() => {
    setIsVisible(true);
    
    const handleMouseMove = (e) => {
      setMousePosition({ x: e.clientX, y: e.clientY });
    };
    
    window.addEventListener('mousemove', handleMouseMove);
    
    // Auto-rotate features
    const interval = setInterval(() => {
      setActiveFeature((prev) => (prev + 1) % 4);
    }, 3000);
    
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      clearInterval(interval);
    };
  }, []);

  const features = [
    {
      icon: 'fa-solid fa-brain',
      title: 'AI-Powered RAG',
      description: 'Advanced Retrieval-Augmented Generation for intelligent document Q&A',
      color: '#6366f1'
    },
    {
      icon: 'fa-solid fa-file-pdf',
      title: 'Smart OCR',
      description: 'Extract and process text from PDFs files',
      color: '#ec4899'
    },
    {
      icon: 'fa-solid fa-code-compare',
      title: 'Document Compare',
      description: 'Compare document versions with detailed change tracking',
      color: '#14b8a6'
    },
    {
      icon: 'fa-solid fa-bolt',
      title: 'Fast Processing',
      description: 'Optimized embeddings for lightning-fast document indexing',
      color: '#f59e0b'
    }
  ];

  const stats = [
    { value: '10x', label: 'Faster Search' },
    { value: '99%', label: 'Accuracy' },
    { value: 'Fast', label: 'Processing' },
    { value: '∞', label: 'Documents' }
  ];

  return (
    <div className="landing-page">
      {/* Animated Background */}
      <div className="bg-gradient"></div>
      <div className="bg-grid"></div>
      <div 
        className="cursor-glow"
        style={{
          left: mousePosition.x - 200,
          top: mousePosition.y - 200
        }}
      ></div>
      
      {/* Floating Particles */}
      <div className="particles">
        {[...Array(20)].map((_, i) => (
          <div key={i} className="particle" style={{
            '--delay': `${i * 0.5}s`,
            '--x': `${Math.random() * 100}%`,
            '--duration': `${15 + Math.random() * 10}s`
          }}></div>
        ))}
      </div>

      {/* Navigation */}
      <Navigation />

      {/* Hero Section */}
      <section className={`hero ${isVisible ? 'visible' : ''}`}>
        <div className="hero-badge">
          <i className="fa-solid fa-sparkles"></i>
          <span>Powered by AI</span>
        </div>
        
        <h1 className="hero-title">
          <span className="title-line">Intelligent Document</span>
          <span className="title-line gradient-text">Analysis & RAG</span>
        </h1>
        
        <p className="hero-subtitle">
          Transform your documents into a searchable knowledge base. 
          Ask questions, compare versions, and extract insights with 
          <span className="highlight"> AI-powered analysis</span>.
        </p>

        <div className="hero-actions">
          <Link to="/workspace" className="cta-primary">
            <span>Get Started</span>
            <i className="fa-solid fa-arrow-right"></i>
          </Link>
          <Link to="/compare" className="cta-secondary">
            <i className="fa-solid fa-code-compare"></i>
            <span>Compare Documents</span>
          </Link>
        </div>

        {/* Stats */}
        <div className="hero-stats">
          {stats.map((stat, index) => (
            <div key={index} className="stat-item" style={{ '--delay': `${index * 0.1}s` }}>
              <span className="stat-value">{stat.value}</span>
              <span className="stat-label">{stat.label}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className={`features-section ${isVisible ? 'visible' : ''}`}>
        <div className="section-header">
          <span className="section-badge">Features</span>
          <h2 className="section-title">Everything You Need</h2>
          <p className="section-subtitle">Powerful tools for document intelligence</p>
        </div>

        <div className="features-grid">
          {features.map((feature, index) => (
            <div 
              key={index}
              className={`feature-card ${activeFeature === index ? 'active' : ''}`}
              onMouseEnter={() => setActiveFeature(index)}
              style={{ '--accent-color': feature.color }}
            >
              <div className="feature-icon">
                <i className={feature.icon}></i>
              </div>
              <h3 className="feature-title">{feature.title}</h3>
              <p className="feature-desc">{feature.description}</p>
              <div className="feature-glow"></div>
            </div>
          ))}
        </div>
      </section>

      {/* How It Works */}
      <section id="about" className="how-section">
        <div className="section-header">
          <span className="section-badge">How It Works</span>
          <h2 className="section-title">Simple Yet Powerful</h2>
        </div>

        <div className="steps-container">
          <div className="step">
            <div className="step-number">01</div>
            <div className="step-content">
              <h3>Upload Documents</h3>
              <p>Drop your PDFs, Word docs, or Excel files into a workspace</p>
            </div>
            <div className="step-icon">
              <i className="fa-solid fa-cloud-arrow-up"></i>
            </div>
          </div>

          <div className="step-connector">
            <div className="connector-line"></div>
            <i className="fa-solid fa-chevron-right"></i>
          </div>

          <div className="step">
            <div className="step-number">02</div>
            <div className="step-content">
              <h3>AI Processing</h3>
              <p>Smart embeddings index your content instantly</p>
            </div>
            <div className="step-icon">
              <i className="fa-solid fa-microchip"></i>
            </div>
          </div>

          <div className="step-connector">
            <div className="connector-line"></div>
            <i className="fa-solid fa-chevron-right"></i>
          </div>

          <div className="step">
            <div className="step-number">03</div>
            <div className="step-content">
              <h3>Ask Anything</h3>
              <p>Chat with your documents using natural language</p>
            </div>
            <div className="step-icon">
              <i className="fa-solid fa-comments"></i>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="cta-section">
        <div className="cta-card">
          <div className="cta-bg"></div>
          <h2>Ready to Transform Your Workflow?</h2>
          <p>Start analyzing documents with AI-powered intelligence</p>
          <Link to="/workspace" className="cta-button">
            <i className="fa-solid fa-rocket"></i>
            <span>Launch RAG-OCR</span>
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="footer-content">
          <div className="footer-brand">
            <div className="logo-icon small">
              <i className="fa-solid fa-cube"></i>
            </div>
            <span>RAG-OCR</span>
          </div>
          <p className="footer-text">
            Built with <i className="fa-solid fa-heart"></i> using React, Django & Ollama
          </p>
          <div className="footer-tech">
            <span className="tech-badge"><i className="fa-brands fa-python"></i> Python</span>
            <span className="tech-badge"><i className="fa-brands fa-react"></i> React</span>
            <span className="tech-badge"><i className="fa-solid fa-database"></i> ChromaDB</span>
            <span className="tech-badge"><i className="fa-solid fa-brain"></i> Ollama</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

export default Landing;
