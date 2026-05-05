import argparse
import csv
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd


CERTIFICATION_NAME = "EU Ecolabel"
REGISTRY_SECTION = "Certified Products"
OFFICIAL_SOURCE_URL = "https://environmental-data.ec.europa.eu/ecolabel/index.html"

DEFAULT_INPUT_DIR = Path("data") / "certifications" / "eu_ecolabel"
DEFAULT_OUTPUT_DIR = Path("data") / "certifications" / "eu_ecolabel"


EXPECTED_COLUMNS = [
    "product_or_service",
    "licence_number",
    "group_name",
    "code_type",
    "code_value",
    "product_or_service_name",
    "decision",
    "expiration_date",
    "company_name",
    "company_country",
    "vat_number",
    "extract_date",
]


def clean_text(value: object) -> str:
    if value is None:
        return ""

    if pd.isna(value):
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


def safe_filename(value: str) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def get_csv_files(input_dir: Path, explicit_csv: Optional[Path]) -> list[Path]:
    if explicit_csv is not None:
        if not explicit_csv.exists():
            raise FileNotFoundError(f"CSV file not found: {explicit_csv}")

        return [explicit_csv]

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    csv_files = sorted(input_dir.glob("*.csv"))

    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in: {input_dir}")

    return csv_files


def detect_delimiter(csv_path: Path) -> str:
    with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as file:
        sample = file.read(5000)

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ";"


def read_eu_ecolabel_csv(csv_path: Path) -> pd.DataFrame:
    delimiter = detect_delimiter(csv_path)

    df = pd.read_csv(
        csv_path,
        sep=delimiter,
        dtype=str,
        encoding="utf-8-sig",
        keep_default_na=False,
    )

    df.columns = [clean_text(column) for column in df.columns]

    missing_columns = [column for column in EXPECTED_COLUMNS if column not in df.columns]

    if missing_columns:
        raise ValueError(
            "The EU Ecolabel CSV does not contain the expected columns. "
            f"Missing columns: {missing_columns}. "
            f"Available columns: {list(df.columns)}"
        )

    df = df[EXPECTED_COLUMNS].copy()

    for column in EXPECTED_COLUMNS:
        df[column] = df[column].apply(clean_text)

    df["source_file"] = str(csv_path)
    df["source_file_name"] = csv_path.name
    df["source_url"] = OFFICIAL_SOURCE_URL
    df["certification"] = CERTIFICATION_NAME
    df["registry_section"] = REGISTRY_SECTION

    return df


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    result["expiration_date_parsed"] = pd.to_datetime(
        result["expiration_date"],
        errors="coerce",
        format="%Y-%m-%d",
    )

    result["extract_date_parsed"] = pd.to_datetime(
        result["extract_date"],
        errors="coerce",
        format="%Y-%m-%d",
    )

    today = pd.Timestamp(datetime.now().date())

    result["is_certificate_active"] = result["expiration_date_parsed"].apply(
        lambda value: bool(pd.notna(value) and value >= today)
    )

    result["days_until_expiration"] = result["expiration_date_parsed"].apply(
        lambda value: int((value - today).days) if pd.notna(value) else None
    )

    return result


def build_products_registry(raw_df: pd.DataFrame) -> pd.DataFrame:
    products_df = raw_df.copy()

    products_df["product_name"] = products_df["product_or_service_name"]
    products_df["product_name_normalized"] = products_df["product_name"].apply(
        normalize_for_matching
    )

    products_df["company_name_normalized"] = products_df["company_name"].apply(
        normalize_for_matching
    )

    products_df["group_name_normalized"] = products_df["group_name"].apply(
        normalize_for_matching
    )

    products_df["licence_number_normalized"] = products_df["licence_number"].apply(
        normalize_for_matching
    )

    products_df["code_value_normalized"] = products_df["code_value"].apply(
        normalize_for_matching
    )

    products_df["evidence_text"] = products_df.apply(
        lambda row: (
            f"{row['product_name']} | {row['company_name']} | "
            f"{row['group_name']} | licence {row['licence_number']} | "
            f"expires {row['expiration_date']}"
        ),
        axis=1,
    )

    products_df["registry_match_level"] = "product"

    products_df = products_df[
        [
            "certification",
            "registry_section",
            "registry_match_level",
            "product_or_service",
            "product_name",
            "product_name_normalized",
            "licence_number",
            "licence_number_normalized",
            "group_name",
            "group_name_normalized",
            "code_type",
            "code_value",
            "code_value_normalized",
            "decision",
            "expiration_date",
            "expiration_date_parsed",
            "is_certificate_active",
            "days_until_expiration",
            "company_name",
            "company_name_normalized",
            "company_country",
            "vat_number",
            "extract_date",
            "extract_date_parsed",
            "source_url",
            "source_file",
            "source_file_name",
            "evidence_text",
        ]
    ]

    products_df = products_df.drop_duplicates(
        subset=[
            "product_name_normalized",
            "company_name_normalized",
            "licence_number",
            "code_type",
            "code_value",
        ],
        keep="first",
    ).reset_index(drop=True)

    return products_df


def build_companies_registry(products_df: pd.DataFrame) -> pd.DataFrame:
    if products_df.empty:
        return pd.DataFrame()

    grouped = (
        products_df.groupby(
            [
                "company_name",
                "company_name_normalized",
                "company_country",
                "vat_number",
            ],
            dropna=False,
        )
        .agg(
            certified_product_rows=("product_name", "count"),
            unique_product_names=("product_name_normalized", "nunique"),
            unique_licences=("licence_number", "nunique"),
            product_groups=("group_name", lambda values: " | ".join(sorted(set(v for v in values if v)))),
            licence_numbers=("licence_number", lambda values: " | ".join(sorted(set(v for v in values if v)))),
            earliest_expiration=("expiration_date_parsed", "min"),
            latest_expiration=("expiration_date_parsed", "max"),
            active_certificates=("is_certificate_active", "sum"),
            source_url=("source_url", "first"),
            source_file=("source_file", "first"),
            source_file_name=("source_file_name", "first"),
        )
        .reset_index()
    )

    grouped["certification"] = CERTIFICATION_NAME
    grouped["registry_section"] = "Certified Companies"
    grouped["registry_match_level"] = "company"
    grouped["is_company_currently_active"] = grouped["active_certificates"].apply(
        lambda value: bool(value > 0)
    )

    grouped["evidence_text"] = grouped.apply(
        lambda row: (
            f"{row['company_name']} has {row['certified_product_rows']} EU Ecolabel product rows "
            f"across {row['unique_licences']} licence(s). Groups: {row['product_groups']}"
        ),
        axis=1,
    )

    grouped = grouped[
        [
            "certification",
            "registry_section",
            "registry_match_level",
            "company_name",
            "company_name_normalized",
            "company_country",
            "vat_number",
            "certified_product_rows",
            "unique_product_names",
            "unique_licences",
            "active_certificates",
            "is_company_currently_active",
            "product_groups",
            "licence_numbers",
            "earliest_expiration",
            "latest_expiration",
            "source_url",
            "source_file",
            "source_file_name",
            "evidence_text",
        ]
    ]

    grouped = grouped.sort_values(
        ["company_name_normalized", "company_country"]
    ).reset_index(drop=True)

    return grouped


