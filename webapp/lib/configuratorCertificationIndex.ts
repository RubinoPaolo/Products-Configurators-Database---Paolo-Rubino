import fs from "node:fs";
import path from "node:path";

type CertificationIndex = {
  byConfigurator: Map<string, Set<string>>;
  byCompany: Map<string, Set<string>>;
  options: string[];
  sourceFiles: string[];
};

type GenericRecord = Record<string, unknown>;

const KNOWN_CERTIFICATIONS = [
  "Blue Angel",
  "bluesign",
  "Cradle to Cradle Certified",
  "EU Ecolabel",
  "EWG Verified",
  "Fair for Life",
  "GOTS",
  "GRS",
  "OEKO-TEX MADE IN GREEN",
  "B Corp",
  "FSC",
  "GreenCircle Certified",
  "EPD",
  "PETA-Approved Vegan",
] as const;

const CERTIFICATION_ALIASES: Record<string, string> = {
  blueangel: "Blue Angel",
  blauerengel: "Blue Angel",

  bluesign: "bluesign",

  cradletocradle: "Cradle to Cradle Certified",
  cradletocradlecertified: "Cradle to Cradle Certified",
  c2c: "Cradle to Cradle Certified",

  euecolabel: "EU Ecolabel",
  ecolabel: "EU Ecolabel",

  ewgverified: "EWG Verified",
  ewg: "EWG Verified",

  fairforlife: "Fair for Life",

  gots: "GOTS",
  globalorganictextilestandard: "GOTS",

  grs: "GRS",
  globalrecycledstandard: "GRS",

  oekotexmadeingreen: "OEKO-TEX MADE IN GREEN",
  madeingreen: "OEKO-TEX MADE IN GREEN",
  oekotex: "OEKO-TEX MADE IN GREEN",

  bcorp: "B Corp",
  bcorporation: "B Corp",

  fsc: "FSC",
  foreststewardshipcouncil: "FSC",

  greencirclecertified: "GreenCircle Certified",
  greencircle: "GreenCircle Certified",

  epd: "EPD",
  environmentalproductdeclaration: "EPD",

  petaapprovedvegan: "PETA-Approved Vegan",
  petaapproved: "PETA-Approved Vegan",
  peta: "PETA-Approved Vegan",
};

let cachedIndex: CertificationIndex | null = null;

function normalizeText(value: string | null | undefined): string {
  return (value ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/&/g, " and ")
    .replace(/[^a-zA-Z0-9]+/g, " ")
    .trim()
    .toLowerCase();
}

function makeConfiguratorKey(
  company: string | null | undefined,
  product: string | null | undefined
): string {
  return `${normalizeText(company)}::${normalizeText(product)}`;
}

function makeCompanyKey(company: string | null | undefined): string {
  return normalizeText(company);
}

function canonicalizeCertification(raw: string | null | undefined): string | null {
  const normalized = normalizeText(raw).replace(/\s+/g, "");
  if (!normalized) {
    return null;
  }

  if (CERTIFICATION_ALIASES[normalized]) {
    return CERTIFICATION_ALIASES[normalized];
  }

  const exactKnown = KNOWN_CERTIFICATIONS.find(
    (item) => normalizeText(item).replace(/\s+/g, "") === normalized
  );

  return exactKnown ?? null;
}

function isTruthyCertificationValue(value: unknown): boolean {
  if (value === true || value === 1) {
    return true;
  }

  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    return ["yes", "true", "1", "y", "present", "certified"].includes(normalized);
  }

  return false;
}

function firstString(record: GenericRecord, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim().length > 0) {
      return value.trim();
    }
  }
  return "";
}

function collectCertificationsFromValue(value: unknown): string[] {
  const result = new Set<string>();

  if (Array.isArray(value)) {
    for (const item of value) {
      if (typeof item === "string") {
        const canonical = canonicalizeCertification(item);
        if (canonical) {
          result.add(canonical);
        }
      }
    }
  } else if (typeof value === "string") {
    const parts = value
      .split(/[|,;/]+/)
      .map((item) => item.trim())
      .filter(Boolean);

    for (const part of parts) {
      const canonical = canonicalizeCertification(part);
      if (canonical) {
        result.add(canonical);
      }
    }
  }

  return [...result];
}

