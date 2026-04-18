import React, { useEffect, useState, useRef } from "react";
import { Activity, ShieldCheck, Maximize2, Minimize2, X } from "lucide-react";
import { executeTask, getSkills, getSystemHealth, getSystemMetrics, getSystemLogs } from "./lib/api";

import JarvisCore from "./components/JarvisCore";
import SystemLogsPanel from "./components/SystemLogsPanel";
import TelemetryDashboard from "./components/TelemetryDashboard";
import DirectiveInput from "./components/DirectiveInput";

export default function App() {
  const [health, setHealth] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [busy, setBusy] = useState(false);
  
  // Simulated Command History for the Logs Panel
  const [commsHistory, setCommsHistory] = useState([
    { time: new Date().toLocaleTimeString(), sender: 'JARVIS_CORE', text: 'SYSTEM INITIALIZED. AWAITING DIRECTIVES.' }
  ]);

  const refreshHealth = async () => {
    try {
      const [h, m] = await Promise.all([getSystemHealth(), getSystemMetrics()]);
      setHealth(h);
      setMetrics(m);
    } catch (e) {
      console.error("Health fetch failed", e);
    }
  };

  useEffect(() => {
    refreshHealth();
    const iv = setInterval(refreshHealth, 2000); // Faster refresh for telemetry
    return () => clearInterval(iv);
  }, []);

  const handleExecute = async (taskText) => {
    if (!taskText.trim() || busy) return;
    
    const time = new Date().toLocaleTimeString();
    setCommsHistory(prev => [...prev, { time, sender: 'USER', text: taskText }]);
    setBusy(true);

    try {
      const res = await executeTask(taskText.trim(), "jarvis-dashboard");
      
      const newTime = new Date().toLocaleTimeString();
      let jarvisResponse = "Action executed successfully.";
      
      // Parse the response to give the conversational text
      if (res?.result?.reply) {
         jarvisResponse = res.result.reply;
      } else if (res?.steps && res.steps.length > 0) {
        const lastStep = res.steps[res.steps.length - 1];
        if (lastStep.status === 'error') {
           jarvisResponse = `Error executing directive: ${lastStep.error}`;
        } else if (lastStep.skill) {
           jarvisResponse = `Module [${lastStep.skill}] completed execution without returning text.`;
        }
      }

      setCommsHistory(prev => [...prev, { time: newTime, sender: 'JARVIS_CORE', text: jarvisResponse }]);
      
      // Play TTS if available
      if (res?.result?.tts_audio_base64) {
        try {
            const audio = new Audio('data:audio/wav;base64,' + res.result.tts_audio_base64);
            audio.play().catch(e => console.error("Audio play error:", e));
        } catch(e) {
            console.error("Audio setup error:", e);
        }
      }
      
    } catch (error) {
      setCommsHistory(prev => [...prev, { time: new Date().toLocaleTimeString(), sender: 'JARVIS_CORE', text: `Critical Failure: ${error.message || "Unknown error"}` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-grid bg-[var(--bg-deep)] text-cyan-100 flex flex-col overflow-hidden relative">
      
      {/* Top HUD Bar */}
      <header className="flex items-center justify-between p-4 border-b border-cyan-500/20 bg-black/40 backdrop-blur-md relative z-20 shadow-[0_4px_30px_rgba(0,246,255,0.05)]" style={{ WebkitAppRegion: 'drag' }}>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-xs text-jarvis-teal tracking-widest font-bold">
             <span className="w-2 h-2 rounded-full bg-jarvis-teal animate-pulse" />
             SYS_CORE: {Math.round(metrics?.cpu_percent || 0).toFixed(1)}%
          </div>
          <div className="border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 rounded text-[10px] tracking-widest text-cyan-200">
             ENGINE: LOCAL_LLM
          </div>
        </div>

        <div className="flex flex-col items-center gap-1">
          <div className="flex items-center gap-3 opacity-30 pointer-events-none">
            <div className="h-[1px] w-32 bg-cyan-500" />
            <ShieldCheck size={14} className="text-cyan-500" />
            <div className="h-[1px] w-32 bg-cyan-500" />
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="text-[10px] tracking-widest text-cyan-500 font-bold uppercase">
            PROTOCOL: SECURE
          </div>
          <div className="flex items-center gap-6 pr-2" style={{ WebkitAppRegion: 'no-drag' }}>
            <button 
              onClick={() => window.jarvis?.minimize()} 
              className="text-cyan-400 hover:text-[#00f6ff] transition-all duration-300 drop-shadow-[0_0_8px_rgba(0,246,255,0.4)] hover:drop-shadow-[0_0_12px_rgba(0,246,255,0.8)]"
              title="Minimize"
            >
              <Minimize2 size={18} strokeWidth={2.5} />
            </button>
            <button 
              onClick={() => window.jarvis?.maximize()} 
              className="text-cyan-400 hover:text-[#00f6ff] transition-all duration-300 drop-shadow-[0_0_8px_rgba(0,246,255,0.4)] hover:drop-shadow-[0_0_12px_rgba(0,246,255,0.8)]"
              title="Maximize"
            >
              <Maximize2 size={18} strokeWidth={2.5} />
            </button>
            <button 
              onClick={() => window.jarvis?.close()} 
              className="text-cyan-400 hover:text-rose-500 transition-all duration-300 drop-shadow-[0_0_8px_rgba(0,246,255,0.4)] hover:drop-shadow-[0_0_12px_rgba(255,0,0,0.8)]"
              title="Close"
            >
              <X size={22} strokeWidth={2.5} />
            </button>
          </div>
        </div>
      </header>

      {/* Main Grid Layout */}
      <main className="flex-1 grid grid-cols-12 gap-6 p-6 relative z-10">
        
        {/* Left: Logs */}
        <div className="col-span-3 flex flex-col">
          <SystemLogsPanel history={commsHistory} />
        </div>

        {/* Center: 3D Core */}
        <div className="col-span-6 relative">
          <JarvisCore />
        </div>

        {/* Right: Telemetry */}
        <div className="col-span-3 flex flex-col">
          <TelemetryDashboard 
            metrics={metrics} 
            location={health?.location} 
            automationReady={health?.automation_ready} 
          />
        </div>
      </main>

      {/* Bottom Input Area */}
      <div className="p-6 pb-8 relative z-20">
        <DirectiveInput onExecute={handleExecute} busy={busy} />
      </div>

    </div>
  );
}