def build_licences_registry(products_df: pd.DataFrame) -> pd.DataFrame:
    if products_df.empty:
        return pd.DataFrame()

    grouped = (
        products_df.groupby(
            [
                "licence_number",
                "licence_number_normalized",
                "company_name",
                "company_name_normalized",
                "company_country",
                "vat_number",
                "group_name",
                "group_name_normalized",
                "decision",
                "expiration_date",
                "expiration_date_parsed",
                "is_certificate_active",
            ],
            dropna=False,
        )
        .agg(
            certified_product_rows=("product_name", "count"),
            unique_product_names=("product_name_normalized", "nunique"),
            code_types=("code_type", lambda values: " | ".join(sorted(set(v for v in values if v)))),
            code_values=("code_value", lambda values: " | ".join(sorted(set(v for v in values if v))[:50])),
            extract_date=("extract_date", "first"),
            extract_date_parsed=("extract_date_parsed", "first"),
            source_url=("source_url", "first"),
            source_file=("source_file", "first"),
            source_file_name=("source_file_name", "first"),
        )
        .reset_index()
    )

    grouped["certification"] = CERTIFICATION_NAME
    grouped["registry_section"] = "Licences"
    grouped["registry_match_level"] = "licence"

    grouped["evidence_text"] = grouped.apply(
        lambda row: (
            f"Licence {row['licence_number']} for {row['company_name']} "
            f"covers {row['certified_product_rows']} product rows in {row['group_name']}."
        ),
        axis=1,
    )

    grouped = grouped[
        [
            "certification",
            "registry_section",
            "registry_match_level",
            "licence_number",
            "licence_number_normalized",
            "company_name",
            "company_name_normalized",
            "company_country",
            "vat_number",
            "group_name",
            "group_name_normalized",
            "decision",
            "expiration_date",
            "expiration_date_parsed",
            "is_certificate_active",
            "certified_product_rows",
            "unique_product_names",
            "code_types",
            "code_values",
            "extract_date",
            "extract_date_parsed",
            "source_url",
            "source_file",
            "source_file_name",
            "evidence_text",
        ]
    ]

    grouped = grouped.sort_values(
        ["company_name_normalized", "licence_number"]
    ).reset_index(drop=True)

    return grouped


def build_product_groups_registry(products_df: pd.DataFrame) -> pd.DataFrame:
    if products_df.empty:
        return pd.DataFrame()

    grouped = (
        products_df.groupby(
            [
                "group_name",
                "group_name_normalized",
            ],
            dropna=False,
        )
        .agg(
            certified_product_rows=("product_name", "count"),
            unique_product_names=("product_name_normalized", "nunique"),
            unique_companies=("company_name_normalized", "nunique"),
            unique_licences=("licence_number", "nunique"),
            countries=("company_country", lambda values: " | ".join(sorted(set(v for v in values if v)))),
            active_product_rows=("is_certificate_active", "sum"),
            source_url=("source_url", "first"),
            source_file=("source_file", "first"),
            source_file_name=("source_file_name", "first"),
        )
        .reset_index()
    )

    grouped["certification"] = CERTIFICATION_NAME
    grouped["registry_section"] = "Product Groups"
    grouped["registry_match_level"] = "product_group"

    grouped["evidence_text"] = grouped.apply(
        lambda row: (
            f"{row['group_name']} contains {row['certified_product_rows']} EU Ecolabel product rows, "
            f"{row['unique_companies']} companies and {row['unique_licences']} licences."
        ),
        axis=1,
    )

    grouped = grouped[
        [
            "certification",
            "registry_section",
            "registry_match_level",
            "group_name",
            "group_name_normalized",
            "certified_product_rows",
            "unique_product_names",
            "unique_companies",
            "unique_licences",
            "active_product_rows",
            "countries",
            "source_url",
            "source_file",
            "source_file_name",
            "evidence_text",
        ]
    ]

    grouped = grouped.sort_values(["group_name_normalized"]).reset_index(drop=True)

    return grouped


def build_metadata(
    csv_files: list[Path],
    raw_df: pd.DataFrame,
    products_df: pd.DataFrame,
    companies_df: pd.DataFrame,
    licences_df: pd.DataFrame,
    product_groups_df: pd.DataFrame,
) -> pd.DataFrame:
    extract_dates = sorted(set(value for value in products_df["extract_date"].tolist() if value))

    metadata = [
        {
            "certification": CERTIFICATION_NAME,
            "registry_section": REGISTRY_SECTION,
            "source_type": "CSV export",
            "source_url": OFFICIAL_SOURCE_URL,
            "source_files": " | ".join(str(path) for path in csv_files),
            "csv_files_processed": len(csv_files),
            "raw_rows": len(raw_df),
            "product_rows": len(products_df),
            "company_rows": len(companies_df),
            "licence_rows": len(licences_df),
            "product_group_rows": len(product_groups_df),
            "active_product_rows": int(products_df["is_certificate_active"].sum()) if not products_df.empty else 0,
            "extract_dates": " | ".join(extract_dates),
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": (
                "This EU Ecolabel registry was built from the CSV export downloaded from the "
                "EU Ecolabel product catalogue. It includes product-level, licence-level, "
                "company-level and product-group-level views."
            ),
        }
    ]

    return pd.DataFrame(metadata)


