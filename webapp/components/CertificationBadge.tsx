import { Award, Building2, Leaf, PackageCheck } from "lucide-react";
import { getCertificationBadgeStyle } from "@/lib/certificationBadges";
import type { SiteCertificationRecord } from "@/lib/certificationData";

type CertificationBadgeProps = {
  certification: SiteCertificationRecord;
};

function claimLabel(siteClaimType: string, evidenceLevel: string) {
  if (siteClaimType === "product_certified") {
    return "Product-level evidence";
  }

  if (siteClaimType === "company_or_brand_certified") {
    return "Company/brand-level evidence";
  }

  if (evidenceLevel) {
    return `${evidenceLevel} evidence`;
  }

  return "Certification evidence";
}

function ClaimIcon({ siteClaimType }: { siteClaimType: string }) {
  if (siteClaimType === "product_certified") {
    return <PackageCheck className="h-4 w-4" />;
  }

  if (siteClaimType === "company_or_brand_certified") {
    return <Building2 className="h-4 w-4" />;
  }

  return <Leaf className="h-4 w-4" />;
}

export default function CertificationBadge({
  certification,
}: CertificationBadgeProps) {
  const style = getCertificationBadgeStyle(certification.certification);
  const supportingName =
    certification.matchedProduct ||
    certification.matchedEntity ||
    certification.matchedCompany ||
    certification.matchedBrand;

  return (
    <article className="group relative overflow-hidden rounded-3xl border border-white/70 bg-white/85 p-4 text-slate-950 shadow-xl shadow-slate-900/10 ring-1 ring-slate-900/5 backdrop-blur transition duration-300 hover:-translate-y-1 hover:shadow-2xl">
      <div
        className={`absolute inset-x-0 top-0 h-1.5 bg-gradient-to-r ${style.gradientClassName}`}
      />

      <div className="flex items-start gap-4">
        <div
          className={`flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br ${style.gradientClassName} text-3xl shadow-lg ring-4 ${style.ringClassName}`}
        >
          {style.imagePath ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={style.imagePath}
              alt={style.label}
              className="h-11 w-11 object-contain"
            />
          ) : (
            <span aria-hidden="true">{style.emoji}</span>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-black tracking-tight text-slate-950">
              {certification.certification}
            </h3>

            {certification.confidence && (
              <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-bold text-emerald-800 ring-1 ring-emerald-200">
                {certification.confidence}
              </span>
            )}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm font-semibold text-slate-700">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 ring-1 ring-slate-200">
              <ClaimIcon siteClaimType={certification.siteClaimType} />
              {claimLabel(
                certification.siteClaimType,
                certification.evidenceLevel
              )}
            </span>

            {certification.score > 0 && (
              <span className="rounded-full bg-blue-50 px-3 py-1 text-blue-800 ring-1 ring-blue-100">
                Score {Math.round(certification.score)}
              </span>
            )}
          </div>

          {supportingName && (
            <p className="mt-3 text-sm leading-6 text-slate-700">
              Matched evidence:{" "}
              <span className="font-bold text-slate-950">{supportingName}</span>
            </p>
          )}

          {certification.certificateIdentifier && (
            <p className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Certificate ID: {certification.certificateIdentifier}
            </p>
          )}

          {certification.sourceUrl && (
            <a
              href={certification.sourceUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-3 inline-flex items-center gap-2 text-sm font-bold text-blue-700 transition hover:text-blue-900"
            >
              <Award className="h-4 w-4" />
              View source
            </a>
          )}
        </div>
      </div>
    </article>
  );
}