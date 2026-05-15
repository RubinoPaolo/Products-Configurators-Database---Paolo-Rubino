import "dotenv/config";
import path from "node:path";
import { fileURLToPath } from "node:url";
import XLSX from "xlsx";
import { PrismaClient } from "@prisma/client";
import { PrismaNeon } from "@prisma/adapter-neon";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const adapter = new PrismaNeon({
  connectionString: process.env.DATABASE_URL,
});

const prisma = new PrismaClient({ adapter });

const DATASET_PATH = path.join(
  __dirname,
  "..",
  "..",
  "Dataset_Enhanced_LEME_Paolo_Rubino.xlsx"
);

function clean(value) {
  if (value === undefined || value === null) return null;
  const text = String(value).trim();
  return text.length > 0 ? text : null;
}

function toBoolean(value) {
  const text = clean(value);
  if (!text) return null;

  const normalized = text.toUpperCase();

  if (["SI", "SÌ", "YES", "TRUE", "1"].includes(normalized)) return true;
  if (["NO", "FALSE", "0"].includes(normalized)) return false;

  return null;
}

function toInteger(value) {
  if (value === undefined || value === null || value === "") return null;

  const number = Number(value);

  if (!Number.isFinite(number)) return null;

  const rounded = Math.round(number);

  if (rounded < 1 || rounded > 5) return null;

  return rounded;
}

function slugify(text) {
  return String(text || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

function calculateIntelligenceScore(row) {
  const mobile = toInteger(row["Ottimizzato per Mobile?"]);
  const compatibility = toInteger(
    row["Presenza di regole/vincoli di compatibilità?"]
  );
  const complexity = toInteger(row["Livello di Complessità"]);

  const visualization = clean(row["Tipo di visualizzazione"]);

  const values = [];

  if (mobile !== null) values.push(mobile);
  if (compatibility !== null) values.push(compatibility);
  if (complexity !== null) values.push(complexity);

  if (visualization === "Interactive 3D") values.push(5);
  if (visualization === "Static 2D") values.push(3);

  if (values.length === 0) return null;

  const average = values.reduce((sum, value) => sum + value, 0) / values.length;

  return Number(average.toFixed(2));
}

async function main() {
  console.log("Import dataset started...");
  console.log(`Reading file: ${DATASET_PATH}`);

  const workbook = XLSX.readFile(DATASET_PATH);
  const firstSheetName = workbook.SheetNames[0];
  const worksheet = workbook.Sheets[firstSheetName];

  const rows = XLSX.utils.sheet_to_json(worksheet, {
    defval: null,
  });

  console.log(`Rows found in Excel: ${rows.length}`);

  await prisma.configurator.deleteMany();

  let imported = 0;
  let skipped = 0;

  for (const row of rows) {
    const company = clean(row["Company"]);

    if (!company) {
      skipped++;
      continue;
    }

    const industry = clean(row["Industry"]);
    const country = clean(row["Country"]);
    const product = clean(row["Product"]);

    const baseSlug =
      slugify(`${company}-${product || "configurator"}`) ||
      `configurator-${imported + 1}`;

    let slug = baseSlug;
    let counter = 2;

    while (await prisma.configurator.findUnique({ where: { slug } })) {
      slug = `${baseSlug}-${counter}`;
      counter++;
    }

    await prisma.configurator.create({
      data: {
        industry,
        country,
        company,
        slug,
        product,
        configuratorUrl: clean(row["Configurator URL"]),
        isActive: toBoolean(row["Attivo SI/NO"]),
        alternativeUrl: clean(row["Configurator URL alternativa"]),
        visualizationType: clean(row["Tipo di visualizzazione"]),
        mobileScore: toInteger(row["Ottimizzato per Mobile?"]),
        compatibilityScore: toInteger(
          row["Presenza di regole/vincoli di compatibilità?"]
        ),
        complexityScore: toInteger(row["Livello di Complessità"]),
        intelligenceScore: calculateIntelligenceScore(row),
        databaseDetailUrl: clean(row["Database detail URL"]),
      },
    });

    imported++;
  }

  console.log("Import completed.");
  console.log(`Imported rows: ${imported}`);
  console.log(`Skipped rows: ${skipped}`);
}

main()
  .catch((error) => {
    console.error("Import failed:");
    console.error(error);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });