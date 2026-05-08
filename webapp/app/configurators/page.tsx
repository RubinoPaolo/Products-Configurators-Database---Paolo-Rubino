import Image from "next/image";
import Link from "next/link";
import type { Prisma } from "@prisma/client";
import {
  ArrowUpRight,
  BadgeCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import HeroBackground from "@/components/HeroBackground";
import PremiumStatCard from "@/components/PremiumStatCard";
import FilterPanel from "@/components/FilterPanel";
import {
  getCountryCode,
  getIndustrySticker,
  getProductSticker,
  getVisualizationSticker,
} from "@/lib/stickers";
import { prisma } from "@/lib/prisma";
import { getAllCertificationOptions } from "@/lib/certificationBadges";
import {
  getConfiguratorKeysForCertifications,
  makeConfiguratorLookupKey,
} from "@/lib/certificationData";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type SearchParams = {
  q?: string | string[];
  industry?: string | string[];
  country?: string | string[];
  active?: string | string[];
  visualization?: string | string[];
  sort?: string | string[];
  cert?: string | string[];
};

type PageProps = {
  searchParams?: Promise<SearchParams>;
};

function getParam(value: string | string[] | undefined) {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

function getParamArray(value: string | string[] | undefined): string[] {
  if (!value) return [];
  if (Array.isArray(value)) return value.filter(Boolean);
  return value.trim() ? [value.trim()] : [];
}

function label(value: string | null | undefined, fallback = "Not available") {
  return value && value.trim().length > 0 ? value : fallback;
}

function scoreLabel(score: number | null) {
  if (score === null) return "N/A";
  return score.toFixed(2);
}

function scorePercent(score: number | null) {
  if (score === null) return 0;
  return Math.max(0, Math.min(100, (score / 5) * 100));
}

function scoreTone(score: number | null) {
  if (score === null) return "from-slate-400 to-slate-300";
  if (score >= 4) return "from-emerald-500 to-cyan-400";
  if (score >= 3) return "from-yellow-400 to-orange-400";
  return "from-red-500 to-orange-500";
}

function StatusBadge({ value }: { value: boolean | null }) {
  if (value === true) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1 text-sm font-black text-emerald-700">
        <BadgeCheck size={14} />
        Active
      </span>
    );
  }

  if (value === false) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-red-100 px-3 py-1 text-sm font-black text-red-700">
        <XCircle size={14} />
        Inactive
      </span>
    );
  }

  return (
    <span className="inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-sm font-black text-slate-600">
      Unknown
    </span>
  );
}

function MiniFlag({ country }: { country: string | null }) {
  const code = getCountryCode(country);

  if (!code) {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-xl border border-slate-200 bg-white text-sm">
        🌍
      </span>
    );
  }

  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-xl border border-slate-200 bg-white p-1.5">
      <Image
        src={`https://flagcdn.com/w40/${code}.png`}
        alt={`${country ?? "Country"} flag`}
        width={24}
        height={18}
        className="rounded-sm object-cover"
      />
    </span>
  );
}

function ScoreMetric({
  label,
  value,
}: {
  label: string;
  value: number | null;
}) {
  return (
    <div className="rounded-2xl border border-slate-100 bg-white/80 p-3 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-slate-500">{label}</p>
        <p className="text-sm font-black text-slate-950">
          {value === null ? "N/A" : `${value}/5`}
        </p>
      </div>

      <div className="mt-2 h-1.5 rounded-full bg-slate-200">
        <div
          className={`h-1.5 rounded-full bg-gradient-to-r ${scoreTone(value)}`}
          style={{ width: `${scorePercent(value)}%` }}
        />
      </div>
    </div>
  );
}

