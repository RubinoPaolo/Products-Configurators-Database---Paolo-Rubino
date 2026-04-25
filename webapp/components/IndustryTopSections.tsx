import Link from "next/link";
import { getIndustrySticker } from "@/lib/stickers";

type IndustryConfigurator = {
  id: number;
  slug: string;
  company: string;
  product: string | null;
  country: string | null;
  intelligenceScore: number | null;
};

type IndustrySection = {
  industry: string;
  items: IndustryConfigurator[];
};

type IndustryTopSectionsProps = {
  sections: IndustrySection[];
};

function scoreLabel(value: number | null) {
  return typeof value === "number" ? value.toFixed(2) : "N/A";
}

export default function IndustryTopSections({
  sections,
}: IndustryTopSectionsProps) {
  return (
    <section className="mx-auto max-w-7xl px-6 pb-16">
      <div>
        <p className="text-sm font-black uppercase tracking-[0.3em] text-blue-600">
          Industry rankings
        </p>
        <h2 className="mt-3 text-3xl font-black tracking-tight text-slate-950 md:text-4xl">
          Top configurators by Overall Configurator Score in each industry
        </h2>
        <p className="mt-4 max-w-3xl text-slate-600">
          For each industry category, here are the highest-ranking
          configurators based on the Overall Configurator Score.
        </p>
      </div>

      <div className="mt-8 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        {sections.map((section) => (
          <div
            key={section.industry}
            className="group relative overflow-hidden rounded-3xl border border-slate-200 bg-white/75 p-6 shadow-xl backdrop-blur transition hover:-translate-y-1 hover:bg-white"
          >
            <div className="absolute -right-14 -top-14 h-40 w-40 rounded-full bg-blue-300/20 blur-3xl opacity-0 transition group-hover:opacity-100" />
            <div className="absolute -bottom-14 -left-14 h-36 w-36 rounded-full bg-cyan-300/20 blur-3xl opacity-0 transition group-hover:opacity-100" />

            <div className="relative flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-slate-200 bg-white text-2xl shadow-sm">
                  {getIndustrySticker(section.industry)}
                </div>

                <div>
                  <h3 className="text-xl font-black text-slate-950">
                    {section.industry}
                  </h3>
                  <p className="mt-1 text-sm text-slate-500">
                    Top configurators in this industry
                  </p>
                </div>
              </div>

              <span className="rounded-full bg-blue-100 px-3 py-1 text-xs font-black text-blue-700">
                Top {section.items.length}
              </span>
            </div>

            <div className="relative mt-5 space-y-3">
              {section.items.map((item, index) => (
                <Link
                  key={item.id}
                  href={`/configurators/${item.slug}`}
                  className="flex items-center justify-between gap-4 rounded-2xl border border-slate-100 bg-white/70 p-4 shadow-sm transition hover:border-blue-200 hover:bg-blue-50/70"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-100 font-black text-blue-700">
                      {index + 1}
                    </div>

                    <div>
                      <p className="font-black text-slate-950">
                        {item.company}
                      </p>
                      <p className="text-sm text-slate-500">
                        {item.product || "No product specified"}
                      </p>
                    </div>
                  </div>

                  <div className="text-right">
                    <p className="font-black text-blue-600">
                      {scoreLabel(item.intelligenceScore)}
                    </p>
                    <p className="text-xs text-slate-400">
                      {item.country || "Unknown country"}
                    </p>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}