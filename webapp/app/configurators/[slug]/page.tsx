import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import {
  ArrowUpRight,
  BadgeCheck,
  Database,
  ExternalLink,
  Gauge,
  Globe2,
  Layers3,
  LinkIcon,
  Radar,
  Sparkles,
  XCircle,
} from "lucide-react";
import AnimatedSection from "@/components/AnimatedSection";
import CountryFlag from "@/components/CountryFlag";
import IndustryThemedBackground from "@/components/IndustryThemedBackground";
import ScoreThermometer from "@/components/ScoreThermometer";
import {
  getIndustrySticker,
  getProductSticker,
  getVisualizationSticker,
} from "@/lib/stickers";
import { prisma } from "@/lib/prisma";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type PageProps = {
  params: Promise<{
    slug: string;
  }>;
};

function label(value: string | null | undefined, fallback = "Not available") {
  return value && value.trim().length > 0 ? value : fallback;
}

function scoreLabel(value: number | null | undefined) {
  if (typeof value !== "number") return "N/A";
  return value.toFixed(2);
}

function scorePercent(value: number | null | undefined) {
  if (typeof value !== "number") return 0;
  return Math.max(0, Math.min(100, (value / 5) * 100));
}

function scoreTone(value: number | null | undefined) {
  if (typeof value !== "number") {
    return {
      text: "text-slate-600",
      bg: "bg-slate-100",
      bar: "from-slate-400 to-slate-300",
      label: "Not evaluated",
    };
  }

  if (value >= 4) {
    return {
      text: "text-emerald-700",
      bg: "bg-emerald-50",
      bar: "from-emerald-500 to-cyan-400",
      label: "Strong",
    };
  }

  if (value >= 3) {
    return {
      text: "text-yellow-700",
      bg: "bg-yellow-50",
      bar: "from-yellow-400 to-orange-400",
      label: "Moderate",
    };
  }

  return {
    text: "text-red-700",
    bg: "bg-red-50",
    bar: "from-red-500 to-orange-500",
    label: "Weak",
  };
}

function statusLabel(value: boolean | null) {
  if (value === true) return "Active";
  if (value === false) return "Inactive";
  return "Unknown";
}

function StatusBadge({ value }: { value: boolean | null }) {
  if (value === true) {
    return (
      <span className="inline-flex w-fit items-center gap-2 rounded-full bg-emerald-100 px-4 py-2 text-sm font-black text-emerald-700">
        <BadgeCheck size={16} />
        Active
      </span>
    );
  }

  if (value === false) {
    return (
      <span className="inline-flex w-fit items-center gap-2 rounded-full bg-red-100 px-4 py-2 text-sm font-black text-red-700">
        <XCircle size={16} />
        Inactive
      </span>
    );
  }

  return (
    <span className="inline-flex w-fit items-center gap-2 rounded-full bg-slate-100 px-4 py-2 text-sm font-black text-slate-600">
      Unknown status
    </span>
  );
}

type OverviewCardProps = {
  title: string;
  value: string;
  sticker: ReactNode;
};

function OverviewCard({ title, value, sticker }: OverviewCardProps) {
  return (
    <div className="group relative overflow-hidden rounded-2xl border border-slate-100 bg-white/80 p-5 shadow-sm backdrop-blur transition hover:-translate-y-0.5 hover:border-blue-200 hover:bg-white">
      <div className="absolute -right-10 -top-10 h-24 w-24 rounded-full bg-blue-300/20 blur-2xl opacity-0 transition group-hover:opacity-100" />
      <div className="absolute right-4 top-4">{sticker}</div>

      <dt className="relative text-sm font-semibold text-slate-500">{title}</dt>
      <dd className="relative mt-2 pr-16 text-lg font-black text-slate-950">
        {value}
      </dd>
    </div>
  );
}

function EmojiSticker({ value }: { value: string }) {
  return (
    <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-slate-200 bg-white text-2xl shadow-sm">
      {value}
    </div>
  );
}

