import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Navigation } from '../components/shared/Navigation';
import {
  Brain,
  FileSearch,
  GitCompare,
  BarChart3,
  Zap,
  Upload,
  Clock,
  ArrowRight,
  Sparkles,
  ShieldCheck,
  Globe,
  ChevronRight,
} from 'lucide-react';
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
    { icon: Brain, title: 'AI-Powered RAG', desc: 'Advanced Retrieval-Augmented Generation for intelligent document Q&A', color: '#4358F6' },
    { icon: FileSearch, title: 'Smart OCR', desc: 'Extract and process text from PDFs, images, and scanned documents', color: '#7C6FE0' },
    { icon: GitCompare, title: 'Document Compare', desc: 'Compare document versions with detailed line-by-line change tracking', color: '#06B6D4' },
    { icon: BarChart3, title: 'Multi-PDF Reports', desc: 'Match Excel values against multiple PDFs with exportable reports', color: '#10B981' },
    { icon: Zap, title: 'Fast Processing', desc: 'Optimised embeddings for lightning-fast document indexing', color: '#F59E0B' },
  ];

  const steps = [
    { num: '01', title: 'Upload Documents', desc: 'Drop PDFs, Word docs, or Excel files into a workspace thread', icon: Upload },
    { num: '02', title: 'AI Processing', desc: 'Smart embeddings index your content for instant retrieval', icon: Brain },
    { num: '03', title: 'Ask Anything', desc: 'Chat with your documents using natural language', icon: Sparkles },
  ];

  // const stats = [
  //   { value: '10×', label: 'Faster Search' },
  //   { value: '99%', label: 'Accuracy' },
  //   { value: '∞', label: 'Documents' },
  //   { value: '<1s', label: 'Response Time' },
  // ];

  return (
    <div className={`landing ${isVisible ? 'landing--visible' : ''}`}>
      <Navigation />

      {/* ── Hero ── */}
      <section className="landing__hero">
        <div className="landing__hero-inner">
          <div className="landing__badge">
            <Sparkles size={13} />
            <span>Powered by AI · Enterprise Ready</span>
          </div>

          <div>
            <h1 className="landing__hero-title">
              Intelligent Standard Operating Procedures
            </h1>
            <h3 className="landing__hero-title-accent"> Operational Readiness is not achieved in moments of crisis, but through disciplined adherence to Standard Operating Procedures every single day</h3>
          </div>

          <p className="landing__hero-subtitle">
            Transform your standard operating procedures into a searchable knowledge base.
            Ask questions, compare versions, and extract insights with
            AI-powered analysis — built for Through Life Support and Documentation and Training.
          </p>

          <div className="landing__hero-actions">
            <Link to="/workspace" className="landing__cta-primary">
              <Upload size={17} />
              Get Started
              <ArrowRight size={16} />
            </Link>
            {/* <Link to="/compare" className="landing__cta-secondary">
              <GitCompare size={17} />
              Compare Documents
            </Link> */}
          </div>

          {/* Stats bar */}
          {/* <div className="landing__stats">
            {stats.map((s, i) => (
              <div key={i} className="landing__stat">
                <span className="landing__stat-value">{s.value}</span>
                <span className="landing__stat-label">{s.label}</span>
              </div>
            ))}
          </div> */}
        </div>

        {/* Visual card */}
        <div className="landing__hero-visual">
          <div className="landing__demo-card">
            <div className="landing__demo-header">
              <div className="landing__demo-dots">
                <span></span><span></span><span></span>
              </div>
              <span className="landing__demo-filename"></span>
              <span className="landing__demo-badge">AI Active</span>
            </div>
            <div className="landing__demo-chat">
              <div className="landing__demo-msg landing__demo-msg--user">
                What are safety aspects?
              </div>
              <div className="landing__demo-msg landing__demo-msg--ai">
                <div className="landing__demo-ai-header">
                  <Sparkles size={12} />
                  SOP Assistant
                </div>
                Safety Aspects:
                The following aspects are mentioned in the table data:
                <ol>


                  <li>Job Safety Analysis (JSA): Record of site activities, risk involved, and measures to avoid accidents as per HIRA & SOP.</li>
                  <li>Behaviour Based Safety (BBS): Observation of individual's attitude and behavior towards safety culture at work place.</li>
                </ol>
                <div className="landing__demo-sources">
                  <span>📄 Page 12</span>
                  <span>📊 Table 3.1</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section className="landing__features">
        <div className="landing__section-header">
          <span className="landing__section-badge">Features</span>
          <h2 className="landing__section-title">Everything You Need</h2>
          <p className="landing__section-sub">Powerful tools built for document intelligence</p>
        </div>

        <div className="landing__features-grid">
          {features.map((f, i) => {
            const Icon = f.icon;
            return (
              <div
                key={i}
                className={`landing__feature-card${activeFeature === i ? ' landing__feature-card--active' : ''}`}
                onMouseEnter={() => setActiveFeature(i)}
                style={{ '--accent': f.color }}
              >
                <div className="landing__feature-icon" style={{ background: `${f.color}14`, color: f.color }}>
                  <Icon size={22} />
                </div>
                <h3 className="landing__feature-title">{f.title}</h3>
                <p className="landing__feature-desc">{f.desc}</p>
                <ChevronRight size={16} className="landing__feature-arrow" />
              </div>
            );
          })}
        </div>
      </section>

      {/* ── How It Works ── */}
      <section className="landing__steps">
        <div className="landing__section-header">
          <span className="landing__section-badge">How It Works</span>
          <h2 className="landing__section-title">Simple Yet Powerful</h2>
        </div>

        <div className="landing__steps-grid">
          {steps.map((s, i) => {
            const Icon = s.icon;
            return (
              <div key={i} className="landing__step">
                <div className="landing__step-num">{s.num}</div>
                <div className="landing__step-icon">
                  <Icon size={20} />
                </div>
                <h3 className="landing__step-title">{s.title}</h3>
                <p className="landing__step-desc">{s.desc}</p>
                {i < steps.length - 1 && <div className="landing__step-connector" />}
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Trust Badges ── */}
      {/* <section className="landing__trust">
        <div className="landing__trust-item">
          <ShieldCheck size={20} />
          <span>Enterprise Security</span>
        </div>
        <div className="landing__trust-divider" />
        <div className="landing__trust-item">
          <Globe size={20} />
          <span>On-Premise Ready</span>
        </div>
        <div className="landing__trust-divider" />
        <div className="landing__trust-item">
          <Clock size={20} />
          <span>Real-Time Processing</span>
        </div>
        <div className="landing__trust-divider" />
        <div className="landing__trust-item">
          <Zap size={20} />
          <span>Local LLM Support</span>
        </div>
      </section> */}

      {/* ── CTA Section ── */}
      {/* <section className="landing__cta-section">
        <div className="landing__cta-card">
          <h2 className="landing__cta-title">Ready to Transform Your Workflow?</h2>
          <p className="landing__cta-desc">
            Start analysing documents with AI-powered intelligence — no cloud required.
          </p>
          <Link to="/workspace" className="landing__cta-primary landing__cta-primary--large">
            <Upload size={18} />
            Launch Enterprise OCR
            <ArrowRight size={17} />
          </Link>
        </div>
      </section> */}

      {/* ── Footer ── */}
      <footer className="landing__footer">
        {/* <div className="landing__footer-brand">
          <div className="landing__footer-icon">
            <Sparkles size={14} />
          </div>
          <span>Enterprise OCR</span>
        </div> */}
        <p className="landing__footer-text">
          Built with React · Django · ChromaDB · Ollama
        </p>
        <p className="landing__footer-copy">
          Developed by L&T(D&T Dev Team)
        </p>
      </footer>
    </div>
  );
}

export default Landing;
