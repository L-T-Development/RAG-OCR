import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Upload, MessageSquare, BarChart3, ArrowRight } from 'lucide-react';
import { Navigation } from '../components/shared/Navigation';
import './Landing.css';

function Landing() {
  const [isVisible, setIsVisible] = useState(false);
  const [activeFeature, setActiveFeature] = useState(0);

  useEffect(() => {
    setIsVisible(true);
    const interval = setInterval(() => {
      setActiveFeature((prev) => (prev + 1) % 5);
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  const features = [
    {
      icon: <MessageSquare size={22} />,
      title: 'RAG Intelligence',
      description: 'Advanced Retrieval-Augmented Generation for intelligent document Q&A',
      color: '#6366f1',
    },
    {
      icon: <Upload size={22} />,
      title: 'Smart OCR',
      description: 'Extract and process text from PDF files with high accuracy',
      color: '#ec4899',
    },
    {
      icon: <BarChart3 size={22} />,
      title: 'Document Compare',
      description: 'Compare document versions with detailed change tracking',
      color: '#14b8a6',
    },
    {
      icon: <BarChart3 size={22} />,
      title: 'Multi-PDF Reports',
      description: 'Compare Excel values against multiple PDFs with detailed reports',
      color: '#8b5cf6',
    },
    {
      icon: <ArrowRight size={22} />,
      title: 'Fast Processing',
      description: 'Optimized embeddings for lightning-fast document indexing',
      color: '#f59e0b',
    },
  ];

  const stats = [
    { value: '10x', label: 'Faster Search' },
    { value: '99%', label: 'Accuracy' },
    { value: 'Fast', label: 'Processing' },
    { value: '∞', label: 'Documents' },
  ];

  const steps = [
    {
      num: '01',
      icon: <Upload size={22} />,
      title: 'Upload Documents',
      desc: 'Drop your PDFs, Word docs, or Excel files into a workspace',
    },
    {
      num: '02',
      icon: <MessageSquare size={22} />,
      title: 'AI Processing',
      desc: 'Smart embeddings index your content instantly',
    },
    {
      num: '03',
      icon: <ArrowRight size={22} />,
      title: 'Ask Anything',
      desc: 'Chat with your documents using natural language',
    },
  ];

  return (
    <div className={`landing ${isVisible ? 'landing--visible' : ''}`}>
      <Navigation />

      {/* Hero */}
      <div className="landing__hero">
        <div className="landing__hero-inner">
          <div className="landing__badge">
            <span>✦</span>
            <span>Powered by AI</span>
          </div>

          <h1 className="landing__hero-title">
            Intelligent Document<br />
            <span className="landing__hero-title-accent">Analysis &amp; RAG</span>
          </h1>

          <p className="landing__hero-subtitle">
            Transform your documents into a searchable knowledge base.
            Ask questions, compare versions, and extract insights with AI-powered analysis.
          </p>

          <div className="landing__hero-actions">
            <Link to="/workspace" className="landing__cta-primary">
              <span>Get Started</span>
              <ArrowRight size={16} />
            </Link>
            <Link to="/compare" className="landing__cta-secondary">
              <span>Compare Documents</span>
            </Link>
          </div>

          <div className="landing__stats">
            {stats.map((stat, i) => (
              <div key={i} className="landing__stat">
                <span className="landing__stat-value">{stat.value}</span>
                <span className="landing__stat-label">{stat.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Features */}
      <section className="landing__features">
        <div className="landing__section-header">
          <span className="landing__section-badge">Features</span>
          <h2 className="landing__section-title">Everything You Need</h2>
          <p className="landing__section-sub">Powerful tools for document intelligence</p>
        </div>

        <div className="landing__features-grid">
          {features.map((feature, i) => (
            <div
              key={i}
              className={`landing__feature-card ${activeFeature === i ? 'landing__feature-card--active' : ''}`}
              onMouseEnter={() => setActiveFeature(i)}
              style={{ '--accent': feature.color }}
            >
              <div className="landing__feature-icon" style={{ background: `${feature.color}22`, color: feature.color }}>
                {feature.icon}
              </div>
              <div className="landing__feature-title">{feature.title}</div>
              <div className="landing__feature-desc">{feature.description}</div>
            </div>
          ))}
        </div>
      </section>

      {/* How It Works */}
      <section className="landing__steps">
        <div className="landing__section-header">
          <span className="landing__section-badge">How It Works</span>
          <h2 className="landing__section-title">Simple Yet Powerful</h2>
        </div>

        <div className="landing__steps-grid">
          {steps.map((step, i) => (
            <div key={i} className="landing__step">
              <div className="landing__step-num">STEP {step.num}</div>
              <div className="landing__step-icon">{step.icon}</div>
              <div className="landing__step-title">{step.title}</div>
              <div className="landing__step-desc">{step.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="landing__cta-section">
        <div className="landing__cta-card">
          <h2 className="landing__cta-title">Ready to Transform Your Workflow?</h2>
          <p className="landing__cta-desc">Start analyzing documents with AI-powered intelligence</p>
          <Link to="/workspace" className="landing__cta-primary landing__cta-primary--large">
            <span>Launch RAG-OCR</span>
            <ArrowRight size={18} />
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="landing__footer">
        <div className="landing__footer-brand">
          <div className="landing__footer-icon">
            <span>R</span>
          </div>
          <span>RAG-OCR</span>
        </div>
        <p className="landing__footer-text">Built with React, Django &amp; Ollama</p>
        <p className="landing__footer-copy">© 2026 RAG-OCR</p>
      </footer>
    </div>
  );
}

export default Landing;
