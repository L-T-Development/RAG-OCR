import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Navigation } from '../components/shared/Navigation';

function Landing() {
  const [isVisible, setIsVisible] = useState(false);
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });
  const [activeFeature, setActiveFeature] = useState(0);

  useEffect(() => {
    setIsVisible(true);
    const handleMouseMove = (e) => setMousePosition({ x: e.clientX, y: e.clientY });
    window.addEventListener('mousemove', handleMouseMove);
    const interval = setInterval(() => setActiveFeature((prev) => (prev + 1) % 5), 3000);
    return () => { window.removeEventListener('mousemove', handleMouseMove); clearInterval(interval); };
  }, []);

  const features = [
    { icon: 'fa-solid fa-brain',        title: 'AI-Powered RAG',      description: 'Advanced Retrieval-Augmented Generation for intelligent document Q&A',          color: '#6366f1' },
    { icon: 'fa-solid fa-file-pdf',     title: 'Smart OCR',           description: 'Extract and process text from PDFs files',                                        color: '#ec4899' },
    { icon: 'fa-solid fa-code-compare', title: 'Document Compare',    description: 'Compare document versions with detailed change tracking',                          color: '#14b8a6' },
    { icon: 'fa-solid fa-chart-bar',    title: 'Multi-PDF Reports',   description: 'Compare Excel values against multiple PDFs with detailed reports',                 color: '#8b5cf6' },
    { icon: 'fa-solid fa-bolt',         title: 'Fast Processing',     description: 'Optimized embeddings for lightning-fast document indexing',                        color: '#f59e0b' },
  ];

  const stats = [
    { value: '10x', label: 'Faster Search' },
    { value: '99%', label: 'Accuracy' },
    { value: 'Fast', label: 'Processing' },
    { value: '∞',   label: 'Documents' },
  ];

  const steps = [
    { num: '01', icon: 'fa-solid fa-cloud-arrow-up', title: 'Upload Documents', desc: 'Drop your PDFs, Word docs, or Excel files into a workspace' },
    { num: '02', icon: 'fa-solid fa-microchip',      title: 'AI Processing',    desc: 'Smart embeddings index your content instantly' },
    { num: '03', icon: 'fa-solid fa-comments',       title: 'Ask Anything',     desc: 'Chat with your documents using natural language' },
  ];

  const fadeIn = (delay) =>
    `transition-all duration-700 ${delay} ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`;

  const sectionBadge = (label) => (
    <span className="inline-block px-4 py-1.5 rounded-full text-xs uppercase tracking-widest mb-4 border"
      style={{ background: 'rgba(99,102,241,0.1)', borderColor: 'rgba(99,102,241,0.3)', color: '#818cf8' }}>
      {label}
    </span>
  );

  return (
    <div className="min-h-screen bg-[#020617] text-[#f8fafc] overflow-x-hidden relative">

      {/* ── Animated background layers ── */}
      <div className="fixed inset-0 z-0 pointer-events-none" style={{
        background: 'radial-gradient(ellipse 80% 50% at 50% -20%, rgba(99,102,241,0.3), transparent), radial-gradient(ellipse 60% 40% at 100% 100%, rgba(236,72,153,0.2), transparent), radial-gradient(ellipse 40% 30% at 0% 100%, rgba(20,184,166,0.2), transparent)',
      }} />
      <div className="landing-grid" />
      <div className="cursor-glow" style={{ left: mousePosition.x - 200, top: mousePosition.y - 200 }} />

      {/* ── Floating particles ── */}
      <div className="fixed inset-0 overflow-hidden z-0 pointer-events-none">
        {[...Array(20)].map((_, i) => (
          <div key={i} className="particle" style={{
            '--delay': `${i * 0.5}s`,
            '--x': `${Math.random() * 100}%`,
            '--duration': `${15 + Math.random() * 10}s`,
          }} />
        ))}
      </div>

      <Navigation />

      {/* ── Hero ──────────────────────────────────────────────────── */}
      <section className="relative z-[1] min-h-screen flex flex-col items-center justify-center text-center px-6 pt-32 pb-16">

        <div className={`inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm mb-8 border ${fadeIn('delay-100')}`}
          style={{ background: 'rgba(99,102,241,0.1)', borderColor: 'rgba(99,102,241,0.3)', color: '#818cf8' }}>
          <i className="fa-solid fa-sparkles"></i>
          <span>Powered by AI</span>
        </div>

        <h1 className={`font-black leading-none mb-6 ${fadeIn('delay-200')}`}
          style={{ fontSize: 'clamp(2.5rem,8vw,5rem)', letterSpacing: '-2px' }}>
          <span className="block">Intelligent Document</span>
          <span className="block gradient-text">Analysis &amp; RAG</span>
        </h1>

        <p className={`text-xl text-slate-400 max-w-xl leading-relaxed mb-10 ${fadeIn('delay-300')}`}>
          Transform your documents into a searchable knowledge base.
          Ask questions, compare versions, and extract insights with{' '}
          <span className="text-teal-400 font-semibold">AI-powered analysis</span>.
        </p>

        <div className={`flex flex-col sm:flex-row gap-4 mb-16 ${fadeIn('delay-[400ms]')}`}>
          <Link to="/workspace"
            className="flex items-center justify-center gap-2.5 px-8 py-4 rounded-2xl font-semibold text-lg text-white transition-all hover:-translate-y-1 hover:scale-[1.02]"
            style={{ background: 'linear-gradient(135deg,#6366f1,#ec4899)', boxShadow: '0 4px 30px rgba(99,102,241,0.4)' }}>
            <span>Get Started</span>
            <i className="fa-solid fa-arrow-right"></i>
          </Link>
          <Link to="/compare"
            className="flex items-center justify-center gap-2.5 px-8 py-4 rounded-2xl font-semibold text-lg text-[#f8fafc] border border-white/10 backdrop-blur-sm hover:bg-white/10 hover:border-white/20 hover:-translate-y-1 transition-all"
            style={{ background: 'rgba(255,255,255,0.05)' }}>
            <i className="fa-solid fa-code-compare"></i>
            <span>Compare Documents</span>
          </Link>
        </div>

        {/* Stats */}
        <div className={`flex flex-wrap justify-center gap-12 sm:gap-16 pt-8 border-t border-white/10 ${fadeIn('delay-500')}`}>
          {stats.map((s, i) => (
            <div key={i} className="flex flex-col items-center">
              <span className="text-4xl font-black bg-gradient-to-br from-indigo-400 to-teal-400 bg-clip-text text-transparent">{s.value}</span>
              <span className="text-sm text-slate-400 mt-1">{s.label}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ── Features ──────────────────────────────────────────────── */}
      <section id="features"
        className={`relative z-[1] py-24 px-6 sm:px-16 transition-all duration-700 delay-300 ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-12'}`}>
        <div className="text-center mb-16">
          {sectionBadge('Features')}
          <h2 className="text-5xl font-black tracking-tight mb-4">Everything You Need</h2>
          <p className="text-lg text-slate-400">Powerful tools for document intelligence</p>
        </div>

        <div className="grid gap-6 max-w-[1200px] mx-auto"
          style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
          {features.map((feature, index) => {
            const active = activeFeature === index;
            return (
              <div
                key={index}
                className={`relative p-8 border rounded-2xl transition-all duration-300 overflow-hidden cursor-pointer ${active ? '-translate-y-1' : 'hover:-translate-y-1'}`}
                style={{
                  background: active ? 'rgba(255,255,255,0.05)' : 'rgba(255,255,255,0.03)',
                  borderColor: active ? feature.color : 'rgba(255,255,255,0.1)',
                }}
                onMouseEnter={() => setActiveFeature(index)}
              >
                <div className="w-[60px] h-[60px] rounded-2xl flex items-center justify-center text-2xl mb-6 relative z-[1]"
                  style={{ background: `linear-gradient(135deg,${feature.color},transparent)` }}>
                  <i className={feature.icon}></i>
                </div>
                <h3 className="text-xl font-bold mb-3 relative z-[1]">{feature.title}</h3>
                <p className="text-slate-400 leading-relaxed text-sm relative z-[1]">{feature.description}</p>
                {/* glow overlay */}
                <div className="absolute inset-0 transition-opacity duration-300 pointer-events-none"
                  style={{ background: `radial-gradient(circle at 50% 0%,${feature.color},transparent 70%)`, opacity: active ? 0.1 : 0 }} />
              </div>
            );
          })}
        </div>
      </section>

      {/* ── How It Works ──────────────────────────────────────────── */}
      <section id="about" className="relative z-[1] py-24 px-6 sm:px-16">
        <div className="text-center mb-16">
          {sectionBadge('How It Works')}
          <h2 className="text-5xl font-black tracking-tight">Simple Yet Powerful</h2>
        </div>

        <div className="flex items-center justify-center gap-4 max-w-[1200px] mx-auto flex-wrap">
          {steps.map((step, i) => (
            <>
              <div key={step.num}
                className="relative p-8 rounded-2xl border w-[280px] text-center transition-all hover:bg-white/[0.06] hover:-translate-y-1"
                style={{ background: 'rgba(255,255,255,0.03)', borderColor: 'rgba(255,255,255,0.1)' }}>
                <div className="absolute -top-4 left-1/2 -translate-x-1/2 w-9 h-9 rounded-full flex items-center justify-center font-bold text-sm text-white"
                  style={{ background: 'linear-gradient(135deg,#6366f1,#ec4899)' }}>
                  {step.num}
                </div>
                <div className="w-[70px] h-[70px] mx-auto mb-6 rounded-2xl flex items-center justify-center text-[1.8rem]"
                  style={{ background: 'rgba(99,102,241,0.1)', color: '#6366f1' }}>
                  <i className={step.icon}></i>
                </div>
                <h3 className="text-xl font-bold mb-2">{step.title}</h3>
                <p className="text-slate-400 text-sm leading-relaxed">{step.desc}</p>
              </div>
              {i < steps.length - 1 && (
                <div key={`conn-${i}`} className="flex items-center text-indigo-500 opacity-50">
                  <div className="w-10 h-0.5" style={{ background: 'linear-gradient(90deg,#6366f1,#ec4899)' }} />
                  <i className="fa-solid fa-chevron-right"></i>
                </div>
              )}
            </>
          ))}
        </div>
      </section>

      {/* ── CTA ───────────────────────────────────────────────────── */}
      <section className="relative z-[1] py-24 px-6 sm:px-16">
        <div className="relative max-w-[900px] mx-auto px-16 py-16 text-center rounded-[30px] overflow-hidden border border-white/10">
          <div className="absolute inset-0 z-0 pointer-events-none"
            style={{ background: 'linear-gradient(135deg,rgba(99,102,241,0.2),rgba(236,72,153,0.1))' }} />
          <h2 className="text-4xl font-black mb-4 relative z-[1]">Ready to Transform Your Workflow?</h2>
          <p className="text-lg text-slate-400 mb-8 relative z-[1]">Start analyzing documents with AI-powered intelligence</p>
          <Link to="/workspace"
            className="inline-flex items-center gap-2.5 px-10 py-[18px] rounded-2xl font-bold text-lg text-white relative z-[1] transition-all hover:-translate-y-1 hover:scale-105"
            style={{ background: 'linear-gradient(135deg,#6366f1,#ec4899)', boxShadow: '0 4px 30px rgba(99,102,241,0.4)' }}>
            <i className="fa-solid fa-rocket"></i>
            <span>Launch RAG-OCR</span>
          </Link>
        </div>
      </section>

      {/* ── Footer ────────────────────────────────────────────────── */}
      <footer className="relative z-[1] py-12 px-6 sm:px-16 border-t border-white/10">
        <div className="max-w-[1200px] mx-auto flex flex-col items-center gap-4">
          <div className="flex items-center gap-2.5 text-xl font-bold">
            <div className="w-8 h-8 rounded-xl flex items-center justify-center text-sm text-white"
              style={{ background: 'linear-gradient(135deg,#6366f1,#ec4899)' }}>
              <i className="fa-solid fa-cube"></i>
            </div>
            <span>RAG-OCR</span>
          </div>
          <p className="text-slate-400 text-sm">
            Built with <i className="fa-solid fa-heart" style={{ color: '#ec4899' }}></i> using React, Django &amp; Ollama
          </p>
          <div className="flex gap-3 flex-wrap justify-center">
            {[
              { icon: 'fa-brands fa-python', label: 'Python' },
              { icon: 'fa-brands fa-react',  label: 'React' },
              { icon: 'fa-solid fa-database', label: 'ChromaDB' },
              { icon: 'fa-solid fa-brain',   label: 'Ollama' },
            ].map(({ icon, label }) => (
              <span key={label}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs text-slate-400 border border-white/10"
                style={{ background: 'rgba(255,255,255,0.05)' }}>
                <i className={icon}></i> {label}
              </span>
            ))}
          </div>
        </div>
      </footer>
    </div>
  );
}

export default Landing;
