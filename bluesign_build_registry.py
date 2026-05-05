import argparse
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from pypdf import PdfReader


DEFAULT_INPUT_DIR = Path("data") / "certifications" / "bluesign"
DEFAULT_OUTPUT_DIR = Path("data") / "certifications" / "bluesign"

CERTIFICATION_NAME = "Bluesign"
REGISTRY_SECTION = "System Partners - Brands Only"


COUNTRIES_AND_REGIONS = [
    "United Arab Emirates",
    "United Kingdom",
    "United States",
    "Hong Kong",
    "New Zealand",
    "South Korea",
    "Czech Republic",
    "South Africa",
    "Saudi Arabia",
    "Sri Lanka",
    "Switzerland",
    "Netherlands",
    "Philippines",
    "Indonesia",
    "Singapore",
    "Australia",
    "Bangladesh",
    "Cambodia",
    "Thailand",
    "Vietnam",
    "Germany",
    "Austria",
    "Belgium",
    "Bulgaria",
    "Canada",
    "China",
    "Croatia",
    "Denmark",
    "Finland",
    "France",
    "Greece",
    "Hungary",
    "Iceland",
    "India",
    "Ireland",
    "Italy",
    "Japan",
    "Latvia",
    "Lithuania",
    "Malaysia",
    "Mexico",
    "Norway",
    "Poland",
    "Portugal",
    "Romania",
    "Serbia",
    "Slovakia",
    "Slovenia",
    "Spain",
    "Sweden",
    "Taiwan",
    "Turkey",
    "Ukraine",
    "USA",
]


HEADER_FOOTER_PATTERNS = [
    r"^April\s+\d{1,2},\s+\d{4}$",
    r"^Company Name Country / Region$",
    r"^LIST OF SYSTEM PARTNERS \(BRANDS ONLY\)$",
    r"^Page\s+\d+\s+of\s+\d+$",
]


