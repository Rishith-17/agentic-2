import React from 'react';
import { motion } from 'framer-motion';
import { Cpu, MemoryStick, Network, MapPin, CheckCircle, CloudRain, Newspaper } from 'lucide-react';

export default function TelemetryDashboard({ metrics, location, automationReady }) {
  
  const cpuLoad = Math.round(metrics?.cpu_percent || 0);
  const memLoad = Math.round(metrics?.ram_percent || 0);
  const netDown = (metrics?.net_received_bytes / 1024 / 1024 || 0).toFixed(1);
  const netUp = (metrics?.net_sent_bytes / 1024 / 1024 || 0).toFixed(1);

  return (
    <motion.div 
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      className="space-y-4"
    >
      {/* TELEMETRY */}
      <div className="panel-shell border-cyan-500/30">
        <div className="panel-header mb-4 items-center">
          <div className="panel-title text-cyan-200">
            <Cpu size={16} /> TELEMETRY
          </div>
        </div>
        
        <div className="space-y-4 font-mono">
          <div>
            <div className="flex justify-between text-xs text-cyan-500 mb-1">
              <span className="flex items-center gap-1"><Cpu size={12}/> CPU LOAD</span>
              <span className="text-cyan-200">{cpuLoad}%</span>
            </div>
            <div className="h-1.5 w-full bg-black/50 rounded-full overflow-hidden">
              <motion.div 
                initial={{ width: 0 }} 
                animate={{ width: `${cpuLoad}%` }} 
                className="h-full bg-cyan-400 shadow-[0_0_10px_#00f6ff]"
              />
            </div>
          </div>

          <div>
            <div className="flex justify-between text-xs text-cyan-500 mb-1">
              <span className="flex items-center gap-1"><MemoryStick size={12}/> MEMORY</span>
              <span className="text-cyan-200">{memLoad}%</span>
            </div>
            <div className="h-1.5 w-full bg-black/50 rounded-full overflow-hidden">
              <motion.div 
                initial={{ width: 0 }} 
                animate={{ width: `${memLoad}%` }} 
                className="h-full bg-purple-500 shadow-[0_0_10px_#a855f7]"
              />
            </div>
          </div>

          <div className="pt-2 border-t border-cyan-500/10 flex justify-between text-xs text-cyan-400">
            <span className="flex items-center gap-1"><Network size={12}/> NETWORK</span>
            <span>↓ {netDown}M ↑ {netUp}M</span>
          </div>
        </div>
      </div>

      {/* DELIVERY TARGET */}
      <div className="panel-shell border-cyan-500/30">
        <div className="panel-header mb-3">
          <div className="panel-title text-cyan-200">
            <MapPin size={16} /> DELIVERY TARGET
          </div>
        </div>
        
        <div className="rounded-xl border border-jarvis-teal/40 bg-jarvis-teal/10 p-3 mb-2 flex items-start gap-3">
          <MapPin size={16} className="text-jarvis-teal mt-0.5" />
          <div className="flex-1">
            <div className="text-xs font-bold text-jarvis-teal uppercase tracking-widest">{location || 'DETECTED (BENGALURU)'}</div>
            <div className="text-[10px] text-jarvis-teal/70 uppercase">Bengaluru</div>
          </div>
          <CheckCircle size={16} className="text-jarvis-teal" />
        </div>
        
        <div className="text-center rounded-lg bg-black/50 p-2 font-mono text-[10px] text-cyan-500">
          <span className="block opacity-50">BENGALURU</span>
          <span className="text-cyan-200 font-bold">MATRIX: 12.9753, 77.5910</span>
        </div>
      </div>

      {/* QUICK MODULES */}
      <div className="panel-shell border-cyan-500/30">
        <div className="panel-header mb-3">
          <div className="panel-title text-cyan-200">
            <CheckCircle size={16} /> QUICK MODULES
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <button className="flex flex-col items-center justify-center p-3 rounded-xl border border-cyan-500/30 bg-black/40 hover:bg-cyan-500/20 hover:border-cyan-400 transition group">
            <CloudRain size={20} className="mb-2 text-cyan-500 group-hover:text-cyan-100 transition shadow-cyan-300 drop-shadow-md" />
            <span className="text-[10px] uppercase tracking-widest text-cyan-200">WEATHER</span>
          </button>
          <button className="flex flex-col items-center justify-center p-3 rounded-xl border border-cyan-500/30 bg-black/40 hover:bg-cyan-500/20 hover:border-cyan-400 transition group">
            <Newspaper size={20} className="mb-2 text-cyan-500 group-hover:text-cyan-100 transition drop-shadow-[0_0_5px_rgba(0,246,255,0.8)]" />
            <span className="text-[10px] uppercase tracking-widest text-cyan-200">BRIEFING</span>
          </button>
        </div>
      </div>

    </motion.div>
  );
}