function extractCertifications(record: GenericRecord): string[] {
  const result = new Set<string>();

  const directKeys = [
    "certifications",
    "certificationTypes",
    "certification_types",
    "certificationType",
    "certification_type",
    "matchedCertifications",
    "matched_certifications",
    "certification",
    "certification_name",
    "certificationName",
    "badges",
    "labels",
  ];

  for (const key of directKeys) {
    if (key in record) {
      for (const cert of collectCertificationsFromValue(record[key])) {
        result.add(cert);
      }
    }
  }

  for (const [key, value] of Object.entries(record)) {
    const canonicalFromKey = canonicalizeCertification(key);
    if (canonicalFromKey && isTruthyCertificationValue(value)) {
      result.add(canonicalFromKey);
    }

    if (typeof value === "string") {
      const canonicalFromValue = canonicalizeCertification(value);
      if (canonicalFromValue) {
        result.add(canonicalFromValue);
      }
    }
  }

  return [...result];
}

function extractRowsFromJson(json: unknown): GenericRecord[] {
  if (Array.isArray(json)) {
    return json.filter(
      (item): item is GenericRecord =>
        typeof item === "object" && item !== null && !Array.isArray(item)
    );
  }

  if (typeof json === "object" && json !== null) {
    const record = json as GenericRecord;

    const containerKeys = [
      "rows",
      "data",
      "records",
      "matches",
      "items",
      "results",
      "configurators",
    ];

    for (const key of containerKeys) {
      const value = record[key];
      if (Array.isArray(value)) {
        return value.filter(
          (item): item is GenericRecord =>
            typeof item === "object" && item !== null && !Array.isArray(item)
        );
      }
    }
  }

  return [];
}

function scanDirectoryForCertificationJsons(
  directoryPath: string,
  maxDepth = 3,
  currentDepth = 0
): string[] {
  if (!fs.existsSync(directoryPath)) {
    return [];
  }

  let results: string[] = [];

  const entries = fs.readdirSync(directoryPath, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = path.join(directoryPath, entry.name);

    if (entry.isDirectory()) {
      if (
        currentDepth < maxDepth &&
        !["node_modules", ".next", ".git"].includes(entry.name)
      ) {
        results = results.concat(
          scanDirectoryForCertificationJsons(fullPath, maxDepth, currentDepth + 1)
        );
      }
      continue;
    }

    const lowerName = entry.name.toLowerCase();
    if (
      lowerName.endsWith(".json") &&
      (lowerName.includes("cert") || lowerName.includes("match"))
    ) {
      results.push(fullPath);
    }
  }

  return results;
}

function getCandidateFiles(): string[] {
  const cwd = process.cwd();

  const explicitCandidates = [
    path.join(cwd, "data", "configurator_certification_matches.json"),
    path.join(cwd, "data", "configurator-certification-matches.json"),
    path.join(cwd, "data", "configurator_certifications.json"),
    path.join(cwd, "data", "configurator-certifications.json"),
    path.join(cwd, "data", "certification_matches.json"),
    path.join(cwd, "data", "certifications.json"),

    path.join(cwd, "public", "data", "configurator_certification_matches.json"),
    path.join(cwd, "public", "data", "configurator-certification-matches.json"),
    path.join(cwd, "public", "data", "configurator_certifications.json"),
    path.join(cwd, "public", "data", "configurator-certifications.json"),
    path.join(cwd, "public", "data", "certification_matches.json"),

    path.resolve(cwd, "..", "data", "configurator_certification_matches.json"),
    path.resolve(cwd, "..", "data", "configurator-certification-matches.json"),
    path.resolve(cwd, "..", "data", "configurator_certifications.json"),
    path.resolve(cwd, "..", "data", "configurator-certifications.json"),
    path.resolve(cwd, "..", "data", "certification_matches.json"),
  ];

  const scanRoots = [
    path.join(cwd, "data"),
    path.join(cwd, "public", "data"),
    path.resolve(cwd, "..", "data"),
  ];

  const allFiles = new Set<string>();

  for (const filePath of explicitCandidates) {
    if (fs.existsSync(filePath)) {
      allFiles.add(filePath);
    }
  }

  for (const root of scanRoots) {
    for (const filePath of scanDirectoryForCertificationJsons(root)) {
      allFiles.add(filePath);
    }
  }

  return [...allFiles];
}