def clean_text(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_matching(value: object) -> str:
    text = clean_text(value).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_header_or_footer(line: str) -> bool:
    line = clean_text(line)

    if not line:
        return True

    for pattern in HEADER_FOOTER_PATTERNS:
        if re.match(pattern, line, flags=re.IGNORECASE):
            return True

    return False


def extract_registry_date(lines: List[str]) -> str:
    for line in lines:
        cleaned = clean_text(line)

        if re.match(r"^April\s+\d{1,2},\s+\d{4}$", cleaned, flags=re.IGNORECASE):
            return cleaned

    return ""


def get_pdf_files(input_dir: Path, explicit_pdf: Optional[Path]) -> List[Path]:
    if explicit_pdf is not None:
        if not explicit_pdf.exists():
            raise FileNotFoundError(f"PDF file not found: {explicit_pdf}")

        return [explicit_pdf]

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    pdf_files = sorted(input_dir.glob("*.pdf"))

    if not pdf_files:
        raise FileNotFoundError(f"No PDF files found in: {input_dir}")

    return pdf_files


def read_pdf_lines(pdf_path: Path) -> List[Dict[str, object]]:
    reader = PdfReader(str(pdf_path))
    rows = []

    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        raw_lines = text.splitlines()

        for raw_line in raw_lines:
            line = clean_text(raw_line)

            if line:
                rows.append(
                    {
                        "source_file": str(pdf_path),
                        "source_file_name": pdf_path.name,
                        "source_page": page_index,
                        "raw_line": line,
                    }
                )

    return rows


def split_brand_and_country(line: str) -> Tuple[str, str]:
    cleaned = clean_text(line)

    countries_sorted = sorted(COUNTRIES_AND_REGIONS, key=len, reverse=True)

    for country in countries_sorted:
        pattern = r"\s+" + re.escape(country) + r"$"

        if re.search(pattern, cleaned, flags=re.IGNORECASE):
            brand = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
            return brand, country

    return "", ""


def parse_bluesign_pdf(pdf_path: Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    pdf_line_rows = read_pdf_lines(pdf_path)

    if not pdf_line_rows:
        raise ValueError(
            f"No text could be extracted from the PDF: {pdf_path}. "
            "The PDF may be scanned or image-based."
        )

    all_lines = [str(row["raw_line"]) for row in pdf_line_rows]
    registry_date = extract_registry_date(all_lines)

    brand_rows = []
    rejected_rows = []

    for row in pdf_line_rows:
        raw_line = clean_text(row["raw_line"])

        if is_header_or_footer(raw_line):
            rejected_rows.append(
                {
                    **row,
                    "reason": "header/footer/empty",
                }
            )
            continue

        brand_name, country_region = split_brand_and_country(raw_line)

        if not brand_name or not country_region:
            rejected_rows.append(
                {
                    **row,
                    "reason": "could_not_split_brand_and_country",
                }
            )
            continue

        brand_rows.append(
            {
                "certification": CERTIFICATION_NAME,
                "registry_section": REGISTRY_SECTION,
                "brand_name": brand_name,
                "brand_name_normalized": normalize_for_matching(brand_name),
                "country_region": country_region,
                "registry_date": registry_date,
                "source_file": str(pdf_path),
                "source_file_name": pdf_path.name,
                "source_page": row["source_page"],
                "evidence_text": raw_line,
            }
        )

    brands_df = pd.DataFrame(brand_rows)
    rejected_df = pd.DataFrame(rejected_rows)

    if not brands_df.empty:
        brands_df = brands_df.drop_duplicates(
            subset=["brand_name_normalized", "country_region"],
            keep="first",
        ).sort_values(["brand_name_normalized", "country_region"])

        brands_df = brands_df.reset_index(drop=True)

    return brands_df, rejected_df


def build_metadata(
    pdf_files: List[Path],
    brands_df: pd.DataFrame,
    rejected_df: pd.DataFrame,
) -> pd.DataFrame:
    metadata_rows = [
        {
            "certification": CERTIFICATION_NAME,
            "registry_section": REGISTRY_SECTION,
            "source_type": "PDF",
            "source_files": " | ".join(str(path) for path in pdf_files),
            "brand_rows_extracted": len(brands_df),
            "unique_brands_extracted": brands_df["brand_name_normalized"].nunique()
            if not brands_df.empty
            else 0,
            "rejected_rows": len(rejected_df),
            "output_note": (
                "This registry is brand-level. It identifies Bluesign system partner brands, "
                "not necessarily individual certified products."
            ),
        }
    ]

    return pd.DataFrame(metadata_rows)


def save_outputs(
    output_dir: Path,
    brands_df: pd.DataFrame,
    rejected_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    brands_csv = output_dir / "bluesign_brands.csv"
    rejected_csv = output_dir / "bluesign_rejected_lines.csv"
    metadata_csv = output_dir / "bluesign_metadata.csv"
    excel_path = output_dir / "bluesign_registry.xlsx"

    brands_df.to_csv(brands_csv, index=False, encoding="utf-8-sig")
    rejected_df.to_csv(rejected_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        brands_df.to_excel(writer, sheet_name="brands", index=False)
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        rejected_df.to_excel(writer, sheet_name="rejected_lines", index=False)

    print("")
    print("Saved files:")
    print(f"- {brands_csv}")
    print(f"- {metadata_csv}")
    print(f"- {rejected_csv}")
    print(f"- {excel_path}")


def build_bluesign_registry(
    input_dir: Path,
    output_dir: Path,
    pdf_path: Optional[Path],
) -> None:
    pdf_files = get_pdf_files(input_dir=input_dir, explicit_pdf=pdf_path)

    all_brands = []
    all_rejected = []

    print("Building Bluesign registry from PDF source file(s)...")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print("")

    for current_pdf_path in pdf_files:
        print(f"Reading PDF: {current_pdf_path}")

        brands_df, rejected_df = parse_bluesign_pdf(current_pdf_path)

        all_brands.append(brands_df)
        all_rejected.append(rejected_df)

        print(f"  Extracted brand rows: {len(brands_df)}")
        print(f"  Rejected lines: {len(rejected_df)}")

    if all_brands:
        combined_brands_df = pd.concat(all_brands, ignore_index=True)
    else:
        combined_brands_df = pd.DataFrame()

    if all_rejected:
        combined_rejected_df = pd.concat(all_rejected, ignore_index=True)
    else:
        combined_rejected_df = pd.DataFrame()

    if not combined_brands_df.empty:
        combined_brands_df = combined_brands_df.drop_duplicates(
            subset=["brand_name_normalized", "country_region"],
            keep="first",
        ).sort_values(["brand_name_normalized", "country_region"])

        combined_brands_df = combined_brands_df.reset_index(drop=True)

    metadata_df = build_metadata(
        pdf_files=pdf_files,
        brands_df=combined_brands_df,
        rejected_df=combined_rejected_df,
    )

    print("")
    print("Registry summary:")
    print(f"  PDF files processed: {len(pdf_files)}")
    print(f"  Brand rows extracted: {len(combined_brands_df)}")
    print(
        "  Unique brands extracted: "
        f"{combined_brands_df['brand_name_normalized'].nunique() if not combined_brands_df.empty else 0}"
    )
    print(f"  Rejected lines: {len(combined_rejected_df)}")

    save_outputs(
        output_dir=output_dir,
        brands_df=combined_brands_df,
        rejected_df=combined_rejected_df,
        metadata_df=metadata_df,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local Bluesign brand registry from the official Bluesign PDF list."
    )

    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help=f"Directory containing Bluesign PDF files. Default: {DEFAULT_INPUT_DIR}",
    )

    parser.add_argument(
        "--pdf",
        default=None,
        help="Optional explicit PDF path. If omitted, all PDFs in input-dir are processed.",
    )

    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    pdf_path = Path(args.pdf) if args.pdf else None

    build_bluesign_registry(
        input_dir=input_dir,
        output_dir=output_dir,
        pdf_path=pdf_path,
    )


if __name__ == "__main__":
    main()