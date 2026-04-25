"use client";

import { motion } from "framer-motion";

type RingGroup = {
  id: string;
  cx: number;
  cy: number;
  radii: number[];
  duration: number;
  dx: number;
  dy: number;
};

const ringGroups: RingGroup[] = [
  { id: "a", cx: 220, cy: 170, radii: [24, 48, 72, 96], duration: 24, dx: 10, dy: 8 },
  { id: "b", cx: 520, cy: 160, radii: [24, 52, 80, 108], duration: 26, dx: -8, dy: 10 },
  { id: "c", cx: 230, cy: 470, radii: [24, 56, 88, 120], duration: 28, dx: 8, dy: -8 },
  { id: "d", cx: 620, cy: 480, radii: [28, 64, 100, 136], duration: 32, dx: -12, dy: 8 },
  { id: "e", cx: 980, cy: 460, radii: [24, 52, 80, 108], duration: 29, dx: 10, dy: -10 },
  { id: "f", cx: 1180, cy: 770, radii: [24, 56, 88, 120], duration: 30, dx: -10, dy: 8 },
  { id: "g", cx: 860, cy: 780, radii: [24, 52, 80, 108], duration: 27, dx: 8, dy: 8 },
];

const paths = [
  "M 120 210 C 280 110, 390 270, 560 210 S 920 100, 1180 210",
  "M 60 580 C 240 470, 420 640, 620 560 S 980 430, 1310 620",
  "M 180 760 C 420 660, 560 840, 820 760 S 1080 680, 1360 820",
];

export default function ModernBackgroundPaths() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {/* base lightened gradient */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(96,165,250,0.22),transparent_30%),radial-gradient(circle_at_top_right,rgba(34,211,238,0.12),transparent_24%),radial-gradient(circle_at_50%_30%,rgba(255,255,255,0.05),transparent_34%),linear-gradient(180deg,rgba(10,22,45,0.96),rgba(9,20,40,0.94))]" />

      {/* animated glow blobs */}
      <motion.div
        className="absolute -left-20 top-10 h-72 w-72 rounded-full bg-blue-400/10 blur-3xl"
        animate={{ x: [0, 24, 0], y: [0, 16, 0], opacity: [0.4, 0.65, 0.4] }}
        transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute right-0 top-0 h-80 w-80 rounded-full bg-cyan-300/10 blur-3xl"
        animate={{ x: [0, -20, 0], y: [0, 18, 0], opacity: [0.35, 0.55, 0.35] }}
        transition={{ duration: 14, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute bottom-0 left-1/3 h-72 w-72 rounded-full bg-indigo-400/10 blur-3xl"
        animate={{ x: [0, 16, 0], y: [0, -16, 0], opacity: [0.25, 0.45, 0.25] }}
        transition={{ duration: 16, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* subtle grid */}
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.05)_1px,transparent_1px)] bg-[size:44px_44px] opacity-[0.18]" />

      {/* svg rings + paths */}
      <svg
        className="absolute inset-0 h-full w-full"
        viewBox="0 0 1440 900"
        fill="none"
        preserveAspectRatio="xMidYMid slice"
      >
        {ringGroups.map((group) => (
          <motion.g
            key={group.id}
            animate={{
              x: [0, group.dx, 0],
              y: [0, group.dy, 0],
              opacity: [0.14, 0.24, 0.14],
            }}
            transition={{
              duration: group.duration,
              repeat: Infinity,
              ease: "easeInOut",
            }}
          >
            {group.radii.map((r, idx) => (
              <circle
                key={`${group.id}-${r}-${idx}`}
                cx={group.cx}
                cy={group.cy}
                r={r}
                stroke="rgba(203,213,225,0.45)"
                strokeWidth="1.4"
              />
            ))}
          </motion.g>
        ))}

        {paths.map((d, index) => (
          <motion.path
            key={index}
            d={d}
            stroke="rgba(148,163,184,0.28)"
            strokeWidth="1.6"
            strokeLinecap="round"
            animate={{
              pathLength: [0.15, 1, 0.15],
              opacity: [0.08, 0.25, 0.08],
            }}
            transition={{
              duration: 10 + index * 2,
              repeat: Infinity,
              ease: "easeInOut",
            }}
          />
        ))}
      </svg>

      {/* soft top light */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,rgba(255,255,255,0.10),transparent_34%)]" />
    </div>
  );
}