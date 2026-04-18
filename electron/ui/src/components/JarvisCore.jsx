import React, { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';

/*──────────────────────────────────────────────────────────────
  JarvisCore – Iron Man HUD central AI interface
  Pure SVG + CSS @keyframes for jitter-free 60fps rotation.
  Framer Motion only for the text glow (opacity/shadow pulses).
──────────────────────────────────────────────────────────────*/

/* ── inline <style> injected once ── */
const CORE_STYLES = `
  @keyframes jarvis-spin-cw-slow {
    from { transform: translate(-50%,-50%) rotate(0deg); }
    to   { transform: translate(-50%,-50%) rotate(360deg); }
  }
  @keyframes jarvis-spin-ccw {
    from { transform: translate(-50%,-50%) rotate(0deg); }
    to   { transform: translate(-50%,-50%) rotate(-360deg); }
  }
  @keyframes jarvis-spin-cw-mid {
    from { transform: translate(-50%,-50%) rotate(0deg); }
    to   { transform: translate(-50%,-50%) rotate(360deg); }
  }
  @keyframes jarvis-spin-ccw-fast {
    from { transform: translate(-50%,-50%) rotate(0deg); }
    to   { transform: translate(-50%,-50%) rotate(-360deg); }
  }
  @keyframes jarvis-glow-pulse {
    0%,100% { opacity: 0.12; transform: translate(-50%,-50%) scale(1); }
    50%     { opacity: 0.22; transform: translate(-50%,-50%) scale(1.04); }
  }
  .jarvis-ring {
    position: absolute;
    top: 50%; left: 50%;
    border-radius: 50%;
  }
  .jarvis-ring svg {
    width: 100%; height: 100%;
    overflow: visible;
  }
  .ring-1 {
    width: 440px; height: 440px;
    animation: jarvis-spin-cw-slow 60s linear infinite;
  }
  .ring-2 {
    width: 400px; height: 400px;
    animation: jarvis-spin-ccw 20s linear infinite;
  }
  .ring-3 {
    width: 340px; height: 340px;
    animation: jarvis-spin-cw-mid 12s linear infinite;
  }
  .ring-4 {
    width: 280px; height: 280px;
    animation: jarvis-spin-ccw-fast 35s linear infinite;
  }
  .ring-5 {
    width: 220px; height: 220px;
    animation: jarvis-spin-cw-slow 50s linear infinite;
  }
`;

export default function JarvisCore() {
  const styleInjected = useRef(false);

  useEffect(() => {
    if (styleInjected.current) return;
    const s = document.createElement('style');
    s.textContent = CORE_STYLES;
    document.head.appendChild(s);
    styleInjected.current = true;
  }, []);

  return (
    <div className="relative flex h-full w-full items-center justify-center select-none">

      {/* ── subtle ambient glow behind the core ── */}
      <div
        style={{
          position: 'absolute', top: '50%', left: '50%',
          width: 420, height: 420, borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(0,246,255,0.13) 0%, rgba(0,246,255,0.04) 40%, transparent 70%)',
          animation: 'jarvis-glow-pulse 4s ease-in-out infinite',
          pointerEvents: 'none',
        }}
      />

      {/* ═══ RING 1 — Outermost dotted track + tick marks ═══ */}
      <div className="jarvis-ring ring-1">
        <svg viewBox="0 0 440 440">
          {/* dotted circle */}
          <circle cx="220" cy="220" r="215" fill="none"
            stroke="#00f6ff" strokeWidth="0.8"
            strokeDasharray="2 6" opacity="0.45" />
          {/* 8 tick marks around the outer edge */}
          {[0,45,90,135,180,225,270,315].map(a => {
            const rad = (a * Math.PI) / 180;
            const x1 = 220 + 210 * Math.cos(rad);
            const y1 = 220 + 210 * Math.sin(rad);
            const x2 = 220 + 218 * Math.cos(rad);
            const y2 = 220 + 218 * Math.sin(rad);
            return <line key={a} x1={x1} y1={y1} x2={x2} y2={y2}
              stroke="#00f6ff" strokeWidth="1.5" opacity="0.6" />;
          })}
        </svg>
      </div>

      {/* ═══ RING 2 — Main thick glowing arcs ═══ */}
      <div className="jarvis-ring ring-2">
        <svg viewBox="0 0 400 400">
          <defs>
            <filter id="arc-glow">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          {/* Arc A — ~120° */}
          <circle cx="200" cy="200" r="190" fill="none"
            stroke="#00f6ff" strokeWidth="3.5"
            strokeDasharray="320 880" strokeLinecap="round"
            filter="url(#arc-glow)" />
          {/* Arc B — ~90° offset */}
          <circle cx="200" cy="200" r="190" fill="none"
            stroke="#0bebc4" strokeWidth="2.8"
            strokeDasharray="240 960" strokeDashoffset="-440"
            strokeLinecap="round" filter="url(#arc-glow)" />
          {/* Arc C — short accent */}
          <circle cx="200" cy="200" r="190" fill="none"
            stroke="#00f6ff" strokeWidth="2.2"
            strokeDasharray="140 1060" strokeDashoffset="-800"
            strokeLinecap="round" filter="url(#arc-glow)" />
          {/* Small dots at arc tips (decorative) */}
          <circle cx="200" cy="10" r="4" fill="#00f6ff" opacity="0.9" filter="url(#arc-glow)" />
          <circle cx="390" cy="200" r="3" fill="#0bebc4" opacity="0.8" filter="url(#arc-glow)" />
        </svg>
      </div>

      {/* ═══ RING 3 — Orbiting particles + thin track ═══ */}
      <div className="jarvis-ring ring-3">
        <svg viewBox="0 0 340 340">
          <circle cx="170" cy="170" r="165" fill="none"
            stroke="#00f6ff" strokeWidth="0.5" opacity="0.25" />
          {/* 5 orbiting dots */}
          {[0, 72, 144, 216, 288].map((angle, i) => {
            const rad = (angle * Math.PI) / 180;
            const cx = 170 + 165 * Math.cos(rad);
            const cy = 170 + 165 * Math.sin(rad);
            const r = i % 2 === 0 ? 3.5 : 2.5;
            return (
              <circle key={angle} cx={cx} cy={cy} r={r}
                fill={i % 2 === 0 ? "#00f6ff" : "#0bebc4"}
                opacity="0.85" />
            );
          })}
          {/* Short arc segments (thinner) */}
          <circle cx="170" cy="170" r="155" fill="none"
            stroke="#00f6ff" strokeWidth="1.5"
            strokeDasharray="60 120 40 120 30 120" strokeLinecap="round"
            opacity="0.55" />
        </svg>
      </div>

      {/* ═══ RING 4 — Inner segmented ring ═══ */}
      <div className="jarvis-ring ring-4">
        <svg viewBox="0 0 280 280">
          <defs>
            <filter id="inner-glow">
              <feGaussianBlur stdDeviation="2" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          <circle cx="140" cy="140" r="132" fill="none"
            stroke="#00f6ff" strokeWidth="1.8"
            strokeDasharray="30 15 10 15" opacity="0.7"
            filter="url(#inner-glow)" />
          <circle cx="140" cy="140" r="122" fill="none"
            stroke="#0bebc4" strokeWidth="0.6"
            strokeDasharray="4 8" opacity="0.35" />
        </svg>
      </div>

      {/* ═══ RING 5 — Innermost thin ring ═══ */}
      <div className="jarvis-ring ring-5">
        <svg viewBox="0 0 220 220">
          <circle cx="110" cy="110" r="105" fill="none"
            stroke="#00f6ff" strokeWidth="0.6"
            strokeDasharray="8 12 4 12" opacity="0.3" />
        </svg>
      </div>

      {/* ═══ CENTER TEXT ═══ */}
      <div className="absolute inset-0 flex flex-col items-center justify-center z-20 pointer-events-none">
        <motion.h1
          animate={{
            opacity: [0.85, 1, 0.85],
            textShadow: [
              '0 0 15px rgba(0,246,255,0.7), 0 0 40px rgba(0,246,255,0.3)',
              '0 0 25px rgba(0,246,255,0.9), 0 0 60px rgba(0,246,255,0.5)',
              '0 0 15px rgba(0,246,255,0.7), 0 0 40px rgba(0,246,255,0.3)',
            ],
          }}
          transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
          className="font-orbitron text-[28px] md:text-[34px] font-bold tracking-[0.3em] text-white"
          style={{ marginLeft: '0.3em' }}
        >
          J.A.R.V.I.S
        </motion.h1>

        <motion.p
          animate={{ opacity: [0.4, 0.9, 0.4] }}
          transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
          className="mt-3 font-mono text-[11px] tracking-[0.3em] text-[#0bebc4] flex items-center gap-2"
          style={{ textShadow: '0 0 10px #0bebc4' }}
        >
          <span className="inline-block w-[5px] h-[5px] rounded-full bg-[#0bebc4]"
                style={{ boxShadow: '0 0 6px #0bebc4' }} />
          AWAITING INPUT
          <span className="inline-block w-[5px] h-[5px] rounded-full bg-[#0bebc4]"
                style={{ boxShadow: '0 0 6px #0bebc4' }} />
        </motion.p>
      </div>
    </div>
  );
}
