"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

type BackgroundPathsProps = {
  className?: string;
  variant?: "light" | "dark";
};

const paths = [
  "M120 260 C80 180 130 105 225 105 C320 105 370 185 330 260 C290 335 170 335 150 250 C130 165 250 135 270 210 C290 285 190 285 205 220",
  "M440 255 C390 155 455 80 565 90 C675 100 725 205 660 285 C595 365 460 335 470 230 C480 125 625 135 625 225 C625 315 515 300 535 225",
  "M790 300 C690 220 730 95 850 95 C970 95 1040 220 970 325 C900 430 740 395 760 260 C780 125 950 145 945 265 C940 385 805 360 825 260",
  "M180 620 C60 520 90 340 245 320 C400 300 500 430 450 570 C400 710 170 715 140 520 C110 325 365 335 375 505 C385 675 175 640 220 500",
  "M570 660 C430 540 455 350 635 330 C815 310 900 475 825 625 C750 775 485 760 500 535 C515 310 795 340 780 560 C765 780 525 720 570 525",
  "M960 640 C820 535 850 365 1015 350 C1180 335 1255 485 1190 625 C1125 765 880 755 900 545 C920 335 1165 365 1150 565 C1135 765 925 710 960 545",
  "M280 170 C370 250 455 290 555 260 C655 230 720 250 800 330 C880 410 965 415 1060 365",
  "M120 470 C250 390 370 390 500 455 C630 520 770 525 900 455 C1030 385 1130 405 1210 485",
];

export default function BackgroundPaths({
  className,
  variant = "light",
}: BackgroundPathsProps) {
  const isLight = variant === "light";

  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 overflow-hidden",
        isLight ? "bg-slate-50" : "bg-slate-950",
        className
      )}
    >
      <div
        className={cn(
          "absolute inset-0",
          isLight
            ? "bg-[radial-gradient(circle_at_top_left,rgba(59,130,246,0.10),transparent_32%),radial-gradient(circle_at_bottom_right,rgba(236,72,153,0.08),transparent_28%)]"
            : "bg-[radial-gradient(circle_at_top_left,rgba(59,130,246,0.22),transparent_32%),radial-gradient(circle_at_bottom_right,rgba(236,72,153,0.12),transparent_28%)]"
        )}
      />

      <motion.div
        animate={{
          opacity: isLight ? [0.25, 0.42, 0.25] : [0.18, 0.32, 0.18],
        }}
        transition={{
          duration: 7,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className="absolute inset-0"
      >
        <svg
          className="absolute inset-0 h-full w-full"
          viewBox="0 0 1280 800"
          preserveAspectRatio="xMidYMid slice"
          fill="none"
        >
          {paths.map((path, index) => (
            <motion.path
              key={path}
              d={path}
              stroke={isLight ? "#94a3b8" : "#60a5fa"}
              strokeWidth={index < 6 ? 2.2 : 1.6}
              strokeLinecap="round"
              initial={{
                pathLength: 0.25,
                opacity: 0.12,
              }}
              animate={{
                pathLength: [0.35, 1, 0.35],
                opacity: isLight ? [0.18, 0.48, 0.18] : [0.12, 0.36, 0.12],
              }}
              transition={{
                duration: 8 + index * 0.8,
                repeat: Infinity,
                ease: "easeInOut",
                delay: index * 0.2,
              }}
            />
          ))}
        </svg>
      </motion.div>

      <motion.div
        animate={{
          x: [0, 80, -40, 0],
          y: [0, -40, 20, 0],
          scale: [1, 1.12, 0.96, 1],
        }}
        transition={{
          duration: 18,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className={cn(
          "absolute left-[8%] top-[10%] h-72 w-72 rounded-full blur-3xl",
          isLight ? "bg-blue-300/25" : "bg-blue-500/18"
        )}
      />

      <motion.div
        animate={{
          x: [0, -60, 35, 0],
          y: [0, 36, -24, 0],
          scale: [1, 0.94, 1.1, 1],
        }}
        transition={{
          duration: 22,
          repeat: Infinity,
          ease: "easeInOut",
        }}
        className={cn(
          "absolute right-[10%] top-[20%] h-80 w-80 rounded-full blur-3xl",
          isLight ? "bg-fuchsia-200/25" : "bg-cyan-400/14"
        )}
      />

      <motion.div
        animate={{
          y: ["-15%", "115%"],
        }}
        transition={{
          duration: 11,
          repeat: Infinity,
          ease: "linear",
        }}
        className={cn(
          "absolute left-0 right-0 h-24 blur-xl",
          isLight
            ? "bg-gradient-to-b from-transparent via-blue-200/25 to-transparent"
            : "bg-gradient-to-b from-transparent via-cyan-300/8 to-transparent"
        )}
      />
    </div>
  );
}