def save_outputs(
    output_dir: Path,
    raw_df: pd.DataFrame,
    products_df: pd.DataFrame,
    companies_df: pd.DataFrame,
    licences_df: pd.DataFrame,
    product_groups_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_csv = output_dir / "eu_ecolabel_raw.csv"
    products_csv = output_dir / "eu_ecolabel_products_registry.csv"
    companies_csv = output_dir / "eu_ecolabel_companies.csv"
    licences_csv = output_dir / "eu_ecolabel_licences.csv"
    product_groups_csv = output_dir / "eu_ecolabel_product_groups.csv"
    metadata_csv = output_dir / "eu_ecolabel_metadata.csv"
    excel_path = output_dir / "eu_ecolabel_registry.xlsx"

    raw_df.to_csv(raw_csv, index=False, encoding="utf-8-sig")
    products_df.to_csv(products_csv, index=False, encoding="utf-8-sig")
    companies_df.to_csv(companies_csv, index=False, encoding="utf-8-sig")
    licences_df.to_csv(licences_csv, index=False, encoding="utf-8-sig")
    product_groups_df.to_csv(product_groups_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        products_df.to_excel(writer, sheet_name="products", index=False)
        companies_df.to_excel(writer, sheet_name="companies", index=False)
        licences_df.to_excel(writer, sheet_name="licences", index=False)
        product_groups_df.to_excel(writer, sheet_name="product_groups", index=False)
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        raw_df.to_excel(writer, sheet_name="raw", index=False)

    print("")
    print("Saved files:")
    print(f"- {raw_csv}")
    print(f"- {products_csv}")
    print(f"- {companies_csv}")
    print(f"- {licences_csv}")
    print(f"- {product_groups_csv}")
    print(f"- {metadata_csv}")
    print(f"- {excel_path}")


def build_eu_ecolabel_registry(
    input_dir: Path,
    output_dir: Path,
    csv_path: Optional[Path],
) -> None:
    csv_files = get_csv_files(input_dir=input_dir, explicit_csv=csv_path)

    raw_frames = []

    print("Building EU Ecolabel registry from CSV export...")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print("")

    for current_csv_path in csv_files:
        print(f"Reading CSV: {current_csv_path}")

        current_df = read_eu_ecolabel_csv(current_csv_path)
        raw_frames.append(current_df)

        print(f"  Rows read: {len(current_df)}")

    raw_df = pd.concat(raw_frames, ignore_index=True)
    raw_df = parse_dates(raw_df)

    products_df = build_products_registry(raw_df)
    companies_df = build_companies_registry(products_df)
    licences_df = build_licences_registry(products_df)
    product_groups_df = build_product_groups_registry(products_df)

    metadata_df = build_metadata(
        csv_files=csv_files,
        raw_df=raw_df,
        products_df=products_df,
        companies_df=companies_df,
        licences_df=licences_df,
        product_groups_df=product_groups_df,
    )

    print("")
    print("Registry summary:")
    print(f"  Raw rows: {len(raw_df)}")
    print(f"  Product rows: {len(products_df)}")
    print(f"  Company rows: {len(companies_df)}")
    print(f"  Licence rows: {len(licences_df)}")
    print(f"  Product group rows: {len(product_groups_df)}")

    if not products_df.empty:
        print(f"  Active product rows: {int(products_df['is_certificate_active'].sum())}")

    save_outputs(
        output_dir=output_dir,
        raw_df=raw_df,
        products_df=products_df,
        companies_df=companies_df,
        licences_df=licences_df,
        product_groups_df=product_groups_df,
        metadata_df=metadata_df,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local EU Ecolabel registry from the official CSV product catalogue export."
    )

    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help=f"Directory containing EU Ecolabel CSV files. Default: {DEFAULT_INPUT_DIR}",
    )

    parser.add_argument(
        "--csv",
        default=None,
        help="Optional explicit CSV path. If omitted, all CSV files in input-dir are processed.",
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
    csv_path = Path(args.csv) if args.csv else None

    build_eu_ecolabel_registry(
        input_dir=input_dir,
        output_dir=output_dir,
        csv_path=csv_path,
    )


if __name__ == "__main__":
    main()