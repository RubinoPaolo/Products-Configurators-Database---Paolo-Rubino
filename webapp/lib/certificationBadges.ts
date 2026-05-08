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
      imagePath: "/certifications/b_corp.png",
      gradientClassName: "from-sky-500 via-blue-500 to-indigo-600",
      ringClassName: "ring-blue-300/50",
      textClassName: "text-blue-950",
    },
    {
      label: "PETA-Approved Vegan",
      shortLabel: "PETA",
      slug: "peta-approved-vegan",
      emoji: "🌱",
      imagePath: "/certifications/peta.png",
      gradientClassName: "from-emerald-400 via-green-500 to-lime-500",
      ringClassName: "ring-emerald-300/60",
      textClassName: "text-emerald-950",
    },
    {
      label: "Blue Angel",
      shortLabel: "Blue Angel",
      slug: "blue-angel",
      emoji: "🔵",
      imagePath: "/certifications/blue_angel.png",
      gradientClassName: "from-cyan-400 via-sky-500 to-blue-600",
      ringClassName: "ring-sky-300/60",
      textClassName: "text-sky-950",
    },
    {
      label: "Bluesign",
      shortLabel: "Bluesign",
      slug: "bluesign",
      emoji: "💧",
      imagePath: "/certifications/bluesign.png",
      gradientClassName: "from-blue-400 via-cyan-500 to-teal-500",
      ringClassName: "ring-cyan-300/60",
      textClassName: "text-cyan-950",
    },
    {
      label: "Cradle to Cradle Certified",
      shortLabel: "C2C",
      slug: "cradle-to-cradle",
      emoji: "♻️",
      imagePath: "/certifications/c2c.png",
      gradientClassName: "from-lime-400 via-green-500 to-emerald-600",
      ringClassName: "ring-lime-300/60",
      textClassName: "text-lime-950",
    },
    {
      label: "EU Ecolabel",
      shortLabel: "EU Ecolabel",
      slug: "eu-ecolabel",
      emoji: "🌼",
      imagePath: "/certifications/eu_ecolabel.png",
      gradientClassName: "from-yellow-300 via-lime-400 to-green-500",
      ringClassName: "ring-yellow-200/70",
      textClassName: "text-lime-950",
    },
    {
      label: "EWG Verified",
      shortLabel: "EWG",
      slug: "ewg-verified",
      emoji: "✅",
      imagePath: "/certifications/ewg.png",
      gradientClassName: "from-green-300 via-emerald-500 to-teal-600",
      ringClassName: "ring-green-300/60",
      textClassName: "text-emerald-950",
    },
    {
      label: "Fair for Life",
      shortLabel: "Fair for Life",
      slug: "fair-for-life",
      emoji: "🤝",
      imagePath: "/certifications/fair_for_life.png",
      gradientClassName: "from-orange-300 via-amber-400 to-yellow-500",
      ringClassName: "ring-amber-200/70",
      textClassName: "text-amber-950",
    },
    {
      label: "Global Organic Textile Standard",
      shortLabel: "GOTS",
      slug: "gots",
      emoji: "🧵",
      imagePath: "/certifications/gots.png",
      gradientClassName: "from-emerald-300 via-teal-400 to-cyan-500",
      ringClassName: "ring-teal-200/70",
      textClassName: "text-teal-950",
    },
    {
      label: "Global Recycled Standard",
      shortLabel: "GRS",
      slug: "grs",
      emoji: "♻️",
      imagePath: "/certifications/grs.png",
      gradientClassName: "from-green-400 via-lime-500 to-emerald-600",
      ringClassName: "ring-green-300/60",
      textClassName: "text-green-950",
    },
    {
      label: "OEKO-TEX MADE IN GREEN",
      shortLabel: "OEKO-TEX",
      slug: "oeko-tex-made-in-green",
      emoji: "🟢",
      imagePath: "/certifications/oeko_tex.png",
      gradientClassName: "from-lime-300 via-emerald-400 to-green-600",
      ringClassName: "ring-lime-200/70",
      textClassName: "text-green-950",
    },
    {
      label: "FSC",
      shortLabel: "FSC",
      slug: "fsc",
      emoji: "🌳",
      imagePath: "/certifications/fsc.png",
      gradientClassName: "from-green-500 via-emerald-600 to-teal-700",
      ringClassName: "ring-emerald-300/60",
      textClassName: "text-green-950",
    },
    {
      label: "GreenCircle Certified",
      shortLabel: "GreenCircle",
      slug: "green-circle",
      emoji: "🟩",
      imagePath: "/certifications/green_circle.png",
      gradientClassName: "from-emerald-400 via-green-500 to-cyan-500",
      ringClassName: "ring-emerald-300/60",
      textClassName: "text-emerald-950",
    },
    {
      label: "Environmental Product Declaration",
      shortLabel: "EPD",
      slug: "epd",
      emoji: "📄",
      imagePath: "/certifications/epd.png",
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
  
  export type CertificationOption = {
    name: string;
    shortLabel: string;
    emoji: string;
    gradientClassName: string;
  };

  export function getAllCertificationOptions(): CertificationOption[] {
    return BADGE_STYLES.map((s) => ({
      name: s.label,
      shortLabel: s.shortLabel,
      emoji: s.emoji,
      gradientClassName: s.gradientClassName,
    }));
  }

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