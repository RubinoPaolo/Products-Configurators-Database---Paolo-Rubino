"use client";

import Link from "next/link";
import { useState } from "react";
import { motion } from "framer-motion";
import {
  ArrowUpRight,
  ChevronDown,
  ChevronUp,
  Medal,
  Trophy,
} from "lucide-react";

type RankingItem = {
  id: number;
  slug: string;
  company: string;
  industry: string | null;
  product: string | null;
  country: string | null;
  visualizationType: string | null;
  intelligenceScore: number | null;
};

type HomeLeaderboardProps = {
  items: RankingItem[];
};

function scoreLabel(value: number | null) {
  return typeof value === "number" ? value.toFixed(2) : "N/A";
}

function scorePercent(value: number | null) {
  if (typeof value !== "number") return 0;
  return Math.max(0, Math.min(100, (value / 5) * 100));
}

function rankConfig(rank: 1 | 2 | 3) {
  if (rank === 1) {
    return {
      medal: "🥇",
      label: "Champion",
      pedestal: "h-20 sm:h-28 lg:h-32",
      card:
        "border-yellow-300/70 bg-gradient-to-br from-yellow-50 via-white to-blue-50",
      glow: "bg-yellow-300/35",
      score: "text-yellow-800 bg-yellow-200/70",
      pedestalClass:
        "from-yellow-300 via-yellow-200 to-yellow-100 text-yellow-950",
      icon: Trophy,
      desktopLift: "lg:-translate-y-6",
    };
  }

  if (rank === 2) {
    return {
      medal: "🥈",
      label: "Runner-up",
      pedestal: "h-16 sm:h-22 lg:h-24",
      card:
        "border-slate-300/80 bg-gradient-to-br from-slate-50 via-white to-blue-50",
      glow: "bg-slate-300/35",
      score: "text-slate-800 bg-slate-200/80",
      pedestalClass:
        "from-slate-300 via-slate-200 to-slate-100 text-slate-950",
      icon: Medal,
      desktopLift: "",
    };
  }

  return {
    medal: "🥉",
    label: "Third place",
    pedestal: "h-14 sm:h-18 lg:h-20",
    card:
      "border-orange-300/70 bg-gradient-to-br from-orange-50 via-white to-blue-50",
    glow: "bg-orange-300/35",
    score: "text-orange-800 bg-orange-200/70",
    pedestalClass:
      "from-orange-300 via-orange-200 to-orange-100 text-orange-950",
    icon: Medal,
    desktopLift: "",
  };
}

function PodiumCard({
  item,
  rank,
}: {
  item: RankingItem;
  rank: 1 | 2 | 3;
}) {
  const config = rankConfig(rank);
  const Icon = config.icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 28, scale: 0.96 }}
      whileInView={{ opacity: 1, y: 0, scale: 1 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{
        duration: 0.65,
        delay: rank === 1 ? 0 : rank === 2 ? 0.12 : 0.2,
        ease: [0.22, 1, 0.36, 1],
      }}
      className={`relative flex min-w-0 flex-col justify-end ${config.desktopLift}`}
    >
      <div
        className={`absolute -inset-4 rounded-[2rem] blur-3xl sm:-inset-5 ${config.glow}`}
      />

      <Link
        href={`/configurators/${item.slug}`}
        className={`group relative min-w-0 overflow-hidden rounded-t-[1.75rem] border p-5 shadow-xl backdrop-blur transition duration-300 hover:-translate-y-1 sm:rounded-t-[2rem] sm:p-6 lg:hover:-translate-y-2 ${config.card}`}
      >
        <div className="absolute inset-0 opacity-0 transition duration-500 group-hover:opacity-100">
          <div className="absolute -right-12 -top-12 h-36 w-36 rounded-full bg-blue-300/35 blur-3xl" />
          <div className="absolute -bottom-10 left-8 h-28 w-28 rounded-full bg-cyan-300/25 blur-3xl" />
        </div>

        <div className="relative flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/70 px-3 py-1 text-xs font-bold text-slate-600 shadow-sm">
              <Icon size={14} />
              {config.label}
            </div>

            <p className="mt-4 text-sm text-slate-500">
              {item.industry || "Unknown industry"}
            </p>

            <h3
              className={
                rank === 1
                  ? "mt-2 break-words text-2xl font-black text-slate-950 sm:text-3xl"
                  : "mt-2 break-words text-xl font-black text-slate-950 sm:text-2xl"
              }
            >
              {item.company}
            </h3>
          </div>

          <div className="shrink-0 text-3xl sm:text-4xl">{config.medal}</div>
        </div>

        <p className="relative mt-4 line-clamp-2 text-sm text-slate-600 sm:text-base">
          {item.product || "No product specified"}
        </p>

        <div className="relative mt-5 flex flex-wrap gap-2">
          <span className="rounded-full border border-slate-200 bg-white/75 px-3 py-1 text-xs text-slate-600 sm:text-sm">
            {item.country || "Unknown country"}
          </span>

          <span className="rounded-full border border-slate-200 bg-white/75 px-3 py-1 text-xs text-slate-600 sm:text-sm">
            {item.visualizationType || "Unknown type"}
          </span>
        </div>

        <div className="relative mt-5 rounded-2xl border border-slate-200 bg-white/75 p-4 shadow-sm sm:mt-6">
          <div className="flex items-center justify-between gap-4">
            <span className="text-xs text-slate-600 sm:text-sm">
              Overall Configurator Score
            </span>
            <span
              className={`rounded-full px-3 py-1 text-xs font-black sm:text-sm ${config.score}`}
            >
              {scoreLabel(item.intelligenceScore)}
            </span>
          </div>

          <div className="mt-3 h-2 rounded-full bg-slate-200">
            <div
              className="h-2 rounded-full bg-gradient-to-r from-blue-500 via-cyan-400 to-emerald-400"
              style={{ width: `${scorePercent(item.intelligenceScore)}%` }}
            />
          </div>
        </div>

        <div className="relative mt-5 inline-flex items-center gap-2 text-sm font-bold text-blue-600 transition group-hover:text-cyan-600">
          View profile
          <ArrowUpRight size={16} />
        </div>
      </Link>

      <div
        className={`relative flex items-center justify-center rounded-b-[1.75rem] border-x border-b border-white/60 bg-gradient-to-b text-lg font-black shadow-xl sm:rounded-b-[2rem] sm:text-xl ${config.pedestal} ${config.pedestalClass}`}
      >
        <span className="rounded-full border border-white/70 bg-white/50 px-4 py-1.5 sm:px-5 sm:py-2">
          #{rank}
        </span>
      </div>
    </motion.div>
  );
}

