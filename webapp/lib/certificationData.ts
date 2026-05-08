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

function makeConfiguratorKey(
  company: string | null | undefined,
  product: string | null | undefined
) {
  return `${normalizeForKey(company)}||${normalizeForKey(product)}`;
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