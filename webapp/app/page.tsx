import Link from "next/link";
import AnimatedSection from "@/components/AnimatedSection";
import HeroBackground from "@/components/HeroBackground";
import HomeLeaderboard from "@/components/HomeLeaderboard";
import IndustryTopSections from "@/components/IndustryTopSections";
import PremiumStatCard from "@/components/PremiumStatCard";
import BackgroundPaths from "@/components/modern-background-paths";
import { prisma } from "@/lib/prisma";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function HomePage() {
  const [totalCount, activeCount, industryRows, countryRows, rankedConfigurators] =
    await Promise.all([
      prisma.configurator.count(),
      prisma.configurator.count({
        where: {
          isActive: true,
        },
      }),
      prisma.configurator.findMany({
        select: {
          industry: true,
        },
      }),
      prisma.configurator.findMany({
        select: {
          country: true,
        },
      }),
      prisma.configurator.findMany({
        where: {
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
        select: {
          id: true,
          slug: true,
          company: true,
          industry: true,
          product: true,
          country: true,
          visualizationType: true,
          intelligenceScore: true,
        },
      }),
    ]);

  const industriesCount = new Set(
    industryRows.map((row) => row.industry).filter(Boolean)
  ).size;

  const countriesCount = new Set(
    countryRows.map((row) => row.country).filter(Boolean)
  ).size;

  const overallTop = rankedConfigurators.slice(0, 20);

  const groupedByIndustry = new Map<
    string,
    {
      id: number;
      slug: string;
      company: string;
      product: string | null;
      country: string | null;
      intelligenceScore: number | null;
    }[]
  >();

  for (const configurator of rankedConfigurators) {
    const industry = configurator.industry?.trim();

    if (!industry) continue;

    if (!groupedByIndustry.has(industry)) {
      groupedByIndustry.set(industry, []);
    }

    const currentItems = groupedByIndustry.get(industry)!;

    if (currentItems.length < 3) {
      currentItems.push({
        id: configurator.id,
        slug: configurator.slug,
        company: configurator.company,
        product: configurator.product,
        country: configurator.country,
        intelligenceScore: configurator.intelligenceScore,
      });
    }
  }

  const industrySections = Array.from(groupedByIndustry.entries())
    .map(([industry, items]) => ({
      industry,
      items,
    }))
    .sort((a, b) => a.industry.localeCompare(b.industry));

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <section className="relative overflow-hidden border-b border-slate-200 bg-slate-50">
        <HeroBackground variant="light" />

        <div className="relative mx-auto max-w-7xl px-6 py-24 md:py-32">
          <div className="max-w-5xl">
            <p className="mb-5 text-sm font-black uppercase tracking-[0.35em] text-blue-600">
              Product configurator intelligence platform
            </p>

            <h1 className="text-5xl font-black tracking-tight text-slate-950 md:text-7xl">
              Discover, analyze and compare{" "}
              <span className="bg-gradient-to-r from-blue-600 via-cyan-500 to-fuchsia-500 bg-clip-text text-transparent">
                product configurators
              </span>{" "}
              worldwide.
            </h1>

            <p className="mt-7 max-w-3xl text-xl leading-8 text-slate-600">
              A data-driven intelligence hub for exploring product configurators
              by status, industry, country, visualization type, mobile
              optimization, compatibility rules and complexity.
            </p>

            <div className="mt-10 flex flex-wrap gap-4">
              <Link
                href="/configurators"
                className="group rounded-2xl bg-blue-600 px-6 py-4 font-semibold text-white shadow-lg shadow-blue-500/25 transition hover:-translate-y-0.5 hover:bg-blue-500"
              >
                Explore database
                <span className="ml-2 inline-block transition group-hover:translate-x-1">
                  →
                </span>
              </Link>

              <Link
                href="/configurators?active=active&sort=score"
                className="rounded-2xl border border-slate-200 bg-white/75 px-6 py-4 font-semibold text-slate-900 shadow-sm backdrop-blur transition hover:-translate-y-0.5 hover:bg-white"
              >
                View best active configurators
              </Link>
            </div>
          </div>

          <div className="mt-16 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <PremiumStatCard
              label="Total records"
              value={totalCount}
              iconName="database"
              delay={0}
              variant="light"
            />

            <PremiumStatCard
              label="Active configurators"
              value={activeCount}
              iconName="activity"
              delay={0.08}
              variant="light"
            />

            <PremiumStatCard
              label="Industries"
              value={industriesCount}
              iconName="layers"
              delay={0.16}
              variant="light"
            />

            <PremiumStatCard
              label="Countries"
              value={countriesCount}
              iconName="globe"
              delay={0.24}
              variant="light"
            />
          </div>
        </div>
      </section>

      <section className="relative overflow-hidden bg-gradient-to-b from-white via-blue-50/70 to-cyan-50">
        <BackgroundPaths variant="light" />

        <div className="absolute inset-0 bg-[radial-gradient(circle_at_12%_10%,rgba(59,130,246,0.14),transparent_26%),radial-gradient(circle_at_86%_18%,rgba(236,72,153,0.11),transparent_24%),radial-gradient(circle_at_50%_82%,rgba(34,211,238,0.15),transparent_30%)]" />

        <div className="relative">
          <AnimatedSection className="mx-auto max-w-7xl px-6 py-16">
            <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
              <div>
                <p className="text-sm font-black uppercase tracking-[0.3em] text-blue-600">
                  Database highlights
                </p>
                <h2 className="mt-3 text-3xl font-black tracking-tight text-slate-950 md:text-5xl">
                  Top configurators by Overall Configurator Score
                </h2>
                <p className="mt-4 max-w-3xl text-slate-600">
                  The first three active configurators are shown on the podium.
                  The remaining ranked configurators can be expanded below.
                </p>
              </div>

              <Link
                href="/configurators?active=active&sort=score"
                className="w-fit rounded-2xl border border-slate-200 bg-white/75 px-5 py-3 font-semibold text-slate-900 shadow-sm backdrop-blur transition hover:-translate-y-0.5 hover:bg-white"
              >
                Explore full ranking →
              </Link>
            </div>

            <div className="mt-10">
              <HomeLeaderboard items={overallTop} />
            </div>
          </AnimatedSection>

          <AnimatedSection delay={0.08} className="pb-20">
            <IndustryTopSections sections={industrySections} />
          </AnimatedSection>
        </div>
      </section>
    </main>
  );
}