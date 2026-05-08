import argparse
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


DEFAULT_INPUT_CANDIDATES = [
    Path("data") / "certifications" / "matching_v2" / "certification_matches_best_v2.csv",
    Path("data") / "certifications" / "matching" / "certification_matches_best.csv",
]

DEFAULT_OUTPUT_PATH = (
    Path("webapp")
    / "data"
    / "site-certifications"
    / "configurator-certifications.json"
)


def clean_text(value: object) -> str:
    if value is None:
        return ""

    if isinstance(value, float) and pd.isna(value):
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_key(value: object) -> str:
    text = clean_text(value).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def make_configurator_key(company: object, product: object) -> str:
    return f"{normalize_for_key(company)}||{normalize_for_key(product)}"


def find_input_file(explicit_input: str | None) -> Path:
    if explicit_input:
        path = Path(explicit_input)

        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")

        return path

    for candidate in DEFAULT_INPUT_CANDIDATES:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "No certification matching file found. Expected one of:\n"
        + "\n".join(f"- {path}" for path in DEFAULT_INPUT_CANDIDATES)
    )


def read_matching_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")

    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, dtype=str).fillna("")

    raise ValueError(f"Unsupported input file type: {path}")


def parse_score(value: object) -> float:
    text = clean_text(value).replace(",", ".")

    if not text:
        return 0.0

    try:
        return float(text)
    except Exception:
        return 0.0


def is_direct_yes(decision: str) -> bool:
    decision = clean_text(decision)

    return decision in {"Direct Yes", "Yes"}


def is_direct_review(decision: str) -> bool:
    decision = clean_text(decision)

    return decision in {"Direct Review", "Review"}


def is_supplier_candidate(decision: str) -> bool:
    decision = clean_text(decision)

    return decision == "Supplier Candidate"


def record_from_row(row: pd.Series) -> dict:
    return {
        "certification": clean_text(row.get("certification", "")),
        "decision": clean_text(row.get("decision", "")),
        "siteClaimType": clean_text(row.get("site_claim_type", "")),
        "confidence": clean_text(row.get("confidence", "")),
        "score": parse_score(row.get("final_score", "")),
        "matchMethod": clean_text(row.get("match_method", "")),
        "evidenceLevel": clean_text(row.get("matched_evidence_level", "")),
        "matchedEntity": clean_text(row.get("matched_registry_entity", "")),
        "matchedCompany": clean_text(row.get("matched_registry_company", "")),
        "matchedBrand": clean_text(row.get("matched_registry_brand", "")),
        "matchedProduct": clean_text(row.get("matched_registry_product", "")),
        "matchedCategory": clean_text(row.get("matched_product_category", "")),
        "certificateIdentifier": clean_text(row.get("certificate_identifier", "")),
        "sourceUrl": clean_text(row.get("source_url", "")),
        "sourceFile": clean_text(row.get("source_file", "")),
        "evidenceText": clean_text(row.get("evidence_text", ""))[:1200],
    }


def keep_best_per_certification(records: list[dict]) -> list[dict]:
    best_by_certification = {}

    for record in records:
        certification = clean_text(record.get("certification", ""))

        if not certification:
            continue

        current = best_by_certification.get(certification)

        if current is None or float(record.get("score", 0)) > float(current.get("score", 0)):
            best_by_certification[certification] = record

    return sorted(
        best_by_certification.values(),
        key=lambda item: (
            clean_text(item.get("certification", "")),
            -float(item.get("score", 0)),
        ),
    )


def build_site_certification_data(input_path: Path, output_path: Path) -> None:
    df = read_matching_file(input_path)

    required_columns = [
        "configurator_company",
        "configurator_product",
        "certification",
        "decision",
    ]

    for column in required_columns:
        if column not in df.columns:
            raise ValueError(
                f"Missing required column '{column}' in input file: {input_path}"
            )

    grouped = {}
    stats = {
        "inputFile": str(input_path),
        "rowsRead": len(df),
        "directYesRows": 0,
        "directReviewRows": 0,
        "supplierCandidateRows": 0,
        "configuratorsWithDirectCertifications": 0,
        "configuratorsWithSupplierCandidates": 0,
        "builtAtUtc": datetime.now(timezone.utc).isoformat(),
    }

    for _, row in df.iterrows():
        company = clean_text(row.get("configurator_company", ""))
        product = clean_text(row.get("configurator_product", ""))

        if not company and not product:
            continue

        key = make_configurator_key(company, product)

        if key not in grouped:
            grouped[key] = {
                "company": company,
                "product": product,
                "directCertifications": [],
                "directReviewCertifications": [],
                "supplierCandidates": [],
            }

        decision = clean_text(row.get("decision", ""))
        record = record_from_row(row)

        if is_direct_yes(decision):
            grouped[key]["directCertifications"].append(record)
            stats["directYesRows"] += 1
        elif is_direct_review(decision):
            grouped[key]["directReviewCertifications"].append(record)
            stats["directReviewRows"] += 1
        elif is_supplier_candidate(decision):
            grouped[key]["supplierCandidates"].append(record)
            stats["supplierCandidateRows"] += 1

    final_grouped = {}

    for key, value in grouped.items():
        direct_certifications = keep_best_per_certification(
            value["directCertifications"]
        )
        direct_review_certifications = keep_best_per_certification(
            value["directReviewCertifications"]
        )
        supplier_candidates = keep_best_per_certification(
            value["supplierCandidates"]
        )

        if direct_certifications:
            stats["configuratorsWithDirectCertifications"] += 1

        if supplier_candidates:
            stats["configuratorsWithSupplierCandidates"] += 1

        final_grouped[key] = {
            "company": value["company"],
            "product": value["product"],
            "directCertifications": direct_certifications,
            "directReviewCertifications": direct_review_certifications,
            "supplierCandidates": supplier_candidates,
        }

    output = {
        "version": 1,
        "description": (
            "Static certification data generated from the local certification matching audit. "
            "Only direct certifications should be displayed as actual configurator/product/company certifications."
        ),
        "stats": stats,
        "byCompanyProductKey": final_grouped,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Site certification data generated.")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print("")
    print("Stats:")
    for key, value in stats.items():
        print(f"- {key}: {value}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build static certification JSON for the Next.js website."
    )

    parser.add_argument(
        "--input",
        default=None,
        help="Optional input matching CSV/XLSX path.",
    )

    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"Output JSON path. Default: {DEFAULT_OUTPUT_PATH}",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = find_input_file(args.input)
    output_path = Path(args.output)

    build_site_certification_data(
        input_path=input_path,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()