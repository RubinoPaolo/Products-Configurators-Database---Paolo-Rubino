import CertificationBadge from "@/components/CertificationBadge";
import { getConfiguratorCertifications } from "@/lib/certificationData";

type ConfiguratorCertificationSectionProps = {
  company: string | null | undefined;
  product: string | null | undefined;
};

export default function ConfiguratorCertificationSection({
  company,
  product,
}: ConfiguratorCertificationSectionProps) {
  const certificationData = getConfiguratorCertifications(company, product);
  const directCertifications = certificationData.directCertifications;

  if (directCertifications.length === 0) {
    return (
      <section className="mt-6 rounded-3xl border border-white/70 bg-white/80 p-6 text-slate-950 shadow-xl shadow-slate-900/10 backdrop-blur">
        <div className="flex flex-col gap-2">
          <p className="text-sm font-black uppercase tracking-[0.25em] text-slate-500">
            Sustainability certifications
          </p>

          <h2 className="text-2xl font-black tracking-tight text-slate-950">
            No direct certifications found
          </h2>

          <p className="max-w-2xl text-sm leading-6 text-slate-600">
            No product-level, company-level, or brand-level certification match
            has been confirmed for this configurator in the current local
            registry.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="mt-6 rounded-3xl border border-white/70 bg-white/80 p-6 text-slate-950 shadow-xl shadow-slate-900/10 backdrop-blur">
      <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-black uppercase tracking-[0.25em] text-emerald-700">
            Sustainability certifications
          </p>

          <h2 className="mt-1 text-2xl font-black tracking-tight text-slate-950">
            Certifications linked to this configurator
          </h2>

          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
            These badges are based on direct product, company, or brand-level
            matches from the local certification registry.
          </p>
        </div>

        <div className="w-fit rounded-2xl bg-emerald-100 px-4 py-2 text-sm font-black text-emerald-800 ring-1 ring-emerald-200">
          {directCertifications.length} found
        </div>
      </div>

      <div className="mt-6 grid gap-4">
        {directCertifications.map((certification) => (
          <CertificationBadge
            key={`${certification.certification}-${certification.matchedEntity}-${certification.matchedProduct}`}
            certification={certification}
          />
        ))}
      </div>
    </section>
  );
}