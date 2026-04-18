import React, { useRef, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Terminal } from 'lucide-react';

export default function SystemLogsPanel({ history }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history]);

  return (
    <motion.div 
      initial={{ opacity: 0, x: -50 }}
      animate={{ opacity: 1, x: 0 }}
      className="panel-shell flex flex-col h-[70vh] border-cyan-500/30"
    >
      <div className="panel-header mb-4 border-b border-cyan-500/20 pb-3">
        <div className="panel-title text-cyan-200">
          <Terminal size={16} /> _SYSTEM COMMS LOG
        </div>
      </div>

      <div className="flex-1 overflow-y-auto pr-2 space-y-4 font-mono text-sm">
        {history.length === 0 && (
          <div className="text-cyan-500/50 italic">Awaiting communication link...</div>
        )}
        
        {history.map((log, idx) => (
          <motion.div 
            key={idx}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className={`flex flex-col gap-1 user-select-text selection:bg-cyan-500/40`}
          >
            <div className="flex flex-wrap gap-2 text-cyan-500/70 text-xs">
              <span>[{log.time}]</span>
              <span className={log.sender === 'USER' ? 'text-cyan-100' : 'text-jarvis-teal font-bold'}>
                [{log.sender}]
              </span>
            </div>
            <div className={`text-sm ${log.sender === 'USER' ? 'text-cyan-200' : 'text-jarvis-teal/90'}`}>
              {log.text}
            </div>
          </motion.div>
        ))}
        <div ref={bottomRef} />
      </div>
    </motion.div>
  );
}