function loadIndex(): CertificationIndex {
  if (cachedIndex) {
    return cachedIndex;
  }

  const byConfigurator = new Map<string, Set<string>>();
  const byCompany = new Map<string, Set<string>>();
  const optionSet = new Set<string>();
  const sourceFiles: string[] = [];

  const candidateFiles = getCandidateFiles();

  for (const filePath of candidateFiles) {
    try {
      const rawText = fs.readFileSync(filePath, "utf-8");
      const parsed = JSON.parse(rawText);
      const rows = extractRowsFromJson(parsed);

      if (rows.length === 0) {
        continue;
      }

      sourceFiles.push(filePath);

      for (const row of rows) {
        const company = firstString(row, [
          "company",
          "company_name",
          "companyName",
          "configurator_company",
          "configuratorCompany",
          "matched_company",
          "matchedCompany",
          "brand",
          "brand_name",
          "brandName",
        ]);

        const product = firstString(row, [
          "product",
          "product_name",
          "productName",
          "configurator_product",
          "configuratorProduct",
          "matched_product",
          "matchedProduct",
        ]);

        const certifications = extractCertifications(row);

        if (!company && !product) {
          continue;
        }

        if (certifications.length === 0) {
          continue;
        }

        const configuratorKey = makeConfiguratorKey(company, product);
        const companyKey = makeCompanyKey(company);

        if (!byConfigurator.has(configuratorKey)) {
          byConfigurator.set(configuratorKey, new Set<string>());
        }

        if (!byCompany.has(companyKey)) {
          byCompany.set(companyKey, new Set<string>());
        }

        for (const certification of certifications) {
          byConfigurator.get(configuratorKey)?.add(certification);
          byCompany.get(companyKey)?.add(certification);
          optionSet.add(certification);
        }
      }
    } catch {
      continue;
    }
  }

  cachedIndex = {
    byConfigurator,
    byCompany,
    options: [...optionSet].sort((a, b) => a.localeCompare(b)),
    sourceFiles,
  };

  return cachedIndex;
}

export function getCertificationOptions(): string[] {
  return loadIndex().options;
}

export function getCertificationsForConfigurator(
  company: string | null | undefined,
  product: string | null | undefined
): string[] {
  const index = loadIndex();

  const exact = index.byConfigurator.get(makeConfiguratorKey(company, product));
  const companyOnly = index.byCompany.get(makeCompanyKey(company));

  const result = new Set<string>();

  if (exact) {
    for (const item of exact) {
      result.add(item);
    }
  }

  if (companyOnly) {
    for (const item of companyOnly) {
      result.add(item);
    }
  }

  return [...result].sort((a, b) => a.localeCompare(b));
}

export function hasAnyCertification(
  company: string | null | undefined,
  product: string | null | undefined
): boolean {
  return getCertificationsForConfigurator(company, product).length > 0;
}

export function hasCertification(
  company: string | null | undefined,
  product: string | null | undefined,
  certificationType: string
): boolean {
  const normalizedTarget = certificationType.trim().toLowerCase();

  return getCertificationsForConfigurator(company, product).some(
    (item) => item.trim().toLowerCase() === normalizedTarget
  );
}

export function getCertificationIndexInfo() {
  const index = loadIndex();
  return {
    sourceFiles: index.sourceFiles,
    totalCertificationTypes: index.options.length,
  };
}