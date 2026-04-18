import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MapPin, Navigation, Home, Briefcase, Plus, Trash2, CheckCircle2, X, Save, Crosshair, Loader2, AlertCircle, Signal } from 'lucide-react';

const AddressPanel = () => {
  const [addresses, setAddresses] = useState([]);
  const [activeAddress, setActiveAddress] = useState(null);
  const [isAdding, setIsAdding] = useState(false);
  const [isDetecting, setIsDetecting] = useState(false);
  const [detectionSource, setDetectionSource] = useState(null); // 'gps' or 'ip'
  
  // Form State
  const [formData, setFormData] = useState({
    label: '',
    house_number: '',
    street_name: '',
    city: '',
    zipcode: '',
    landmark: '',
    lat: '',
    lng: ''
  });
  
  const BACKEND_URL = 'http://127.0.0.1:8765';

  const fetchAddresses = async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/food/addresses`);
      if (res.ok) {
        const data = await res.json();
        setAddresses(data.addresses || []);
        const active = data.addresses.find(a => a.is_active);
        setActiveAddress(active || null);
      }
    } catch (e) {
      console.warn('Address fetch failed', e);
    }
  };

  useEffect(() => {
    fetchAddresses();
    const interval = setInterval(fetchAddresses, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleLiveDetect = async () => {
    setIsDetecting(true);
    setDetectionSource(null);
    
    const fallbackIP = async () => {
      try {
        const res = await fetch('http://ip-api.com/json/');
        const data = await res.json();
        if (data.status === 'success') {
          setDetectionSource('ip');
          setFormData(prev => ({
            ...prev,
            label: `DETECTED (${data.city.toUpperCase()})`,
            city: data.city,
            zipcode: data.zip || '',
            lat: data.lat.toString(),
            lng: data.lon.toString()
          }));
        }
      } catch (e) {
        console.error('IP Fallback failed', e);
      }
    };

    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        async (position) => {
          const { latitude, longitude } = position.coords;
          try {
            const res = await fetch(`https://api-bdc.io/data/reverse-geocode-client?latitude=${latitude}&longitude=${longitude}&localityLanguage=en`);
            const data = await res.json();
            
            const area = data.locality || data.principalSubdivision || 'LIVE TARGET';
            const city = data.city || data.locality || 'UNKNOWN';
            
            setDetectionSource('gps');
            setFormData(prev => ({
              ...prev,
              label: `HOME - ${area.toUpperCase()}`,
              city: city,
              zipcode: data.postcode || '',
              street_name: data.locality || '',
              lat: latitude.toFixed(6),
              lng: longitude.toFixed(6)
            }));
          } catch (e) {
            console.warn('Reverse geocode failed, using raw GPS', e);
            setDetectionSource('gps');
            setFormData(prev => ({ ...prev, lat: latitude.toFixed(6), lng: longitude.toFixed(6), label: 'GPS LOCK' }));
          } finally {
            setIsDetecting(false);
          }
        },
        async (error) => {
          console.warn('GPS Denied/Failed, falling back to IP', error);
          await fallbackIP();
          setIsDetecting(false);
        },
        { timeout: 10000 }
      );
    } else {
      await fallbackIP();
      setIsDetecting(false);
    }
  };

  const handleSetActive = async (label) => {
    try {
      await fetch(`${BACKEND_URL}/api/food/addresses/active`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label })
      });
      fetchAddresses();
    } catch (e) {
      console.error(e);
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();
    if (!formData.label || !formData.city) return;

    try {
      const res = await fetch(`${BACKEND_URL}/api/food/addresses`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...formData,
          lat: parseFloat(formData.lat) || 0,
          lng: parseFloat(formData.lng) || 0,
          set_active: true
        })
      });
      if (res.ok) {
        setIsAdding(false);
        setDetectionSource(null);
        setFormData({ label: '', house_number: '', street_name: '', city: '', zipcode: '', landmark: '', lat: '', lng: '' });
        fetchAddresses();
      }
    } catch (err) {
      console.error('Failed to save address', err);
    }
  };

  const handleDelete = async (e, label) => {
    e.stopPropagation();
    try {
      const res = await fetch(`${BACKEND_URL}/api/food/addresses/${label}`, {
        method: 'DELETE'
      });
      if (res.ok) fetchAddresses();
    } catch (err) {
      console.error('Failed to delete address', err);
    }
  };

  const getIcon = (label) => {
    const l = label ? label.toLowerCase() : '';
    if (l.includes('home')) return <Home size={14} />;
    if (l.includes('work') || l.includes('office')) return <Briefcase size={14} />;
    return <MapPin size={14} />;
  };

  const formatFullAddress = (addr) => {
    const parts = [
      addr.house_number,
      addr.street_name,
      addr.city,
      addr.zipcode ? `${addr.zipcode}` : null
    ].filter(Boolean);
    return parts.join(', ');
  };

  return (
    <div className="glass-panel p-5 flex flex-col gap-4 relative overflow-hidden group">
      <div className="absolute inset-0 bg-cyan-500/5 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />
      
      <div className="z-10 flex items-center justify-between border-b border-jarvis-cyan/20 pb-2 mb-1">
        <div className="font-orbitron tracking-widest text-sm flex items-center gap-2 opacity-80 uppercase">
          <Navigation size={16} className="text-cyan-400" /> Delivery Target
        </div>
        <button 
          onClick={() => setIsAdding(!isAdding)}
          className={`p-1 rounded-lg transition-colors ${isAdding ? 'bg-red-500/20 text-red-400' : 'hover:bg-cyan-500/20 text-cyan-500/60 hover:text-cyan-400'}`}
        >
          {isAdding ? <X size={16} /> : <Plus size={16} />}
        </button>
      </div>

      <div className="z-10 space-y-2 max-h-[300px] overflow-y-auto pr-1 custom-scrollbar">
        <AnimatePresence mode='popLayout'>
          {isAdding ? (
            <motion.form
              key="add-form"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              onSubmit={handleSave}
              className="space-y-3 bg-cyan-500/5 p-3 rounded-xl border border-cyan-500/20"
            >
              <button
                type="button"
                onClick={handleLiveDetect}
                disabled={isDetecting}
                className={`w-full py-2 mb-1 rounded-lg flex items-center justify-center gap-2 text-[9px] font-orbitron tracking-widest border transition-all ${
                  isDetecting 
                    ? 'bg-cyan-400/10 border-cyan-400/20 text-cyan-400 cursor-wait' 
                    : detectionSource === 'gps'
                      ? 'bg-green-500/10 border-green-500/20 text-green-400'
                      : detectionSource === 'ip'
                        ? 'bg-yellow-500/10 border-yellow-500/20 text-yellow-400'
                        : 'bg-cyan-400/10 border-cyan-400/20 text-cyan-400 hover:bg-cyan-400/20'
                }`}
              >
                {isDetecting ? <Loader2 size={12} className="animate-spin" /> : detectionSource === 'gps' ? <Signal size={12} /> : detectionSource === 'ip' ? <AlertCircle size={12} /> : <Crosshair size={12} />}
                {isDetecting ? 'SCANNING COORDINATES...' : detectionSource === 'gps' ? 'GPS SIGNAL: PRECISE' : detectionSource === 'ip' ? 'IP FALLBACK: APPROXIMATE' : 'LIVE LOCATION DETECTION'}
              </button>

              <input 
                placeholder="LABEL (E.G. HOME / OFFICE)" 
                value={formData.label}
                onChange={e => setFormData({...formData, label: e.target.value})}
                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-[10px] font-mono text-cyan-300 focus:border-cyan-500 outline-none"
              />

              <div className="grid grid-cols-2 gap-2">
                <input 
                  placeholder="HOUSE / FLAT NO" 
                  value={formData.house_number}
                  onChange={e => setFormData({...formData, house_number: e.target.value})}
                  className="bg-black/40 border border-white/10 rounded-lg p-2 text-[10px] font-mono text-white/80 focus:border-cyan-500 outline-none"
                />
                <input 
                  placeholder="STREET / CROSS" 
                  value={formData.street_name}
                  onChange={e => setFormData({...formData, street_name: e.target.value})}
                  className="bg-black/40 border border-white/10 rounded-lg p-2 text-[10px] font-mono text-white/80 focus:border-cyan-500 outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <input 
                  placeholder="CITY" 
                  value={formData.city}
                  onChange={e => setFormData({...formData, city: e.target.value})}
                  className="bg-black/40 border border-white/10 rounded-lg p-2 text-[10px] font-mono text-white/80 focus:border-cyan-500 outline-none"
                />
                <input 
                  placeholder="ZIPCODE" 
                  value={formData.zipcode}
                  onChange={e => setFormData({...formData, zipcode: e.target.value})}
                  className="bg-black/40 border border-white/10 rounded-lg p-2 text-[10px] font-mono text-white/80 focus:border-cyan-500 outline-none"
                />
              </div>

              <input 
                placeholder="LANDMARK (OPTIONAL)" 
                value={formData.landmark}
                onChange={e => setFormData({...formData, landmark: e.target.value})}
                className="w-full bg-black/40 border border-white/10 rounded-lg p-2 text-[10px] font-mono text-white/80 focus:border-cyan-500 outline-none"
              />

              {detectionSource === 'ip' && (
                <div className="text-[8px] text-yellow-500/60 font-mono flex items-center gap-1 mt-1 animate-pulse">
                  <AlertCircle size={10} /> WARNING: IP DETECTION MAY BE INACCURATE BY MILES
                </div>
              )}

              <button 
                type="submit"
                className="w-full py-2 bg-cyan-500/20 hover:bg-cyan-500/40 text-cyan-400 rounded-lg font-orbitron text-[10px] tracking-widest flex items-center justify-center gap-2 transition-all border border-cyan-500/30"
              >
                <Save size={14} /> INITIALIZE TARGET
              </button>
            </motion.form>
          ) : addresses.length === 0 ? (
            <motion.div 
              key="empty"
              initial={{ opacity: 0 }} 
              animate={{ opacity: 1 }}
              className="text-[10px] font-mono opacity-40 italic text-center py-4"
            >
              NO TARGETS DEFINED // STANDBY
            </motion.div>
          ) : (
            addresses.map((addr) => (
              <motion.div
                key={addr.label}
                layout
                initial={{ x: -20, opacity: 0 }}
                animate={{ x: 0, opacity: 1 }}
                onClick={() => handleSetActive(addr.label)}
                className={`
                  flex items-center justify-between p-2.5 rounded-xl border cursor-pointer group/item transition-all duration-300
                  ${addr.is_active 
                    ? 'bg-cyan-500/20 border-cyan-500/40 shadow-[0_0_15px_rgba(6,182,212,0.2)]' 
                    : 'bg-black/20 border-white/5 hover:border-cyan-500/20 hover:bg-cyan-500/5'}
                `}
              >
                <div className="flex items-center gap-3 w-full">
                  <div className={`p-1.5 rounded-lg flex-shrink-0 ${addr.is_active ? 'text-cyan-400' : 'text-gray-500'}`}>
                    {getIcon(addr.label)}
                  </div>
                  <div className="overflow-hidden">
                    <div className={`text-[10px] font-bold tracking-wider ${addr.is_active ? 'text-cyan-300' : 'text-gray-400 uppercase'}`}>
                      {addr.label}
                    </div>
                    <div className="text-[8px] text-gray-500 font-mono truncate">
                      {formatFullAddress(addr)}
                    </div>
                  </div>
                </div>
                
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button 
                    onClick={(e) => handleDelete(e, addr.label)}
                    className="opacity-0 group-hover/item:opacity-100 p-1 hover:bg-red-500/20 text-red-400/60 hover:text-red-400 rounded transition-all"
                  >
                    <Trash2 size={12} />
                  </button>
                  {addr.is_active && (
                    <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }}>
                      <CheckCircle2 size={14} className="text-cyan-400" />
                    </motion.div>
                  )}
                </div>
              </motion.div>
            ))
          )}
        </AnimatePresence>
      </div>

      <div className="z-10 mt-2 p-2 rounded-lg bg-cyan-500/5 border border-cyan-500/10 transition-all animate-in fade-in slide-in-from-bottom-2">
         <div className="text-[7px] font-mono text-cyan-500/40 uppercase tracking-widest text-center truncate">
           {activeAddress ? formatFullAddress(activeAddress) : 'OFFLINE'}
         </div>
         <div className="text-[9px] font-bold text-cyan-400/80 uppercase tracking-widest text-center mt-0.5">
           Matrix: {activeAddress ? `${parseFloat(activeAddress.lat).toFixed(4)}, ${parseFloat(activeAddress.lng).toFixed(4)}` : 'DISCONNECTED'}
         </div>
      </div>
    </div>
  );
};

export default AddressPanel;