function IntelligenceSnapshot({
  mobileScore,
  compatibilityScore,
  complexityScore,
  visualizationType,
  overallScore,
}: {
  mobileScore: number | null;
  compatibilityScore: number | null;
  complexityScore: number | null;
  visualizationType: string | null;
  overallScore: number | null;
}) {
  const overallTone = scoreTone(overallScore);

  const insights = [
    {
      title: "Mobile readiness",
      value:
        mobileScore === null
          ? "Mobile optimization has not been evaluated for this configurator."
          : mobileScore >= 4
            ? "This configurator appears strong on mobile experience."
            : mobileScore === 3
              ? "Mobile experience looks acceptable but not best-in-class."
              : "Mobile experience may need attention.",
    },
    {
      title: "Configuration depth",
      value:
        complexityScore === null
          ? "Complexity has not been evaluated."
          : complexityScore >= 4
            ? "The configurator offers a rich or advanced configuration flow."
            : complexityScore === 3
              ? "The configurator has a moderate level of complexity."
              : "The configurator appears relatively simple.",
    },
    {
      title: "Compatibility logic",
      value:
        compatibilityScore === null
          ? "Compatibility rules have not been evaluated."
          : compatibilityScore >= 4
            ? "Compatibility constraints appear well represented."
            : compatibilityScore === 3
              ? "Compatibility rules appear present but limited."
              : "Compatibility logic appears weak or minimal.",
    },
    {
      title: "Visualization",
      value: visualizationType
        ? `The configurator uses ${visualizationType} visualization.`
        : "Visualization type is not available.",
    },
  ];

  return (
    <div className="rounded-3xl border border-slate-200 bg-white/80 p-6 shadow-xl backdrop-blur">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-black uppercase tracking-[0.3em] text-blue-600">
            Intelligence snapshot
          </p>
          <h2 className="mt-3 text-2xl font-black text-slate-950">
            Configurator intelligence summary
          </h2>
        </div>

        <div className={`rounded-2xl px-4 py-3 text-right ${overallTone.bg}`}>
          <p
            className={`text-xs font-black uppercase tracking-[0.18em] ${overallTone.text}`}
          >
            Overall
          </p>
          <p className={`text-2xl font-black ${overallTone.text}`}>
            {scoreLabel(overallScore)}
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {insights.map((item) => (
          <div
            key={item.title}
            className="rounded-2xl border border-slate-100 bg-white/75 p-4 shadow-sm"
          >
            <p className="font-black text-slate-950">{item.title}</p>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              {item.value}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default async function ConfiguratorDetailPage({ params }: PageProps) {
  const { slug } = await params;

  const configurator = await prisma.configurator.findUnique({
    where: {
      slug,
    },
  });

  if (!configurator) {
    notFound();
  }

  const similarConfigurators = await prisma.configurator.findMany({
    where: {
      id: {
        not: configurator.id,
      },
      industry: configurator.industry,
      isActive: true,
      intelligenceScore: {
        not: null,
      },
    },
    orderBy: [
      {
        intelligenceScore: "desc",
      },
      {
        company: "asc",
      },
    ],
    take: 3,
  });

  const mainUrl =
    configurator.alternativeUrl || configurator.configuratorUrl || null;

  const overallTone = scoreTone(configurator.intelligenceScore);

  return (
    <main className="relative isolate min-h-screen overflow-hidden bg-slate-50 text-slate-950">
      <IndustryThemedBackground
        industry={configurator.industry}
        variant="light"
      />

      <section className="relative z-10 border-b border-slate-200 bg-white/40">
        <div className="mx-auto max-w-6xl px-6 py-10">
          <Link
            href="/configurators"
            className="text-sm font-black text-blue-600 transition hover:text-blue-500"
          >
            ← Back to database
          </Link>

          <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_0.38fr] lg:items-end">
            <div>
              <p className="text-sm font-black uppercase tracking-[0.3em] text-blue-600">
                Configurator profile
              </p>

              <h1 className="mt-3 text-5xl font-black tracking-tight text-slate-950 md:text-7xl">
                {configurator.company}
              </h1>

              <p className="mt-4 max-w-3xl text-xl text-slate-600">
                {label(configurator.product, "No product specified")}
              </p>

              <div className="mt-7 flex flex-wrap gap-3">
                <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/75 px-4 py-2 text-sm font-bold text-slate-700 shadow-sm backdrop-blur">
                  <span>{getIndustrySticker(configurator.industry)}</span>
                  {label(configurator.industry)}
                </span>

                <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/75 px-4 py-2 text-sm font-bold text-slate-700 shadow-sm backdrop-blur">
                  <Globe2 size={16} className="text-blue-600" />
                  {label(configurator.country)}
                </span>

                <StatusBadge value={configurator.isActive} />
              </div>
            </div>

            <div className="rounded-[2rem] border border-slate-200 bg-white/80 p-6 shadow-xl backdrop-blur">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-black uppercase tracking-[0.25em] text-blue-600">
                    Overall score
                  </p>
                  <p className="mt-2 text-5xl font-black text-slate-950">
                    {scoreLabel(configurator.intelligenceScore)}
                  </p>
                </div>

                <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-blue-100 bg-blue-50 text-blue-600">
                  <Gauge size={26} />
                </div>
              </div>

              <div className="mt-5 h-2 rounded-full bg-slate-200">
                <div
                  className={`h-2 rounded-full bg-gradient-to-r ${overallTone.bar}`}
                  style={{
                    width: `${scorePercent(configurator.intelligenceScore)}%`,
                  }}
                />
              </div>

              <p className={`mt-4 text-sm font-black ${overallTone.text}`}>
                {overallTone.label} benchmark profile
              </p>
            </div>
          </div>

          <div className="mt-8 flex flex-wrap gap-3">
            {mainUrl && (
              <a
                href={mainUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-3 font-bold text-white shadow-lg shadow-blue-500/20 transition hover:-translate-y-0.5 hover:bg-blue-500"
              >
                Open configurator
                <ExternalLink size={17} />
              </a>
            )}

            {configurator.databaseDetailUrl && (
              <a
                href={configurator.databaseDetailUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white/80 px-5 py-3 font-bold text-slate-900 shadow-sm transition hover:-translate-y-0.5 hover:bg-white"
              >
                Original database page
                <ArrowUpRight size={17} />
              </a>
            )}
          </div>
        </div>
      </section>

      <section className="relative z-10 mx-auto grid max-w-6xl gap-6 px-6 py-8 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <AnimatedSection>
            <div className="rounded-3xl border border-slate-200 bg-white/80 p-6 shadow-xl backdrop-blur">
              <div className="flex items-center justify-between gap-4">
                <h2 className="text-2xl font-black text-slate-950">Overview</h2>
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-blue-100 bg-blue-50 text-blue-600">
                  <Layers3 size={21} />
                </div>
              </div>

              <dl className="mt-6 grid gap-4 md:grid-cols-2">
                <OverviewCard
                  title="Company"
                  value={configurator.company}
                  sticker={<EmojiSticker value="🏢" />}
                />

                <OverviewCard
                  title="Product"
                  value={label(configurator.product)}
                  sticker={
                    <EmojiSticker
                      value={getProductSticker(configurator.product)}
                    />
                  }
                />

                <OverviewCard
                  title="Industry"
                  value={label(configurator.industry)}
                  sticker={
                    <EmojiSticker
                      value={getIndustrySticker(configurator.industry)}
                    />
                  }
                />

                <OverviewCard
                  title="Country"
                  value={label(configurator.country)}
                  sticker={<CountryFlag country={configurator.country} />}
                />

                <OverviewCard
                  title="Visualization type"
                  value={label(configurator.visualizationType)}
                  sticker={
                    <EmojiSticker
                      value={getVisualizationSticker(
                        configurator.visualizationType
                      )}
                    />
                  }
                />

                <OverviewCard
                  title="Current status"
                  value={statusLabel(configurator.isActive)}
                  sticker={
                    configurator.isActive ? (
                      <EmojiSticker value="✅" />
                    ) : configurator.isActive === false ? (
                      <EmojiSticker value="⚠️" />
                    ) : (
                      <EmojiSticker value="❔" />
                    )
                  }
                />
              </dl>
            </div>
          </AnimatedSection>

          <AnimatedSection delay={0.05}>
            <IntelligenceSnapshot
              mobileScore={configurator.mobileScore}
              compatibilityScore={configurator.compatibilityScore}
              complexityScore={configurator.complexityScore}
              visualizationType={configurator.visualizationType}
              overallScore={configurator.intelligenceScore}
            />
          </AnimatedSection>

          <AnimatedSection delay={0.08}>
            <div className="rounded-3xl border border-slate-200 bg-white/80 p-6 shadow-xl backdrop-blur">
              <div className="flex items-center justify-between gap-4">
                <h2 className="text-2xl font-black text-slate-950">Links</h2>
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-blue-100 bg-blue-50 text-blue-600">
                  <LinkIcon size={21} />
                </div>
              </div>

              <div className="mt-5 space-y-4">
                <div className="rounded-2xl border border-slate-100 bg-white/75 p-4 shadow-sm">
                  <p className="text-sm font-semibold text-slate-500">
                    Configurator URL
                  </p>
                  {configurator.configuratorUrl ? (
                    <a
                      href={configurator.configuratorUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-1 block break-all font-semibold text-blue-600 hover:text-blue-500"
                    >
                      {configurator.configuratorUrl}
                    </a>
                  ) : (
                    <p className="mt-1 text-slate-600">Not available</p>
                  )}
                </div>

                <div className="rounded-2xl border border-slate-100 bg-white/75 p-4 shadow-sm">
                  <p className="text-sm font-semibold text-slate-500">
                    Alternative URL
                  </p>
                  {configurator.alternativeUrl ? (
                    <a
                      href={configurator.alternativeUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-1 block break-all font-semibold text-blue-600 hover:text-blue-500"
                    >
                      {configurator.alternativeUrl}
                    </a>
                  ) : (
                    <p className="mt-1 text-slate-600">Not available</p>
                  )}
                </div>
              </div>
            </div>
          </AnimatedSection>
        </div>

        <aside className="space-y-6">
          <AnimatedSection delay={0.04}>
            <div className="rounded-3xl border border-slate-200 bg-white/80 p-6 shadow-xl backdrop-blur">
              <div className="flex items-center justify-between gap-4">
                <h2 className="text-2xl font-black text-slate-950">
                  Score panel
                </h2>
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-blue-100 bg-blue-50 text-blue-600">
                  <Sparkles size={21} />
                </div>
              </div>

              <div className="mt-5 space-y-3">
                <div className="flex items-center justify-between gap-4 rounded-2xl border border-slate-100 bg-white/75 p-4 shadow-sm">
                  <span className="font-semibold text-slate-600">Mobile</span>
                  <ScoreThermometer
                    value={configurator.mobileScore}
                    variant="light"
                  />
                </div>

                <div className="flex items-center justify-between gap-4 rounded-2xl border border-slate-100 bg-white/75 p-4 shadow-sm">
                  <span className="font-semibold text-slate-600">
                    Compatibility rules
                  </span>
                  <ScoreThermometer
                    value={configurator.compatibilityScore}
                    variant="light"
                  />
                </div>

                <div className="flex items-center justify-between gap-4 rounded-2xl border border-slate-100 bg-white/75 p-4 shadow-sm">
                  <span className="font-semibold text-slate-600">
                    Complexity
                  </span>
                  <ScoreThermometer
                    value={configurator.complexityScore}
                    variant="light"
                  />
                </div>

                <div className="flex items-center justify-between gap-4 rounded-2xl border border-slate-100 bg-white/75 p-4 shadow-sm">
                  <span className="font-semibold text-slate-600">
                    Overall Configurator Score
                  </span>
                  <ScoreThermometer
                    value={configurator.intelligenceScore}
                    variant="light"
                  />
                </div>
              </div>
            </div>
          </AnimatedSection>

          <AnimatedSection delay={0.08}>
            <div className="rounded-3xl border border-slate-200 bg-white/80 p-6 shadow-xl backdrop-blur">
              <div className="flex items-center justify-between gap-4">
                <h2 className="text-2xl font-black text-slate-950">
                  Data status
                </h2>
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-blue-100 bg-blue-50 text-blue-600">
                  <Database size={21} />
                </div>
              </div>

              <div className="mt-5 space-y-3 text-sm text-slate-600">
                <p>
                  <span className="text-slate-400">Record ID:</span>{" "}
                  <span className="font-bold text-slate-950">
                    {configurator.id}
                  </span>
                </p>
                <p>
                  <span className="text-slate-400">Created:</span>{" "}
                  <span className="font-bold text-slate-950">
                    {configurator.createdAt.toLocaleDateString()}
                  </span>
                </p>
                <p>
                  <span className="text-slate-400">Updated:</span>{" "}
                  <span className="font-bold text-slate-950">
                    {configurator.updatedAt.toLocaleDateString()}
                  </span>
                </p>
              </div>
            </div>
          </AnimatedSection>
        </aside>
      </section>

      {similarConfigurators.length > 0 && (
        <section className="relative z-10 mx-auto max-w-6xl px-6 pb-12">
          <AnimatedSection delay={0.1}>
            <div className="rounded-3xl border border-slate-200 bg-white/80 p-6 shadow-xl backdrop-blur">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-black uppercase tracking-[0.3em] text-blue-600">
                    Similar configurators
                  </p>
                  <h2 className="mt-3 text-2xl font-black text-slate-950">
                    More from {label(configurator.industry)}
                  </h2>
                </div>

                <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-blue-100 bg-blue-50 text-blue-600">
                  <Radar size={21} />
                </div>
              </div>

              <div className="mt-6 grid gap-4 md:grid-cols-3">
                {similarConfigurators.map((item) => (
                  <Link
                    key={item.id}
                    href={`/configurators/${item.slug}`}
                    className="group rounded-2xl border border-slate-100 bg-white/75 p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-blue-200 hover:bg-blue-50/80"
                  >
                    <p className="text-sm text-slate-500">
                      {label(item.country, "Unknown country")}
                    </p>

                    <h3 className="mt-2 font-black text-slate-950">
                      {item.company}
                    </h3>

                    <p className="mt-1 text-sm text-slate-500">
                      {label(item.product, "No product specified")}
                    </p>

                    <div className="mt-4 flex items-center justify-between gap-3">
                      <span className="rounded-full bg-blue-100 px-3 py-1 text-sm font-black text-blue-700">
                        {scoreLabel(item.intelligenceScore)}
                      </span>

                      <ArrowUpRight
                        size={17}
                        className="text-slate-400 transition group-hover:text-blue-600"
                      />
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          </AnimatedSection>
        </section>
      )}
    </main>
  );
}