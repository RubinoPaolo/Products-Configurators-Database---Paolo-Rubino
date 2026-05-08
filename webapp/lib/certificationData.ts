import fs from "fs";
import path from "path";

export type SiteCertificationRecord = {
  certification: string;
  decision: string;
  siteClaimType: string;
  confidence: string;
  score: number;
  matchMethod: string;
  evidenceLevel: string;
  matchedEntity: string;
  matchedCompany: string;
  matchedBrand: string;
  matchedProduct: string;
  matchedCategory: string;
  certificateIdentifier: string;
  sourceUrl: string;
  sourceFile: string;
  evidenceText: string;
};

export type ConfiguratorCertificationData = {
  company: string;
  product: string;
  directCertifications: SiteCertificationRecord[];
  directReviewCertifications: SiteCertificationRecord[];
  supplierCandidates: SiteCertificationRecord[];
};

type CertificationJson = {
  version: number;
  stats: Record<string, unknown>;
  byCompanyProductKey: Record<string, ConfiguratorCertificationData>;
};

function normalizeForKey(value: string | null | undefined) {
  return (value || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export function makeConfiguratorLookupKey(
  company: string | null | undefined,
  product: string | null | undefined
) {
  return `${normalizeForKey(company)}||${normalizeForKey(product)}`;
}

function makeConfiguratorKey(
  company: string | null | undefined,
  product: string | null | undefined
) {
  return makeConfiguratorLookupKey(company, product);
}

function emptyCertificationData(
  company: string | null | undefined,
  product: string | null | undefined
): ConfiguratorCertificationData {
  return {
    company: company || "",
    product: product || "",
    directCertifications: [],
    directReviewCertifications: [],
    supplierCandidates: [],
  };
}

function readCertificationJson(): CertificationJson | null {
  const filePath = path.join(
    process.cwd(),
    "data",
    "site-certifications",
    "configurator-certifications.json"
  );

  if (!fs.existsSync(filePath)) {
    return null;
  }

  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    return JSON.parse(raw) as CertificationJson;
  } catch {
    return null;
  }
}

export function getConfiguratorKeysForCertifications(
  certificationNames: string[]
): Set<string> | null {
  if (certificationNames.length === 0) return null;

  const json = readCertificationJson();
  if (!json) return new Set();

  let result: Set<string> | null = null;

  for (const certName of certificationNames) {
    const keysForCert = new Set<string>();
    for (const [key, data] of Object.entries(json.byCompanyProductKey)) {
      if (data.directCertifications.some((c) => c.certification === certName)) {
        keysForCert.add(key);
      }
    }
    if (result === null) {
      result = keysForCert;
    } else {
      const intersection = new Set<string>();
      result.forEach((k) => {
        if (keysForCert.has(k)) intersection.add(k);
      });
      result = intersection;
    }
  }

  return result ?? new Set<string>();
}

export function getConfiguratorCertifications(
  company: string | null | undefined,
  product: string | null | undefined
): ConfiguratorCertificationData {
  const json = readCertificationJson();

  if (!json) {
    return emptyCertificationData(company, product);
  }

  const key = makeConfiguratorKey(company, product);
  const match = json.byCompanyProductKey[key];

  if (!match) {
    return emptyCertificationData(company, product);
  }

  return match;
}