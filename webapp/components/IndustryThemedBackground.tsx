"use client";

import { motion } from "framer-motion";
import BackgroundPaths from "@/components/modern-background-paths";
import { getIndustryTheme } from "@/lib/stickers";

type IndustryThemedBackgroundProps = {
  industry?: string | null;
  className?: string;
  variant?: "light" | "dark";
};

export default function IndustryThemedBackground({
  industry,
  className = "",
  variant = "light",
}: IndustryThemedBackgroundProps) {
  const theme = getIndustryTheme(industry);
  const isLight = variant === "light";

  return (
    <div className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}>
      <BackgroundPaths variant={variant} />

      <div
        className={
          isLight
            ? "absolute inset-0 bg-gradient-to-b from-white/55 via-blue-50/55 to-cyan-50/70"
            : "absolute inset-0 bg-slate-950/70"
        }
      />

      <motion.div
        animate={{
          x: [0, 55, -24, 0],
          y: [0, -35, 24, 0],
          scale: [1, 1.08, 0.97, 1],
        }}
        transition={{ duration: 18, repeat: Infinity, ease: "easeInOut" }}
        className="absolute -left-10 top-8 h-72 w-72 rounded-full blur-3xl"
        style={{
          background: `radial-gradient(circle, ${theme.glow1} 0%, transparent 70%)`,
          opacity: isLight ? 0.85 : 1,
        }}
      />

      <motion.div
        animate={{
          x: [0, -42, 24, 0],
          y: [0, 22, -28, 0],
          scale: [1, 0.94, 1.12, 1],
        }}
        transition={{ duration: 22, repeat: Infinity, ease: "easeInOut" }}
        className="absolute right-[-6%] top-[14%] h-80 w-80 rounded-full blur-3xl"
        style={{
          background: `radial-gradient(circle, ${theme.glow2} 0%, transparent 72%)`,
          opacity: isLight ? 0.9 : 1,
        }}
      />

      <motion.div
        animate={{
          x: [0, 28, -16, 0],
          y: [0, -18, 12, 0],
          scale: [1, 1.03, 0.98, 1],
        }}
        transition={{ duration: 20, repeat: Infinity, ease: "easeInOut" }}
        className="absolute bottom-[-10%] left-[38%] h-72 w-72 rounded-full blur-3xl"
        style={{
          background: `radial-gradient(circle, ${theme.glow3} 0%, transparent 72%)`,
          opacity: isLight ? 0.85 : 1,
        }}
      />

      <motion.div
        animate={{ y: [0, -14, 0], rotate: [0, 6, 0] }}
        transition={{ duration: 8, repeat: Infinity, ease: "easeInOut" }}
        className={isLight ? "absolute left-[7%] top-[16%] text-7xl opacity-[0.07]" : "absolute left-[7%] top-[16%] text-7xl opacity-[0.08]"}
      >
        {theme.iconA}
      </motion.div>

      <motion.div
        animate={{ y: [0, 18, 0], rotate: [0, -8, 0] }}
        transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }}
        className={isLight ? "absolute right-[10%] top-[26%] text-6xl opacity-[0.07]" : "absolute right-[10%] top-[26%] text-6xl opacity-[0.08]"}
      >
        {theme.iconB}
      </motion.div>
    </div>
  );
}