function OverallScore({ value }: { value: number | null }) {
  return (
    <div className="rounded-2xl border border-blue-100 bg-blue-50/80 p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.22em] text-blue-600">
            Overall score
          </p>
          <p className="mt-1 text-2xl font-black text-slate-950">
            {scoreLabel(value)}
          </p>
        </div>

        <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-blue-100 bg-white text-blue-600 shadow-sm">
          <Sparkles size={22} />
        </div>
      </div>

      <div className="mt-4 h-2 rounded-full bg-slate-200">
        <div
          className={`h-2 rounded-full bg-gradient-to-r ${scoreTone(value)}`}
          style={{ width: `${scorePercent(value)}%` }}
        />
      </div>
    </div>
  );
}

export default async function ConfiguratorsPage({ searchParams }: PageProps) {
  const params = await searchParams;

  const q = getParam(params?.q).trim();
  const active = getParam(params?.active).trim();
  const sort = getParam(params?.sort).trim();

  const selectedIndustries = getParamArray(params?.industry);
  const selectedCountries = getParamArray(params?.country);
  const selectedVisualizations = getParamArray(params?.visualization);
  const selectedCerts = getParamArray(params?.cert);

  const where: Prisma.ConfiguratorWhereInput = {};

  if (q) {
    where.OR = [
      { company: { contains: q } },
      { product: { contains: q } },
      { industry: { contains: q } },
      { country: { contains: q } },
    ];
  }

  if (selectedIndustries.length === 1) {
    where.industry = selectedIndustries[0];
  } else if (selectedIndustries.length > 1) {
    where.industry = { in: selectedIndustries };
  }

  if (selectedCountries.length === 1) {
    where.country = selectedCountries[0];
  } else if (selectedCountries.length > 1) {
    where.country = { in: selectedCountries };
  }

  if (active === "active") where.isActive = true;
  if (active === "inactive") where.isActive = false;

  if (selectedVisualizations.length === 1) {
    where.visualizationType = selectedVisualizations[0];
  } else if (selectedVisualizations.length > 1) {
    where.visualizationType = { in: selectedVisualizations };
  }

  let orderBy: Prisma.ConfiguratorOrderByWithRelationInput[] = [
    { company: "asc" },
  ];

  if (sort === "score") orderBy = [{ intelligenceScore: "desc" }, { company: "asc" }];
  if (sort === "mobile") orderBy = [{ mobileScore: "desc" }, { company: "asc" }];
  if (sort === "complexity") orderBy = [{ complexityScore: "desc" }, { company: "asc" }];
  if (sort === "compatibility") orderBy = [{ compatibilityScore: "desc" }, { company: "asc" }];

  // Certification filter: build matching key set server-side
  const certKeys = getConfiguratorKeysForCertifications(selectedCerts);

  const [
    totalCount,
    activeCount,
    inactiveCount,
    filterRows,
  ] = await Promise.all([
    prisma.configurator.count(),
    prisma.configurator.count({ where: { isActive: true } }),
    prisma.configurator.count({ where: { isActive: false } }),
    prisma.configurator.findMany({
      select: { industry: true, country: true, visualizationType: true },
    }),
  ]);

  // When cert filter is active, query all matches then filter in memory
  let configurators;
  let filteredCount: number;

  if (certKeys !== null) {
    const allMatching = await prisma.configurator.findMany({ where, orderBy });
    const certFiltered = allMatching.filter((c) =>
      certKeys.has(makeConfiguratorLookupKey(c.company, c.product))
    );
    filteredCount = certFiltered.length;
    configurators = certFiltered.slice(0, 120);
  } else {
    const [rows, count] = await Promise.all([
      prisma.configurator.findMany({ where, orderBy, take: 120 }),
      prisma.configurator.count({ where }),
    ]);
    configurators = rows;
    filteredCount = count;
  }

  const industries = Array.from(
    new Set(
      filterRows
        .map((row) => row.industry)
        .filter((value): value is string => Boolean(value))
    )
  ).sort();

  const countries = Array.from(
    new Set(
      filterRows
        .map((row) => row.country)
        .filter((value): value is string => Boolean(value))
    )
  ).sort();

  const visualizations = Array.from(
    new Set(
      filterRows
        .map((row) => row.visualizationType)
        .filter((value): value is string => Boolean(value))
    )
  ).sort();

  const certificationOptions = getAllCertificationOptions();

  const hasFilters = Boolean(
    q ||
    selectedIndustries.length > 0 ||
    selectedCountries.length > 0 ||
    active ||
    selectedVisualizations.length > 0 ||
    sort ||
    selectedCerts.length > 0
  );

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <section className="relative overflow-hidden border-b border-slate-200 bg-slate-50">
        <HeroBackground variant="light" />

        <div className="relative mx-auto max-w-7xl px-6 py-16 md:py-20">
          <Link
            href="/"
            className="inline-flex items-center text-sm font-black text-blue-600 transition hover:text-blue-500"
          >
            ← Back to homepage
          </Link>

          <div className="mt-8 grid gap-10 lg:grid-cols-[1fr_0.72fr] lg:items-end">
            <div>
              <p className="text-sm font-black uppercase tracking-[0.35em] text-blue-600">
                Configurator explorer
              </p>

              <h1 className="mt-4 max-w-4xl text-5xl font-black tracking-tight text-slate-950 md:text-7xl">
                Search the global{" "}
                <span className="bg-gradient-to-r from-blue-600 via-cyan-500 to-fuchsia-500 bg-clip-text text-transparent">
                  configurator database.
                </span>
              </h1>

              <p className="mt-6 max-w-3xl text-lg leading-8 text-slate-600">
                Filter product configurators by industry, country, status,
                visualization type, certifications and benchmark scores.
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <PremiumStatCard label="Total records" value={totalCount} iconName="database" variant="light" />
              <PremiumStatCard label="Filtered results" value={filteredCount} iconName="sparkles" variant="light" />
              <PremiumStatCard label="Active" value={activeCount} iconName="activity" variant="light" />
              <PremiumStatCard label="Inactive" value={inactiveCount} iconName="database" variant="light" />
            </div>
          </div>
        </div>
      </section>

      <section className="relative overflow-hidden bg-gradient-to-b from-white via-blue-50/70 to-cyan-50 px-6 py-8">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_12%_10%,rgba(59,130,246,0.13),transparent_26%),radial-gradient(circle_at_86%_18%,rgba(236,72,153,0.09),transparent_24%),radial-gradient(circle_at_50%_82%,rgba(34,211,238,0.13),transparent_30%)]" />

        <div className="relative mx-auto max-w-7xl">
          <FilterPanel
            industries={industries}
            countries={countries}
            visualizations={visualizations}
            certificationOptions={certificationOptions}
            initQ={q}
            initIndustries={selectedIndustries}
            initCountries={selectedCountries}
            initActive={active}
            initVisualizations={selectedVisualizations}
            initSort={sort}
            initCertifications={selectedCerts}
          />

          <div className="mt-8 flex flex-wrap items-center justify-between gap-4">
            <p className="text-sm text-slate-600">
              Showing <span className="font-black text-slate-950">{configurators.length}</span>{" "}
              of <span className="font-black text-slate-950">{filteredCount}</span>{" "}
              matching records
            </p>

            {hasFilters && (
              <div className="flex flex-wrap gap-2">
                {q && (
                  <span className="rounded-full border border-slate-200 bg-white/80 px-3 py-1 text-sm text-slate-600">
                    Search: {q}
                  </span>
                )}
                {selectedIndustries.map((ind) => (
                  <span key={ind} className="rounded-full border border-slate-200 bg-white/80 px-3 py-1 text-sm text-slate-600">
                    Industry: {ind}
                  </span>
                ))}
                {selectedCountries.map((c) => (
                  <span key={c} className="rounded-full border border-slate-200 bg-white/80 px-3 py-1 text-sm text-slate-600">
                    Country: {c}
                  </span>
                ))}
                {selectedCerts.map((c) => (
                  <span key={c} className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-sm font-semibold text-blue-700">
                    ✓ {c}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="mt-8 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
            {configurators.map((configurator) => {
              const mainUrl =
                configurator.alternativeUrl || configurator.configuratorUrl || null;

              return (
                <article
                  key={configurator.id}
                  className="group relative overflow-hidden rounded-[2rem] border border-slate-200 bg-white/80 p-6 shadow-xl backdrop-blur transition duration-300 hover:-translate-y-1 hover:border-blue-200 hover:bg-white"
                >
                  <div className="absolute -right-12 -top-12 h-32 w-32 rounded-full bg-blue-300/25 blur-3xl opacity-0 transition duration-500 group-hover:opacity-100" />
                  <div className="absolute -bottom-12 -left-12 h-28 w-28 rounded-full bg-cyan-300/20 blur-3xl opacity-0 transition duration-500 group-hover:opacity-100" />

                  <div className="relative flex items-start justify-between gap-4">
                    <div className="flex gap-3">
                      <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-slate-200 bg-white text-2xl shadow-sm">
                        {getIndustrySticker(configurator.industry)}
                      </div>

                      <div>
                        <p className="text-sm text-slate-500">
                          {label(configurator.industry)}
                        </p>
                        <h2 className="mt-1 text-2xl font-black tracking-tight text-slate-950">
                          {configurator.company}
                        </h2>
                      </div>
                    </div>

                    <StatusBadge value={configurator.isActive} />
                  </div>

                  <div className="relative mt-5 flex items-start gap-3 rounded-2xl border border-slate-100 bg-white/75 p-4 shadow-sm">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-xl">
                      {getProductSticker(configurator.product)}
                    </div>

                    <div>
                      <p className="text-xs font-black uppercase tracking-[0.22em] text-slate-400">
                        Product
                      </p>
                      <p className="mt-1 font-bold text-slate-950">
                        {label(configurator.product, "No product specified")}
                      </p>
                    </div>
                  </div>

                  <div className="relative mt-4 flex flex-wrap gap-2">
                    <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/75 px-3 py-1.5 text-sm text-slate-600">
                      <MiniFlag country={configurator.country} />
                      {label(configurator.country, "Unknown country")}
                    </span>

                    <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/75 px-3 py-1.5 text-sm text-slate-600">
                      <span>{getVisualizationSticker(configurator.visualizationType)}</span>
                      {label(configurator.visualizationType, "Unknown type")}
                    </span>
                  </div>

                  <div className="relative mt-5">
                    <OverallScore value={configurator.intelligenceScore} />
                  </div>

                  <div className="relative mt-4 grid grid-cols-3 gap-3">
                    <ScoreMetric label="Mobile" value={configurator.mobileScore} />
                    <ScoreMetric label="Rules" value={configurator.compatibilityScore} />
                    <ScoreMetric label="Complexity" value={configurator.complexityScore} />
                  </div>

                  <div className="relative mt-6 flex gap-3">
                    <Link
                      href={`/configurators/${configurator.slug}`}
                      className="flex flex-1 items-center justify-center gap-2 rounded-2xl bg-blue-600 px-4 py-3 text-center font-bold text-white shadow-lg shadow-blue-500/20 transition hover:bg-blue-500"
                    >
                      View profile
                      <ArrowUpRight size={16} />
                    </Link>

                    {mainUrl && (
                      <a
                        href={mainUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-2xl border border-slate-200 bg-white px-4 py-3 font-bold text-slate-900 shadow-sm transition hover:bg-blue-50"
                      >
                        Open
                      </a>
                    )}
                  </div>
                </article>
              );
            })}
          </div>

          {configurators.length === 0 && (
            <div className="mt-8 rounded-[2rem] border border-slate-200 bg-white/80 p-10 text-center shadow-xl backdrop-blur">
              <h2 className="text-2xl font-black text-slate-950">
                No configurators found
              </h2>
              <p className="mt-3 text-slate-600">
                Try changing your filters or resetting the search.
              </p>

              <Link
                href="/configurators"
                className="mt-6 inline-flex rounded-2xl bg-blue-600 px-5 py-3 font-bold text-white transition hover:bg-blue-500"
              >
                Reset filters
              </Link>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
