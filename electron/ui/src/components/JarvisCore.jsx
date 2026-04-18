import React, { useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Ring, Text } from '@react-three/drei';

function AnimatedRings() {
  const outerRing = useRef();
  const middleRing = useRef();
  const innerRing = useRef();

  useFrame((state) => {
    const t = state.clock.getElapsedTime();
    if (outerRing.current) {
      outerRing.current.rotation.z = t * 0.2;
    }
    if (middleRing.current) {
      middleRing.current.rotation.z = -t * 0.3;
    }
    if (innerRing.current) {
      innerRing.current.rotation.z = t * 0.5;
    }
  });

  return (
    <group>
      {/* Outer Glow Ring */}
      <Ring ref={outerRing} args={[3.8, 4, 64, 1, 0, Math.PI * 1.5]} position={[0, 0, 0]}>
        <meshBasicMaterial color="#00f6ff" transparent opacity={0.6} fog={false} />
      </Ring>
      <Ring args={[3.8, 4, 64, 1, Math.PI * 1.6, Math.PI * 0.3]} position={[0, 0, 0]}>
        <meshBasicMaterial color="#00d7ff" transparent opacity={0.3} />
      </Ring>

      {/* Middle Dashed Ring */}
      <Ring ref={middleRing} args={[3, 3.15, 64, 1, 0, Math.PI * 1.8]} position={[0, 0, 0]}>
        <meshBasicMaterial color="#0bebc4" transparent opacity={0.7} />
      </Ring>

      {/* Inner Fast Ring */}
      <Ring ref={innerRing} args={[2.2, 2.3, 64]} position={[0, 0, 0]}>
        <meshBasicMaterial color="#00f6ff" transparent opacity={0.4} wireframe />
      </Ring>

      {/* Center Text */}
      <Text
        position={[0, 0.4, 0]}
        fontSize={0.8}
        color="#ffffff"
        font="https://fonts.gstatic.com/s/orbitron/v31/yHK30MXbvkvdqcbzvwI0O_A.woff"
        anchorX="center"
        anchorY="middle"
        characters="J.A.R.V.I.S"
      >
        J.A.R.V.I.S
        <meshBasicMaterial color="#00f6ff" />
      </Text>
      
      <Text
        position={[0, -0.6, 0]}
        fontSize={0.25}
        color="#0bebc4"
        font="https://fonts.gstatic.com/s/sharetechmono/v15/J7aHnp1uD0FAWEeoNdpSN8-P7WJ2.woff"
        anchorX="center"
        anchorY="middle"
      >
        ● AWAITING INPUT ●
      </Text>
    </group>
  );
}

export default function JarvisCore() {
  return (
    <div className="relative flex h-full w-full items-center justify-center">
      {/* Glow Behind the 3D canvas */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-64 w-64 rounded-full bg-cyan-500/20 blur-[80px] animate-pulse-glow pointer-events-none" />
      
      <Canvas camera={{ position: [0, 0, 10], fov: 50 }}>
        <ambientLight intensity={0.5} />
        <AnimatedRings />
      </Canvas>
    </div>
  );
}
