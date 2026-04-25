export function normalizeText(value?: string | null) {
  return (value ?? "").trim().toLowerCase();
}

export function getCountryCode(country?: string | null) {
  const key = normalizeText(country);

  const codes: Record<string, string> = {
    norway: "no",
    sweden: "se",
    finland: "fi",
    denmark: "dk",
    germany: "de",
    switzerland: "ch",
    austria: "at",
    italy: "it",
    france: "fr",
    spain: "es",
    portugal: "pt",
    belgium: "be",
    netherlands: "nl",
    poland: "pl",
    "czech republic": "cz",
    czechia: "cz",
    "united kingdom": "gb",
    uk: "gb",
    england: "gb",
    ireland: "ie",
    "united states": "us",
    usa: "us",
    "united states of america": "us",
    canada: "ca",
    australia: "au",
    china: "cn",
    japan: "jp",
    india: "in",
  };

  return codes[key] ?? null;
}

export type IndustryKey =
  | "accessories"
  | "apparel"
  | "beauty-health"
  | "electronics"
  | "food-packaging"
  | "footwear"
  | "games-music"
  | "house-garden"
  | "industrial-goods"
  | "kids-babies"
  | "motor-vehicles"
  | "office-merchandise"
  | "paper-books"
  | "pet-supplies"
  | "printing-platforms"
  | "sportswear-equipment"
  | "uncategorized";

export type IndustryTheme = {
  glow1: string;
  glow2: string;
  glow3: string;
  iconA: string;
  iconB: string;
};

function resolveIndustryKey(industry?: string | null): IndustryKey {
  const key = normalizeText(industry);

  if (key === "accessories" || key.includes("accessor")) {
    return "accessories";
  }

  if (key === "apparel" || key.includes("apparel") || key.includes("fashion") || key.includes("clothing")) {
    return "apparel";
  }

  if (key === "beauty & health" || key.includes("beauty") || key.includes("health")) {
    return "beauty-health";
  }

  if (key === "electronics" || key.includes("electronics")) {
    return "electronics";
  }

  if (key === "food & packaging" || key.includes("food") || key.includes("packaging")) {
    return "food-packaging";
  }

  if (key === "footwear" || key.includes("footwear")) {
    return "footwear";
  }

  if (key === "games & music" || key.includes("games") || key.includes("music")) {
    return "games-music";
  }

  if (
    key === "house & garden" ||
    key.includes("house") ||
    key.includes("garden") ||
    key.includes("furniture")
  ) {
    return "house-garden";
  }

  if (
    key === "industrial goods" ||
    key.includes("industrial") ||
    key.includes("machinery") ||
    key.includes("manufacturing")
  ) {
    return "industrial-goods";
  }

  if (key === "kids & babies" || key.includes("kids") || key.includes("babies") || key.includes("baby")) {
    return "kids-babies";
  }

  if (
    key === "motor vehicles" ||
    key.includes("motor") ||
    key.includes("vehicle") ||
    key.includes("automotive")
  ) {
    return "motor-vehicles";
  }

  if (
    key === "office & merchandise" ||
    key.includes("office") ||
    key.includes("merchandise")
  ) {
    return "office-merchandise";
  }

  if (key === "paper & books" || key.includes("paper") || key.includes("book")) {
    return "paper-books";
  }

  if (key === "pet supplies" || key.includes("pet")) {
    return "pet-supplies";
  }

  if (
    key === "printing platforms" ||
    key.includes("printing") ||
    key.includes("print")
  ) {
    return "printing-platforms";
  }

  if (
    key === "sportswear & equipment" ||
    key.includes("sportswear") ||
    key.includes("equipment") ||
    key.includes("sport")
  ) {
    return "sportswear-equipment";
  }

  return "uncategorized";
}

