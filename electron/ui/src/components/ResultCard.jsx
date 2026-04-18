import React, { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Cloud, Sun, CloudRain, Wind, Newspaper, Monitor, Smartphone, Volume2, Wifi, Bluetooth, X } from 'lucide-react';

const ResultCard = ({ result, onClose }) => {
  useEffect(() => {
    if (result.skill_type === 'food_grocery') return; // Don't auto-close food cards
    const timer = setTimeout(() => {
      onClose();
    }, 8000);
    return () => clearTimeout(timer);
  }, [onClose, result.skill_type]);

  const getIcon = () => {
    switch (result.skill_type) {
      case 'weather':
        return <Cloud className="w-8 h-8 text-cyan-400" />;
      case 'news':
        return <Newspaper className="w-8 h-8 text-blue-400" />;
      case 'hardware':
        return <Monitor className="w-8 h-8 text-teal-400" />;
      case 'food_grocery':
        return <Volume2 className="w-8 h-8 text-orange-400 rotate-90" />; // Placeholder for food
      default:
        return <Monitor className="w-8 h-8 text-gray-400" />;
    }
  };

  const getTitle = () => {
    switch (result.skill_type) {
      case 'weather': return 'Weather Forecast';
      case 'news': return 'Latest News';
      case 'hardware': return 'System Update';
      case 'food_grocery': return 'Food & Grocery';
      default: return 'Information';
    }
  };

  return (
    <motion.div
      initial={{ y: -50, opacity: 0, scale: 0.9, x: "-50%" }}
      animate={{ y: 0, opacity: 1, scale: 1, x: "-50%" }}
      exit={{ y: -50, opacity: 0, scale: 0.9, x: "-50%" }}
      className={`fixed top-12 left-1/2 ${result.skill_type === 'food_grocery' ? 'w-[450px]' : 'w-96'} z-[100] bg-black/60 backdrop-blur-2xl border ${result.skill_type === 'food_grocery' ? 'border-orange-500/40' : 'border-cyan-500/40'} rounded-2xl p-5 shadow-[0_10px_40px_rgba(6,182,212,0.3)]`}
    >
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className={`p-2.5 ${result.skill_type === 'food_grocery' ? 'bg-orange-500/20 border-orange-500/30' : 'bg-cyan-500/20 border-cyan-500/30'} rounded-xl border`}>
            {getIcon()}
          </div>
          <div>
            <h3 className={`text-sm font-bold ${result.skill_type === 'food_grocery' ? 'text-orange-300' : 'text-cyan-300'} uppercase tracking-[0.2em]`}>{getTitle()}</h3>
            <p className="text-[10px] text-cyan-500/70 font-mono tracking-widest mt-0.5">AUTH: {Math.random().toString(36).substr(2, 8).toUpperCase()}</p>
          </div>
        </div>
        <button onClick={onClose} className="text-cyan-500/50 hover:text-cyan-200 hover:bg-cyan-500/10 p-1.5 rounded-full transition-all">
          <X className="w-5 h-5" />
        </button>
      </div>

      <div className="space-y-3">
        {result.skill_type === 'food_grocery' && result.data?.search_results && (
          <div className="space-y-2 max-h-[300px] overflow-y-auto pr-2 custom-scrollbar">
            {result.data.search_results.map((item, idx) => (
              <div key={idx} className="flex items-center justify-between p-3 rounded-xl bg-orange-500/5 border border-orange-500/10 hover:bg-orange-500/10 transition-colors group">
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-bold text-white truncate">{idx + 1}. {item.name}</div>
                  <div className="flex items-center gap-2 mt-1 text-[10px]">
                    <span className="text-orange-400 font-bold">Rs.{item.price}</span>
                    <span className="text-gray-400">|</span>
                    <span className="text-cyan-400">{item.rating ? `⭐ ${item.rating}` : 'N/A'}</span>
                    <span className="text-gray-400">|</span>
                    <span className={`px-1.5 py-0.5 rounded text-[8px] uppercase font-bold ${item.platform.toLowerCase() === 'swiggy' ? 'bg-orange-500/20 text-orange-400' : 'bg-red-500/20 text-red-400'}`}>{item.platform}</span>
                  </div>
                </div>
                <button 
                  onClick={() => window.dispatchEvent(new CustomEvent('jarvis-selection', { detail: idx + 1 }))}
                  className="ml-4 px-3 py-1.5 bg-orange-500/20 hover:bg-orange-500 text-orange-300 hover:text-white text-[10px] font-bold rounded-lg border border-orange-500/30 transition-all uppercase tracking-wider"
                >
                  Select
                </button>
              </div>
            ))}
          </div>
        )}

        {result.skill_type === 'weather' && result.data && (
          <div className="text-center py-2">
            <div className="text-4xl font-light text-white mb-1">{Math.round(result.data.temp)}°C</div>
            <div className="text-sm text-cyan-300 uppercase tracking-wider">{result.data.condition}</div>
            <div className="text-xs text-cyan-500/70 mt-1">{result.data.city}</div>
          </div>
        )}

        {(result.skill_type === 'hardware' || !result.data) && (
          <div className="text-sm text-cyan-100 font-mono leading-relaxed bg-cyan-500/5 p-3 rounded-lg border border-cyan-500/10 italic">
            "{result.message}"
          </div>
        )}
      </div>

      <div className="mt-4 h-1 bg-cyan-900/30 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: "100%" }}
          animate={{ width: "0%" }}
          transition={{ duration: 8, ease: "linear" }}
          className="h-full bg-cyan-500"
        />
      </div>
    </motion.div>
  );
};

export default ResultCard;
