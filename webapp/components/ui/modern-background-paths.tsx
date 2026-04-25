"use client";

import { motion } from "framer-motion";

type BackgroundPathsProps = {
  className?: string;
  variant?: "light" | "dark";
};

type SpiralSpec = {
  cx: number;
  cy: number;
  turns: number;
  spacing: number;
  startAngle: number;
  scaleX?: number;
  scaleY?: number;
  delay: number;
};

const spirals: SpiralSpec[] = [
  { cx: 16, cy: 25, turns: 3.2, spacing: 2.1, startAngle: 0.2, delay: 0 },
  { cx: 38, cy: 24, turns: 3.4, spacing: 2.0, startAngle: 0.6, delay: 0.2 },
  { cx: 78, cy: 42, turns: 3.0, spacing: 2.2, startAngle: 1.1, delay: 0.4 },
  { cx: 22, cy: 58, turns: 3.8, spacing: 2.0, startAngle: 0.4, delay: 0.6 },
  { cx: 46, cy: 55, turns: 3.2, spacing: 2.0, startAngle: 1.5, delay: 0.8 },
  { cx: 69, cy: 58, turns: 3.5, spacing: 2.1, startAngle: 0.9, delay: 1.0 },
  { cx: 88, cy: 66, turns: 3.0, spacing: 2.2, startAngle: 1.7, delay: 1.2 },
  { cx: 62, cy: 82, turns: 3.6, spacing: 2.0, startAngle: 0.1, delay: 1.4 },
];

function buildSpiralPath(spec: SpiralSpec) {
  const points: string[] = [];
  const total = spec.turns * Math.PI * 2;
  const steps = 190;
  const scaleX = spec.scaleX ?? 1;
  const scaleY = spec.scaleY ?? 1;

  for (let index = 0; index <= steps; index++) {
    const progress = index / steps;
    const angle = spec.startAngle + progress * total;
    const radius = progress * spec.turns * spec.spacing;

    const x = spec.cx + Math.cos(angle) * radius * scaleX;
    const y = spec.cy + Math.sin(angle) * radius * scaleY;

    points.push(`${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`);
  }

  return points.join(" ");
}

export default function BackgroundPaths({
  className = "",
  variant = "light",
}: BackgroundPathsProps) {
  const isLight = variant === "light";

  return (
    <div
      className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}
    >
      <div
        className={
          isLight
            ? "absolute inset-0 bg-[radial-gradient(circle_at_50%_42%,rgba(219,234,254,0.95),transparent_34%),linear-gradient(180deg,#ffffff_0%,#f8fafc_58%,#eef6ff_100%)]"
            : "absolute inset-0 bg-[linear-gradient(135deg,#020617_0%,#081126_42%,#172554_100%)]"
        }
      />

      <motion.div
        animate={{
          opacity: isLight ? [0.18, 0.32, 0.18] : [0.12, 0.24, 0.12],
          scale: [1, 1.025, 1],
        }}
        transition={{
          duration: 8,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className={
          isLight
            ? "absolute left-1/2 top-1/2 h-[780px] w-[780px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-200/50 blur-3xl"
            : "absolute left-1/2 top-1/2 h-[780px] w-[780px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-500/20 blur-3xl"
        }
      />

      <motion.svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full"
        animate={{
          x: [0, -10, 0],
          y: [0, 6, 0],
        }}
        transition={{
          duration: 18,
          repeat: Infinity,
          ease: "easeInOut",
        }}
      >
        {spirals.map((spec, index) => (
          <motion.path
            key={index}
            d={buildSpiralPath(spec)}
            fill="none"
            stroke={isLight ? "rgb(148 163 184)" : "rgb(125 211 252)"}
            strokeWidth={isLight ? 0.22 : 0.16}
            strokeLinecap="round"
            opacity={isLight ? 0.34 : 0.22}
            initial={{ pathLength: 0.45 }}
            animate={{
              pathLength: [0.45, 1, 0.72],
              opacity: isLight ? [0.2, 0.45, 0.24] : [0.12, 0.35, 0.16],
            }}
            transition={{
              duration: 9 + index * 0.6,
              delay: spec.delay,
              repeat: Infinity,
              ease: "easeInOut",
            }}
          />
        ))}
      </motion.svg>

      <motion.div
        animate={{
          x: ["-15%", "115%"],
          opacity: [0, 0.5, 0],
        }}
        transition={{
          duration: 9,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className={
          isLight
            ? "absolute top-[42%] h-48 w-48 rounded-full bg-blue-200/30 blur-3xl"
            : "absolute top-[42%] h-48 w-48 rounded-full bg-cyan-300/20 blur-3xl"
        }
      />

      <div
        className={
          isLight
            ? "absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-slate-950"
            : "absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-slate-950"
        }
      />
    </div>
  );
}