const industryThemes: Record<IndustryKey, IndustryTheme> = {
  accessories: {
    glow1: "rgba(236,72,153,0.22)",
    glow2: "rgba(168,85,247,0.18)",
    glow3: "rgba(251,191,36,0.14)",
    iconA: "👜",
    iconB: "🕶️",
  },

  apparel: {
    glow1: "rgba(59,130,246,0.22)",
    glow2: "rgba(139,92,246,0.18)",
    glow3: "rgba(34,197,94,0.14)",
    iconA: "👕",
    iconB: "🧵",
  },

  "beauty-health": {
    glow1: "rgba(244,114,182,0.22)",
    glow2: "rgba(45,212,191,0.16)",
    glow3: "rgba(250,204,21,0.14)",
    iconA: "🧴",
    iconB: "✨",
  },

  electronics: {
    glow1: "rgba(59,130,246,0.24)",
    glow2: "rgba(6,182,212,0.18)",
    glow3: "rgba(99,102,241,0.16)",
    iconA: "💻",
    iconB: "⚡",
  },

  "food-packaging": {
    glow1: "rgba(245,158,11,0.22)",
    glow2: "rgba(249,115,22,0.18)",
    glow3: "rgba(34,197,94,0.14)",
    iconA: "📦",
    iconB: "🍽️",
  },

  footwear: {
    glow1: "rgba(34,197,94,0.20)",
    glow2: "rgba(59,130,246,0.16)",
    glow3: "rgba(251,191,36,0.12)",
    iconA: "👟",
    iconB: "🦶",
  },

  "games-music": {
    glow1: "rgba(168,85,247,0.22)",
    glow2: "rgba(34,211,238,0.18)",
    glow3: "rgba(236,72,153,0.14)",
    iconA: "🎸",
    iconB: "🎵",
  },

  "house-garden": {
    glow1: "rgba(34,197,94,0.26)",
    glow2: "rgba(16,185,129,0.18)",
    glow3: "rgba(132,204,22,0.18)",
    iconA: "🏡",
    iconB: "🌿",
  },

  "industrial-goods": {
    glow1: "rgba(249,115,22,0.22)",
    glow2: "rgba(107,114,128,0.18)",
    glow3: "rgba(251,191,36,0.12)",
    iconA: "🏭",
    iconB: "⚙️",
  },

  "kids-babies": {
    glow1: "rgba(251,191,36,0.22)",
    glow2: "rgba(96,165,250,0.16)",
    glow3: "rgba(244,114,182,0.14)",
    iconA: "🧸",
    iconB: "🍼",
  },

  "motor-vehicles": {
    glow1: "rgba(249,115,22,0.24)",
    glow2: "rgba(239,68,68,0.16)",
    glow3: "rgba(251,191,36,0.14)",
    iconA: "🚗",
    iconB: "🏎️",
  },

  "office-merchandise": {
    glow1: "rgba(59,130,246,0.22)",
    glow2: "rgba(107,114,128,0.16)",
    glow3: "rgba(16,185,129,0.12)",
    iconA: "💼",
    iconB: "📎",
  },

  "paper-books": {
    glow1: "rgba(96,165,250,0.18)",
    glow2: "rgba(250,204,21,0.14)",
    glow3: "rgba(248,250,252,0.10)",
    iconA: "📚",
    iconB: "📝",
  },

  "pet-supplies": {
    glow1: "rgba(16,185,129,0.22)",
    glow2: "rgba(250,204,21,0.16)",
    glow3: "rgba(34,197,94,0.14)",
    iconA: "🐾",
    iconB: "🦴",
  },

  "printing-platforms": {
    glow1: "rgba(99,102,241,0.22)",
    glow2: "rgba(34,211,238,0.16)",
    glow3: "rgba(168,85,247,0.14)",
    iconA: "🖨️",
    iconB: "🖼️",
  },

  "sportswear-equipment": {
    glow1: "rgba(34,197,94,0.20)",
    glow2: "rgba(59,130,246,0.16)",
    glow3: "rgba(251,191,36,0.12)",
    iconA: "🏅",
    iconB: "🏋️",
  },

  uncategorized: {
    glow1: "rgba(59,130,246,0.24)",
    glow2: "rgba(6,182,212,0.18)",
    glow3: "rgba(99,102,241,0.14)",
    iconA: "🧩",
    iconB: "✦",
  },
};

export function getIndustryTheme(industry?: string | null): IndustryTheme {
  const industryKey = resolveIndustryKey(industry);
  return industryThemes[industryKey];
}

export function getIndustrySticker(industry?: string | null) {
  return getIndustryTheme(industry).iconA;
}

export function getProductSticker(product?: string | null) {
  const key = normalizeText(product);

  if (key.includes("chair")) return "💺";
  if (key.includes("desk")) return "🪑";
  if (key.includes("sofa")) return "🛋️";
  if (key.includes("table")) return "🪵";
  if (key.includes("shelf")) return "🗄️";

  if (key.includes("bag") || key.includes("handbag")) return "👜";
  if (key.includes("backpack")) return "🎒";
  if (key.includes("hat") || key.includes("cap")) return "🧢";
  if (key.includes("shoe") || key.includes("sneaker")) return "👟";
  if (key.includes("sandal")) return "👡";
  if (key.includes("watch")) return "⌚";
  if (key.includes("ring")) return "💍";
  if (key.includes("pendant")) return "📿";
  if (key.includes("suit")) return "🤵";
  if (key.includes("shirt") || key.includes("t-shirt")) return "👕";

  if (key.includes("car")) return "🚗";
  if (key.includes("trailer")) return "🚚";
  if (key.includes("harvester")) return "🚜";
  if (key.includes("bike") || key.includes("bicycle")) return "🚲";

  if (key.includes("guitar")) return "🎸";
  if (key.includes("pc")) return "💻";
  if (key.includes("server")) return "🖥️";
  if (key.includes("cable")) return "🔌";

  if (key.includes("rug") || key.includes("carpet")) return "🧶";
  if (key.includes("pizza")) return "🍕";
  if (key.includes("chocolate")) return "🍫";
  if (key.includes("cookie")) return "🍪";
  if (key.includes("cereal")) return "🥣";
  if (key.includes("nutrition bar")) return "🍫";

  if (key.includes("razor")) return "🪒";
  if (key.includes("lipstick")) return "💄";
  if (key.includes("shampoo")) return "🧴";

  if (key.includes("door")) return "🚪";
  if (key.includes("window")) return "🪟";
  if (key.includes("cage")) return "🦜";
  if (key.includes("dog tag")) return "🐕";
  if (key.includes("mug")) return "☕";
  if (key.includes("calendar")) return "🗓️";
  if (key.includes("portrait") || key.includes("photograph") || key.includes("photo")) return "🖼️";
  if (key.includes("pencil")) return "✏️";
  if (key.includes("skateboard")) return "🛹";
  if (key.includes("tent")) return "⛺";
  if (key.includes("plate")) return "🍽️";
  if (key.includes("buggy")) return "🛒";
  if (key.includes("energy supply")) return "🔋";
  if (key.includes("workbench")) return "🛠️";
  if (key.includes("elevator")) return "🛗";
  if (key.includes("name assembly") || key.includes("exhibition booth")) return "🧩";
  if (key.includes("tea favor")) return "🍵";

  return "📦";
}

export function getVisualizationSticker(visualization?: string | null) {
  const key = normalizeText(visualization);

  if (key.includes("3d")) return "🧊";
  if (key.includes("2d")) return "🖼️";

  return "🎨";
}