import React from 'react';
import { motion } from 'framer-motion';

const CentralCore = ({ state = 'IDLE' }) => {
  // Determine color and glow based on state
  const isBusy = state !== 'IDLE';
  const primaryColor = isBusy ? '#0bebc4' : '#00f6ff';
  
  return (
    <div className="relative flex items-center justify-center w-[500px] h-[500px]">
      
      {/* Outer Ring - Dashed */}
      <motion.svg
        className="absolute inset-0 w-full h-full"
        viewBox="0 0 500 500"
        animate={{ rotate: 360 }}
        transition={{ duration: 40, ease: "linear", repeat: Infinity }}
      >
        <circle cx="250" cy="250" r="230" fill="none" stroke={primaryColor} strokeWidth="1" strokeDasharray="4 12" className="opacity-40" />
      </motion.svg>

      {/* Middle Ring 1 */}
      <motion.svg
        className="absolute inset-0 w-full h-full drop-shadow-[0_0_8px_rgba(0,246,255,0.6)]"
        viewBox="0 0 500 500"
        animate={{ rotate: -360 }}
        transition={{ duration: 25, ease: "linear", repeat: Infinity }}
      >
        <circle cx="250" cy="250" r="200" fill="none" stroke={primaryColor} strokeWidth="2" strokeDasharray="100 40 20 40" className="opacity-60" />
        <circle cx="250" cy="450" r="4" fill={primaryColor} />
        <circle cx="50" cy="250" r="4" fill={primaryColor} />
      </motion.svg>

      {/* Thick glowing segments */}
      <motion.svg
        className="absolute inset-0 w-full h-full drop-shadow-[0_0_12px_rgba(0,246,255,1)]"
        viewBox="0 0 500 500"
        animate={{ rotate: 360 }}
        transition={{ duration: 15, ease: "easeInOut", repeat: Infinity, repeatType: 'reverse' }}
      >
        <circle cx="250" cy="250" r="170" fill="none" stroke={primaryColor} strokeWidth="6" strokeDasharray="80 300" strokeLinecap="round" className="opacity-90" />
        <circle cx="250" cy="250" r="170" fill="none" stroke={primaryColor} strokeWidth="6" strokeDasharray="40 400" strokeLinecap="round" className="opacity-90" strokeDashoffset="200" />
      </motion.svg>

      {/* Inner precise ring */}
      <motion.svg
        className="absolute inset-0 w-full h-full"
        viewBox="0 0 500 500"
        animate={{ rotate: -360 }}
        transition={{ duration: 60, ease: "linear", repeat: Infinity }}
      >
        <circle cx="250" cy="250" r="140" fill="none" stroke={primaryColor} strokeWidth="1" strokeDasharray="2 10" className="opacity-50" />
      </motion.svg>

      {/* Center content */}
      <div className="absolute flex flex-col items-center justify-center text-center z-10 w-[260px] h-[260px] rounded-full bg-jarvis-dark/40 backdrop-blur-sm border border-jarvis-cyan/10 pointer-events-none">
        
        {/* The Audio Waveform simulation when busy */}
        {isBusy && (
          <div className="absolute inset-0 flex items-center justify-center opacity-30">
            <motion.div animate={{ scale: [1, 1.2, 1] }} transition={{ repeat: Infinity, duration: 1 }} className="absolute w-[180px] h-[180px] rounded-full bg-jarvis-teal blur-2xl" />
          </div>
        )}

        <h1 className="text-4xl font-bold tracking-[0.3em] ml-3 text-glow text-jarvis-cyan">
          J.A.R.V.I.S
        </h1>
        
        <div className="flex items-center gap-2 mt-4 opacity-80">
          <div className={`w-2 h-2 rounded-full ${isBusy ? 'bg-jarvis-teal animate-ping' : 'bg-jarvis-cyan'}`} />
          <span className="text-xs font-mono tracking-widest text-jarvis-cyan/80">
            {isBusy ? 'PROCESSING DIRECTIVE...' : 'AWAITING INPUT'}
          </span>
          <div className={`w-2 h-2 rounded-full ${isBusy ? 'bg-jarvis-teal animate-ping' : 'bg-jarvis-cyan'}`} />
        </div>
      </div>

    </div>
  );
};

export default CentralCore;
