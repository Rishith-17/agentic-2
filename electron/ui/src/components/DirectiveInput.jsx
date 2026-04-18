import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Loader2 } from 'lucide-react';

export default function DirectiveInput({ onExecute, busy }) {
  const [task, setTask] = useState("");

  const handleExecute = () => {
    if (!task.trim() || busy) return;
    onExecute(task);
    setTask("");
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 50 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex w-full max-w-4xl mx-auto rounded-xl border border-cyan-500/40 bg-black/50 p-1 backdrop-blur-md shadow-[0_0_20px_rgba(0,246,255,0.15)] overflow-hidden"
    >
      <input
        value={task}
        onChange={(e) => setTask(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && handleExecute()}
        placeholder="DIRECTIVE INPUT..."
        className="flex-1 bg-transparent px-6 py-4 text-sm font-mono text-cyan-100 outline-none placeholder:text-cyan-500/30 uppercase tracking-widest"
      />
      <button
        onClick={handleExecute}
        disabled={busy || !task.trim()}
        className="bg-cyan-500/20 hover:bg-cyan-400/30 text-cyan-200 px-8 py-4 font-bold tracking-widest text-xs uppercase transition border-l border-cyan-500/40 disabled:opacity-50 disabled:cursor-not-allowed group relative overflow-hidden"
      >
        <span className="relative z-10 flex items-center gap-2">
          {busy ? <Loader2 size={16} className="animate-spin" /> : null}
          EXECUTE
        </span>
        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-cyan-400/20 to-transparent -translate-x-full group-hover:animate-[shimmer_1.5s_infinite]" />
      </button>
    </motion.div>
  );
}
