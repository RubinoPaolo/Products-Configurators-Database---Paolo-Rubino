export type CertificationBadgeStyle = {
    label: string;
    shortLabel: string;
    slug: string;
    emoji: string;
    imagePath?: string;
    gradientClassName: string;
    ringClassName: string;
    textClassName: string;
  };
  
  function normalizeCertificationName(value: string) {
    return value
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/&/g, " and ")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }
  
  const BADGE_STYLES: CertificationBadgeStyle[] = [
    {
      label: "B Corp",
      shortLabel: "B Corp",
      slug: "b-corp",
      emoji: "🌍",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\b_corp\italian-b-corp-logo-black-rgb-removebg-preview.png",
      gradientClassName: "from-sky-500 via-blue-500 to-indigo-600",
      ringClassName: "ring-blue-300/50",
      textClassName: "text-blue-950",
    },
    {
      label: "PETA-Approved Vegan",
      shortLabel: "PETA",
      slug: "peta-approved-vegan",
      emoji: "🌱",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\peta_approved_vegan\PETA_Logo_Black.png",
      gradientClassName: "from-emerald-400 via-green-500 to-lime-500",
      ringClassName: "ring-emerald-300/60",
      textClassName: "text-emerald-950",
    },
    {
      label: "Blue Angel",
      shortLabel: "Blue Angel",
      slug: "blue-angel",
      emoji: "🔵",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\blue_angel\BLUE_ANGEL_Logo.png",
      gradientClassName: "from-cyan-400 via-sky-500 to-blue-600",
      ringClassName: "ring-sky-300/60",
      textClassName: "text-sky-950",
    },
    {
      label: "Bluesign",
      shortLabel: "Bluesign",
      slug: "bluesign",
      emoji: "💧",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\bluesign\bluesign-removebg-preview.png",
      gradientClassName: "from-blue-400 via-cyan-500 to-teal-500",
      ringClassName: "ring-cyan-300/60",
      textClassName: "text-cyan-950",
    },
    {
      label: "Cradle to Cradle Certified",
      shortLabel: "C2C",
      slug: "cradle-to-cradle",
      emoji: "♻️",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\cradle_to_cradle\general-requirements-on-cradle-to-cradle-dansk-wilton-removebg-preview.png",
      gradientClassName: "from-lime-400 via-green-500 to-emerald-600",
      ringClassName: "ring-lime-300/60",
      textClassName: "text-lime-950",
    },
    {
      label: "EU Ecolabel",
      shortLabel: "EU Ecolabel",
      slug: "eu-ecolabel",
      emoji: "🌼",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\eu_ecolabel\eu_certif-removebg-preview.png",
      gradientClassName: "from-yellow-300 via-lime-400 to-green-500",
      ringClassName: "ring-yellow-200/70",
      textClassName: "text-lime-950",
    },
    {
      label: "EWG Verified",
      shortLabel: "EWG",
      slug: "ewg-verified",
      emoji: "✅",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\ewg_verified\ewg_verified_mark_720-removebg-preview.png",
      gradientClassName: "from-green-300 via-emerald-500 to-teal-600",
      ringClassName: "ring-green-300/60",
      textClassName: "text-emerald-950",
    },
    {
      label: "Fair for Life",
      shortLabel: "Fair for Life",
      slug: "fair-for-life",
      emoji: "🤝",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\fair_for_life\ffllogo-news-26-02-2016-and-08-02-2017-removebg-preview.png",
      gradientClassName: "from-orange-300 via-amber-400 to-yellow-500",
      ringClassName: "ring-amber-200/70",
      textClassName: "text-amber-950",
    },
    {
      label: "Global Organic Textile Standard",
      shortLabel: "GOTS",
      slug: "gots",
      emoji: "🧵",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\gots\gots-logo-2018-removebg-preview.png",
      gradientClassName: "from-emerald-300 via-teal-400 to-cyan-500",
      ringClassName: "ring-teal-200/70",
      textClassName: "text-teal-950",
    },
    {
      label: "Global Recycled Standard",
      shortLabel: "GRS",
      slug: "grs",
      emoji: "♻️",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\GRS\GRS v3 Logo Final_0.png",
      gradientClassName: "from-green-400 via-lime-500 to-emerald-600",
      ringClassName: "ring-green-300/60",
      textClassName: "text-green-950",
    },
    {
      label: "OEKO-TEX MADE IN GREEN",
      shortLabel: "OEKO-TEX",
      slug: "oeko-tex-made-in-green",
      emoji: "🟢",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\oeko_tex_made_in_green\Logo-OEKO-TEX-MADE-IN-GREEN-gw-cmyk-ws-scaled-removebg-preview.png",
      gradientClassName: "from-lime-300 via-emerald-400 to-green-600",
      ringClassName: "ring-lime-200/70",
      textClassName: "text-green-950",
    },
    {
      label: "FSC",
      shortLabel: "FSC",
      slug: "fsc",
      emoji: "🌳",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\fsc\FSC_Logo_-__RGB-removebg-preview.png",
      gradientClassName: "from-green-500 via-emerald-600 to-teal-700",
      ringClassName: "ring-emerald-300/60",
      textClassName: "text-green-950",
    },
    {
      label: "GreenCircle Certified",
      shortLabel: "GreenCircle",
      slug: "green-circle",
      emoji: "🟩",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\green_circle\GCC+Blank+No+Back-removebg-preview.png",
      gradientClassName: "from-emerald-400 via-green-500 to-cyan-500",
      ringClassName: "ring-emerald-300/60",
      textClassName: "text-emerald-950",
    },
    {
      label: "Environmental Product Declaration",
      shortLabel: "EPD",
      slug: "epd",
      emoji: "📄",
      imagePath: "C:\Users\Paolo Rubino\OneDrive - Poste Italiane S.p.A\Desktop\configurator-intelligence-hub\data\certifications\epd\epd certification.png",
      gradientClassName: "from-slate-300 via-blue-300 to-cyan-400",
      ringClassName: "ring-blue-200/70",
      textClassName: "text-slate-950",
    },
  ];
  
  const DEFAULT_BADGE_STYLE: CertificationBadgeStyle = {
    label: "Certification",
    shortLabel: "Certified",
    slug: "certification",
    emoji: "🏅",
    imagePath: "",
    gradientClassName: "from-violet-400 via-fuchsia-500 to-pink-500",
    ringClassName: "ring-fuchsia-300/60",
    textClassName: "text-fuchsia-950",
  };
  
  export function getCertificationBadgeStyle(
    certification: string
  ): CertificationBadgeStyle {
    const normalized = normalizeCertificationName(certification);
  
    const exact = BADGE_STYLES.find(
      (style) => normalizeCertificationName(style.label) === normalized
    );
  
    if (exact) {
      return exact;
    }
  
    const partial = BADGE_STYLES.find((style) => {
      const styleName = normalizeCertificationName(style.label);
      return normalized.includes(styleName) || styleName.includes(normalized);
    });
  
    if (partial) {
      return partial;
    }
  
    return {
      ...DEFAULT_BADGE_STYLE,
      label: certification || DEFAULT_BADGE_STYLE.label,
      shortLabel: certification || DEFAULT_BADGE_STYLE.shortLabel,
    };
  }