export default function HomeLeaderboard({ items }: HomeLeaderboardProps) {
  const [expanded, setExpanded] = useState(false);

  const first = items[0];
  const second = items[1];
  const third = items[2];

  const rest = items.slice(3);
  const visibleRest = expanded ? rest : rest.slice(0, 6);

  return (
    <div className="space-y-8 sm:space-y-10">
      <div className="grid gap-8 lg:grid-cols-3 lg:items-end">
        {first && (
          <div className="lg:col-start-2 lg:row-start-1">
            <PodiumCard item={first} rank={1} />
          </div>
        )}

        {second && (
          <div className="lg:col-start-1 lg:row-start-1">
            <PodiumCard item={second} rank={2} />
          </div>
        )}

        {third && (
          <div className="lg:col-start-3 lg:row-start-1">
            <PodiumCard item={third} rank={3} />
          </div>
        )}
      </div>

      {rest.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 22 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          className="relative overflow-hidden rounded-[1.75rem] border border-slate-200 bg-white/75 p-4 shadow-xl backdrop-blur sm:rounded-[2rem] sm:p-6"
        >
          <div className="absolute -right-16 -top-16 h-48 w-48 rounded-full bg-blue-300/25 blur-3xl" />

          <div className="relative flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-xs font-black uppercase tracking-[0.25em] text-blue-600 sm:text-sm sm:tracking-[0.3em]">
                Extended ranking
              </p>
              <h3 className="mt-2 text-xl font-black text-slate-950 sm:text-2xl">
                From 4th place onward
              </h3>
            </div>

            <div className="rounded-full border border-slate-200 bg-white/75 px-4 py-2 text-xs text-slate-600 shadow-sm sm:text-sm">
              {rest.length} additional configurators
            </div>
          </div>

          <div className="relative mt-6 grid gap-3">
            {visibleRest.map((item, index) => {
              const rank = index + 4;

              return (
                <Link
                  key={item.id}
                  href={`/configurators/${item.slug}`}
                  className="group grid gap-4 rounded-2xl border border-slate-200 bg-white/70 p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-blue-200 hover:bg-blue-50/70 md:grid-cols-[1fr_auto] md:items-center"
                >
                  <div className="flex min-w-0 items-center gap-3 sm:gap-4">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-blue-100 font-black text-blue-700 sm:h-11 sm:w-11">
                      {rank}
                    </div>

                    <div className="min-w-0">
                      <p className="break-words font-black text-slate-950">
                        {item.company}
                      </p>
                      <p className="line-clamp-2 text-sm text-slate-500">
                        {item.product || "No product specified"} ·{" "}
                        {item.industry || "Unknown industry"}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center justify-between gap-3 md:justify-end">
                    <span className="hidden rounded-full border border-slate-200 bg-white/75 px-3 py-1 text-sm text-slate-600 md:inline-flex">
                      {item.country || "Unknown country"}
                    </span>

                    <div className="min-w-32 sm:min-w-36">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-xs text-slate-500">Score</span>
                        <span className="font-black text-blue-600">
                          {scoreLabel(item.intelligenceScore)}
                        </span>
                      </div>

                      <div className="mt-2 h-1.5 rounded-full bg-slate-200">
                        <div
                          className="h-1.5 rounded-full bg-gradient-to-r from-blue-500 via-cyan-400 to-emerald-400"
                          style={{
                            width: `${scorePercent(item.intelligenceScore)}%`,
                          }}
                        />
                      </div>
                    </div>

                    <ArrowUpRight
                      size={18}
                      className="shrink-0 text-slate-400 transition group-hover:text-blue-600"
                    />
                  </div>
                </Link>
              );
            })}
          </div>

          {rest.length > 6 && (
            <div className="relative mt-6">
              <button
                type="button"
                onClick={() => setExpanded((current) => !current)}
                className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white/75 px-5 py-3 font-bold text-slate-900 shadow-sm transition hover:-translate-y-0.5 hover:bg-white sm:w-auto"
              >
                {expanded ? (
                  <>
                    Show fewer
                    <ChevronUp size={18} />
                  </>
                ) : (
                  <>
                    Show all remaining configurators
                    <ChevronDown size={18} />
                  </>
                )}
              </button>
            </div>
          )}
        </motion.div>
      )}
    </div>
  );
}