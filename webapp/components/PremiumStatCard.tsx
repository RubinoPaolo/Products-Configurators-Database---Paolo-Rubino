"use client";

import { motion } from "framer-motion";
import {
  Activity,
  Database,
  Globe2,
  Layers3,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

type IconName = "database" | "activity" | "layers" | "globe" | "sparkles";

type PremiumStatCardProps = {
  label: string;
  value: number | string;
  iconName?: IconName;
  delay?: number;
  variant?: "dark" | "light";
};

const icons: Record<IconName, LucideIcon> = {
  database: Database,
  activity: Activity,
  layers: Layers3,
  globe: Globe2,
  sparkles: Sparkles,
};

export default function PremiumStatCard({
  label,
  value,
  iconName = "sparkles",
  delay = 0,
  variant = "dark",
}: PremiumStatCardProps) {
  const Icon = icons[iconName];
  const isLight = variant === "light";

  return (
    <motion.div
      initial={{ opacity: 0, y: 18, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{
        duration: 0.55,
        delay,
        ease: [0.22, 1, 0.36, 1],
      }}
      whileHover={{
        y: -5,
        scale: 1.018,
      }}
      className={
        isLight
          ? "group relative overflow-hidden rounded-3xl border border-slate-200/80 bg-white/75 p-6 shadow-xl backdrop-blur"
          : "group relative overflow-hidden rounded-3xl border border-white/10 bg-white/[0.08] p-6 shadow-2xl backdrop-blur"
      }
    >
      <div
        className={
          isLight
            ? "absolute inset-0 bg-gradient-to-br from-blue-50 via-transparent to-cyan-50 opacity-0 transition duration-500 group-hover:opacity-100"
            : "absolute inset-0 bg-gradient-to-br from-white/10 via-transparent to-blue-500/10 opacity-0 transition duration-500 group-hover:opacity-100"
        }
      />

      <div
        className={
          isLight
            ? "absolute -right-10 -top-10 h-28 w-28 rounded-full bg-blue-300/20 blur-2xl transition group-hover:bg-blue-400/25"
            : "absolute -right-10 -top-10 h-28 w-28 rounded-full bg-blue-500/10 blur-2xl transition group-hover:bg-blue-400/20"
        }
      />

      <div className="relative flex items-start justify-between gap-4">
        <div>
          <p className={isLight ? "text-sm text-slate-500" : "text-sm text-slate-300"}>
            {label}
          </p>
          <p className={isLight ? "mt-2 text-4xl font-bold text-slate-950" : "mt-2 text-4xl font-bold text-white"}>
            {value}
          </p>
        </div>

        <div
          className={
            isLight
              ? "flex h-11 w-11 items-center justify-center rounded-2xl border border-slate-200 bg-white text-blue-600 shadow-sm"
              : "flex h-11 w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/10 text-blue-200 shadow-lg"
          }
        >
          <Icon size={22} />
        </div>
      </div>
    </motion.div>
  );
}