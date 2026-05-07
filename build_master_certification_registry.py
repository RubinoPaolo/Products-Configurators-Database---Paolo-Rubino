import argparse
import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


DEFAULT_CERTIFICATIONS_DIR = Path("data") / "certifications"
DEFAULT_OUTPUT_DIR = Path("data") / "certifications" / "master_registry"

EXCEL_ILLEGAL_CHARACTERS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


EXPECTED_CERTIFICATION_FOLDERS = {
    "blue_angel": "Blue Angel",
    "bluesign": "Bluesign",
    "cradle_to_cradle": "Cradle to Cradle Certified",
    "eu_ecolabel": "EU Ecolabel",
    "ewg_verified": "EWG Verified",
    "fair_for_life": "Fair for Life",
    "gots": "Global Organic Textile Standard",
    "GRS": "Global Recycled Standard",
    "oeko_tex_made_in_green": "OEKO-TEX MADE IN GREEN",
    "b_corp": "B Corp",
    "fsc": "FSC",
    "green_circle": "GreenCircle Certified",
    "epd": "Environmental Product Declaration",
    "peta_approved_vegan": "PETA-Approved Vegan",
}


SKIP_FILE_KEYWORDS = [
    "metadata",
    "scrape_log",
    "country_summary",
    "countries",
    "domain_summary",
    "label_summary",
    "compliance_summary",
    "standards_summary",
    "certified_since_summary",
    "certification_claims",
    "product_types",
    "product_categories",
    "types",
    "checkpoint",
    "raw_pages",
    "debug",
    "master_certification_registry",
    "unmapped",
    "summary",
]

PRIMARY_FILE_KEYWORDS = [
    "products",
    "companies",
    "brands",
    "suppliers",
    "partners",
    "organizations",
    "organisations",
    "certificate_rows",
    "epds",
    "registry",
    "made_in_green",
    "b_corp",
    "fsc",
    "grs",
    "gots",
    "peta",
    "green_circle",
    "cradle",
    "ecolabel",
    "ewg",
    "fair_for_life",
    "blue",
    "bluesign",
]

SKIP_SHEET_KEYWORDS = [
    "metadata",
    "scrape_log",
    "country_summary",
    "countries",
    "domain_summary",
    "label_summary",
    "compliance_summary",
    "standards_summary",
    "certified_since",
    "product_categories",
    "product_types",
    "epd_types",
    "summary",
    "raw",
]


FOLDER_CERTIFICATION_MAP = {
    "blue_angel": "Blue Angel",
    "blauer_engel": "Blue Angel",
    "bluesign": "Bluesign",
    "cradle_to_cradle": "Cradle to Cradle Certified",
    "c2c": "Cradle to Cradle Certified",
    "eu_ecolabel": "EU Ecolabel",
    "ecolabel": "EU Ecolabel",
    "ewg": "EWG Verified",
    "ewg_verified": "EWG Verified",
    "fair_for_life": "Fair for Life",
    "gots": "Global Organic Textile Standard",
    "global_organic_textile_standard": "Global Organic Textile Standard",
    "grs": "Global Recycled Standard",
    "global_recycled_standard": "Global Recycled Standard",
    "oeko_tex": "OEKO-TEX MADE IN GREEN",
    "oeko_tex_made_in_green": "OEKO-TEX MADE IN GREEN",
    "b_corp": "B Corp",
    "fsc": "FSC",
    "green_circle": "GreenCircle Certified",
    "epd": "Environmental Product Declaration",
    "peta": "PETA-Approved Vegan",
    "peta_approved_vegan": "PETA-Approved Vegan",
}


COMPANY_COLUMN_CANDIDATES = [
    "company_name",
    "company",
    "organization_name",
    "organisation_name",
    "organization",
    "organisation",
    "supplier",
    "supplier_name",
    "partner",
    "partner_name",
    "manufacturer",
    "producer",
    "owner",
    "certificate_holder",
    "certificate holder",
    "holder",
    "applicant",
    "legal_entity",
    "entity_name",
]

BRAND_COLUMN_CANDIDATES = [
    "brand_name",
    "brand",
    "brands",
    "certified_brand",
    "brandname",
]

PRODUCT_COLUMN_CANDIDATES = [
    "product_name",
    "product",
    "certified_product",
    "input_trade_name",
    "input trade name",
    "trade_name",
    "trade name",
    "product_title",
    "declaration_name",
    "epd_product_name",
]

CATEGORY_COLUMN_CANDIDATES = [
    "product_category",
    "product category",
    "category",
    "product_type",
    "product type",
    "type_utilisation",
    "type / utilisation",
    "type",
    "output_category",
    "output category",
    "sector",
    "field_of_operation",
    "field of operation",
    "industry",
]

COUNTRY_COLUMN_CANDIDATES = [
    "country",
    "country_name",
    "country name",
    "country_area",
    "country/area",
    "country_region",
    "country/region",
    "geographical_scope",
    "geographical scope",
    "location",
    "state_province",
    "state/province",
]

CLAIM_COLUMN_CANDIDATES = [
    "certification_claim",
    "certification claim",
    "standard_label",
    "standard label",
    "standards_labels",
    "standards labels",
    "claim",
    "epd_type",
    "epd type",
    "certificate_type",
    "certificate type",
    "certification_type",
    "certification type",
    "certification_level",
    "certification level",
    "compliance_label",
    "compliance label",
    "cert_status",
    "cert status",
    "certificate_status",
    "certificate status",
    "registry_match_level",
]

IDENTIFIER_COLUMN_CANDIDATES = [
    "certificate_id",
    "certificate id",
    "certificate_code",
    "certificate code",
    "licence",
    "license",
    "epd_number",
    "epd number",
    "certification_number",
    "certification number",
    "registration_number",
    "registration number",
    "product_id",
    "product id",
    "id",
]

URL_COLUMN_CANDIDATES = [
    "product_url",
    "profile_url",
    "website_url",
    "download_url",
    "source_url",
    "registry_url",
    "url",
    "database_detail_url",
]

EVIDENCE_COLUMN_CANDIDATES = [
    "evidence_text",
    "evidence text",
    "raw_text",
    "raw text",
    "raw_company_text",
    "raw company text",
    "description",
    "source_text",
    "source text",
]

MATCH_LEVEL_COLUMN_CANDIDATES = [
    "registry_match_level",
    "match_level",
    "match level",
    "registry_section",
    "registry section",
]


LEGAL_SUFFIXES = [
    "incorporated",
    "corporation",
    "company",
    "limited",
    "ltd",
    "llc",
    "plc",
    "inc",
    "corp",
    "co",
    "gmbh",
    "ag",
    "kg",
    "oy",
    "ab",
    "bv",
    "nv",
    "srl",
    "sr",
    "spa",
    "s.p.a",
    "sas",
    "sa",
    "s.a",
    "pte",
    "pte ltd",
    "pty",
    "pty ltd",
    "kft",
    "aps",
    "as",
    "a/s",
    "sl",
    "s.l",
    "llp",
    "lp",
    "group",
    "holdings",
    "holding",
]


MASTER_COLUMNS = [
    "master_record_id",
    "certification",
    "certification_full_name",
    "evidence_level",
    "registry_match_level_raw",
    "applies_to_configurator_product_by",
    "certified_entity_name",
    "certified_entity_type",
    "certified_entity_name_normalized",
    "certified_entity_name_normalized_strict",
    "certified_company",
    "certified_company_normalized",
    "certified_company_normalized_strict",
    "certified_brand",
    "certified_brand_normalized",
    "certified_brand_normalized_strict",
    "certified_product",
    "certified_product_normalized",
    "certified_product_normalized_strict",
    "product_category",
    "product_category_normalized",
    "country_or_scope",
    "country_or_scope_normalized",
    "certification_claim_or_standard",
    "certificate_identifier",
    "source_url",
    "source_file",
    "source_sheet",
    "source_row_number",
    "evidence_text",
    "created_at_utc",
]


def strip_excel_illegal_characters(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = EXCEL_ILLEGAL_CHARACTERS_RE.sub("", text)
    return text


def clean_text(value: object) -> str:
    if value is None:
        return ""

    if isinstance(value, float) and pd.isna(value):
        return ""

    text = strip_excel_illegal_characters(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = text.replace("☻", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sanitize_dataframe_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    sanitized_df = df.copy()

    for column in sanitized_df.columns:
        if sanitized_df[column].dtype == "object":
            sanitized_df[column] = sanitized_df[column].apply(clean_text)

    return sanitized_df


def normalize_column_name(value: object) -> str:
    text = clean_text(value).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text.strip()


def normalize_for_matching(value: object, remove_legal_suffixes: bool = False) -> str:
    text = clean_text(value).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if remove_legal_suffixes:
        suffixes = set()

        for suffix in LEGAL_SUFFIXES:
            normalized_suffix = normalize_for_matching(suffix, remove_legal_suffixes=False)
            for token in normalized_suffix.split():
                suffixes.add(token)

        tokens = text.split()
        filtered_tokens = [token for token in tokens if token not in suffixes]

        text = " ".join(filtered_tokens)
        text = re.sub(r"\s+", " ", text).strip()

    return text


def make_hash_key(*values: object) -> str:
    raw_key = "|".join(clean_text(value) for value in values)
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def is_supported_data_file(path: Path) -> bool:
    return path.suffix.lower() in {".csv", ".xlsx", ".xls"}


def should_skip_file(path: Path) -> bool:
    lowered = path.name.lower()

    if not is_supported_data_file(path):
        return True

    if any(keyword in lowered for keyword in SKIP_FILE_KEYWORDS):
        return True

    return False


def looks_like_primary_data_file(path: Path) -> bool:
    lowered = path.name.lower()

    if should_skip_file(path):
        return False

    if any(keyword in lowered for keyword in PRIMARY_FILE_KEYWORDS):
        return True

    return False


def should_skip_sheet(sheet_name: str) -> bool:
    lowered = sheet_name.lower()
    return any(keyword in lowered for keyword in SKIP_SHEET_KEYWORDS)


def discover_certification_folders(certifications_dir: Path) -> Dict[str, Path]:
    discovered = {}

    if not certifications_dir.exists():
        return discovered

    for path in certifications_dir.iterdir():
        if path.is_dir() and path.name != "master_registry":
            discovered[path.name.lower()] = path

    return discovered


def find_folder_for_expected_certification(
    expected_folder_name: str,
    certifications_dir: Path,
    discovered_folders: Dict[str, Path],
) -> Optional[Path]:
    expected_lower = expected_folder_name.lower()

    if expected_lower in discovered_folders:
        return discovered_folders[expected_lower]

    expected_normalized = normalize_column_name(expected_folder_name)

    for discovered_name, discovered_path in discovered_folders.items():
        discovered_normalized = normalize_column_name(discovered_name)

        if discovered_normalized == expected_normalized:
            return discovered_path

    return None


def select_files_from_folder(folder: Path) -> Tuple[List[Path], str, int, int, int]:
    if not folder.exists():
        return [], "missing_folder", 0, 0, 0

    all_supported_files = [
        path for path in folder.rglob("*")
        if path.is_file()
        and is_supported_data_file(path)
        and "debug" not in str(path).lower()
        and "master_registry" not in str(path).lower()
    ]

    usable_files = [
        path for path in all_supported_files
        if not should_skip_file(path)
    ]

    primary_csv_files = [
        path for path in usable_files
        if path.suffix.lower() == ".csv" and looks_like_primary_data_file(path)
    ]

    primary_excel_files = [
        path for path in usable_files
        if path.suffix.lower() in {".xlsx", ".xls"} and looks_like_primary_data_file(path)
    ]

    fallback_csv_files = [
        path for path in usable_files
        if path.suffix.lower() == ".csv"
    ]

    fallback_excel_files = [
        path for path in usable_files
        if path.suffix.lower() in {".xlsx", ".xls"}
    ]

    if primary_csv_files:
        return sorted(primary_csv_files), "selected_primary_csv_files", len(all_supported_files), len(primary_csv_files), len(primary_excel_files)

    if primary_excel_files:
        return sorted(primary_excel_files), "selected_primary_excel_files_no_csv_available", len(all_supported_files), len(primary_csv_files), len(primary_excel_files)

    if fallback_csv_files:
        return sorted(fallback_csv_files), "fallback_selected_any_usable_csv_files", len(all_supported_files), len(primary_csv_files), len(primary_excel_files)

    if fallback_excel_files:
        return sorted(fallback_excel_files), "fallback_selected_any_usable_excel_files", len(all_supported_files), len(primary_csv_files), len(primary_excel_files)

    if all_supported_files:
        return [], "supported_files_found_but_all_skipped_or_non_primary", len(all_supported_files), len(primary_csv_files), len(primary_excel_files)

    return [], "folder_exists_but_no_supported_files", len(all_supported_files), len(primary_csv_files), len(primary_excel_files)


def collect_input_files(certifications_dir: Path) -> Tuple[List[Path], List[Dict[str, object]]]:
    if not certifications_dir.exists():
        raise FileNotFoundError(f"Certifications directory not found: {certifications_dir}")

    discovered_folders = discover_certification_folders(certifications_dir)

    selected_files: List[Path] = []
    inventory_rows: List[Dict[str, object]] = []

    processed_folder_paths = set()

    for expected_folder_name, expected_certification_name in EXPECTED_CERTIFICATION_FOLDERS.items():
        folder = find_folder_for_expected_certification(
            expected_folder_name=expected_folder_name,
            certifications_dir=certifications_dir,
            discovered_folders=discovered_folders,
        )

        if folder is None:
            inventory_rows.append(
                {
                    "expected_certification": expected_certification_name,
                    "expected_folder": str(certifications_dir / expected_folder_name),
                    "actual_folder": "",
                    "folder_status": "missing_folder",
                    "files_found": 0,
                    "primary_csv_files": 0,
                    "primary_excel_files": 0,
                    "files_selected": 0,
                    "selection_reason": "missing_folder",
                    "selected_files": "",
                    "fallback_used": False,
                }
            )
            continue

        processed_folder_paths.add(folder.resolve())

        chosen_files, reason, files_found, primary_csv_count, primary_excel_count = select_files_from_folder(folder)

        selected_files.extend(chosen_files)

        inventory_rows.append(
            {
                "expected_certification": expected_certification_name,
                "expected_folder": str(certifications_dir / expected_folder_name),
                "actual_folder": str(folder),
                "folder_status": "available",
                "files_found": files_found,
                "primary_csv_files": primary_csv_count,
                "primary_excel_files": primary_excel_count,
                "files_selected": len(chosen_files),
                "selection_reason": reason,
                "selected_files": " | ".join(str(path) for path in chosen_files),
                "fallback_used": reason.startswith("fallback"),
            }
        )

    for folder in sorted(discovered_folders.values()):
        if folder.resolve() in processed_folder_paths:
            continue

        if folder.name == "master_registry":
            continue

        chosen_files, reason, files_found, primary_csv_count, primary_excel_count = select_files_from_folder(folder)

        selected_files.extend(chosen_files)

        inventory_rows.append(
            {
                "expected_certification": infer_certification_from_path(folder),
                "expected_folder": "",
                "actual_folder": str(folder),
                "folder_status": "extra_discovered_folder",
                "files_found": files_found,
                "primary_csv_files": primary_csv_count,
                "primary_excel_files": primary_excel_count,
                "files_selected": len(chosen_files),
                "selection_reason": reason,
                "selected_files": " | ".join(str(path) for path in chosen_files),
                "fallback_used": reason.startswith("fallback"),
            }
        )

    selected_files = sorted(set(selected_files))

    return selected_files, inventory_rows


def read_csv_with_fallback(path: Path) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    last_error = None

    for encoding in encodings:
        try:
            return pd.read_csv(path, encoding=encoding, dtype=str)
        except Exception as error:
            last_error = error

    raise RuntimeError(f"Could not read CSV file {path}: {last_error}")


def read_tables_from_file(path: Path) -> List[Tuple[str, pd.DataFrame]]:
    suffix = path.suffix.lower()

    if suffix == ".csv":
        df = read_csv_with_fallback(path)
        return [("csv", df)]

    if suffix in {".xlsx", ".xls"}:
        excel = pd.ExcelFile(path)
        tables = []

        for sheet_name in excel.sheet_names:
            if should_skip_sheet(sheet_name):
                continue

            try:
                df = pd.read_excel(path, sheet_name=sheet_name, dtype=str)
                tables.append((sheet_name, df))
            except Exception:
                continue

        return tables

    return []


def normalize_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [clean_text(column) for column in df.columns]
    return df


def build_column_lookup(df: pd.DataFrame) -> Dict[str, str]:
    lookup = {}

    for column in df.columns:
        normalized = normalize_column_name(column)

        if normalized and normalized not in lookup:
            lookup[normalized] = column

    return lookup


def choose_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    lookup = build_column_lookup(df)

    for candidate in candidates:
        candidate_normalized = normalize_column_name(candidate)

        if candidate_normalized in lookup:
            return lookup[candidate_normalized]

    for candidate in candidates:
        candidate_normalized = normalize_column_name(candidate)

        for normalized_column, original_column in lookup.items():
            if candidate_normalized and candidate_normalized in normalized_column:
                return original_column

    return None


def get_row_value(row: pd.Series, column: Optional[str]) -> str:
    if not column:
        return ""

    if column not in row:
        return ""

    return clean_text(row[column])


def infer_certification_from_path(path: Path) -> str:
    path_text = str(path).lower().replace("\\", "/")

    for key, certification_name in FOLDER_CERTIFICATION_MAP.items():
        if key.lower() in path_text:
            return certification_name

    folder_name = path.parent.name.replace("_", " ").replace("-", " ").title()
    return folder_name


def infer_certification_from_dataframe(df: pd.DataFrame, path: Path) -> str:
    for column_candidate in [
        "certification_full_name",
        "certification_display_name",
        "certification",
        "certification_name",
    ]:
        column = choose_column(df, [column_candidate])

        if column:
            values = [
                clean_text(value)
                for value in df[column].dropna().astype(str).head(20).tolist()
                if clean_text(value)
            ]

            if values:
                value = values[0]

                if value.lower() not in {
                    "certification",
                    "certification claim",
                    "certification_claim",
                }:
                    return value

    return infer_certification_from_path(path)


def infer_match_level(path: Path, sheet_name: str, row: pd.Series, match_level_column: Optional[str]) -> str:
    row_level = get_row_value(row, match_level_column)

    if row_level:
        return row_level

    text = f"{path.name} {path.parent.name} {sheet_name}".lower()

    if "product" in text or "epd" in text or "declaration" in text:
        return "product"
    if "brand" in text:
        return "brand"
    if "supplier" in text:
        return "supplier"
    if "partner" in text:
        return "company"
    if "company" in text or "companies" in text:
        return "company"
    if "organization" in text or "organisation" in text:
        return "organization"
    if "certificate_rows" in text or "certificate row" in text:
        return "organization_certificate"
    if "made_in_green" in text:
        return "brand"

    return "unknown"


def evidence_level_from_match_level(match_level_raw: str, certified_product: str, certified_brand: str) -> str:
    text = clean_text(match_level_raw).casefold()

    if "product" in text or "declaration" in text:
        return "product"

    if certified_product:
        return "product"

    if "brand" in text or certified_brand:
        return "brand"

    if "supplier" in text:
        return "supplier"

    if "partner" in text:
        return "company"

    if "organization" in text or "organisation" in text or "certificate" in text:
        return "company"

    if "company" in text:
        return "company"

    return "company"


def applies_to_configurator_product_by(evidence_level: str) -> str:
    if evidence_level == "product":
        return "product_or_product_plus_company_match"

    if evidence_level in {"company", "brand", "supplier"}:
        return "company_or_brand_match"

    return "company_or_brand_match"


def filter_known_special_cases(df: pd.DataFrame, path: Path, sheet_name: str) -> pd.DataFrame:
    df = df.copy()
    path_text = str(path).lower().replace("\\", "/")
    sheet_text = sheet_name.lower()

    if "oeko" in path_text and "made" in path_text:
        has_mig_column = choose_column(df, ["has_made_in_green"])

        if has_mig_column:
            mask = df[has_mig_column].astype(str).str.strip().str.lower().isin(
                ["true", "1", "yes", "y"]
            )
            df = df[mask].copy()

    if "standard100" in path_text or "standard100" in sheet_text:
        df = df.iloc[0:0].copy()

    return df


def standardize_table(df: pd.DataFrame, path: Path, sheet_name: str) -> Tuple[pd.DataFrame, Dict[str, object]]:
    df = normalize_dataframe_columns(df)
    df = filter_known_special_cases(df, path, sheet_name)

    company_col = choose_column(df, COMPANY_COLUMN_CANDIDATES)
    brand_col = choose_column(df, BRAND_COLUMN_CANDIDATES)
    product_col = choose_column(df, PRODUCT_COLUMN_CANDIDATES)
    category_col = choose_column(df, CATEGORY_COLUMN_CANDIDATES)
    country_col = choose_column(df, COUNTRY_COLUMN_CANDIDATES)
    claim_col = choose_column(df, CLAIM_COLUMN_CANDIDATES)
    identifier_col = choose_column(df, IDENTIFIER_COLUMN_CANDIDATES)
    url_col = choose_column(df, URL_COLUMN_CANDIDATES)
    evidence_col = choose_column(df, EVIDENCE_COLUMN_CANDIDATES)
    match_level_col = choose_column(df, MATCH_LEVEL_COLUMN_CANDIDATES)

    certification_name = infer_certification_from_dataframe(df, path)
    master_rows = []

    for source_index, row in df.iterrows():
        certified_company = get_row_value(row, company_col)
        certified_brand = get_row_value(row, brand_col)
        certified_product = get_row_value(row, product_col)
        product_category = get_row_value(row, category_col)
        country_or_scope = get_row_value(row, country_col)
        certification_claim_or_standard = get_row_value(row, claim_col)
        certificate_identifier = get_row_value(row, identifier_col)
        source_url = get_row_value(row, url_col)
        evidence_text = get_row_value(row, evidence_col)

        registry_match_level_raw = infer_match_level(
            path=path,
            sheet_name=sheet_name,
            row=row,
            match_level_column=match_level_col,
        )

        evidence_level = evidence_level_from_match_level(
            match_level_raw=registry_match_level_raw,
            certified_product=certified_product,
            certified_brand=certified_brand,
        )

        certified_entity_name = ""
        certified_entity_type = ""

        if certified_company:
            certified_entity_name = certified_company
            certified_entity_type = "company"
        elif certified_brand:
            certified_entity_name = certified_brand
            certified_entity_type = "brand"
        elif certified_product:
            certified_entity_name = certified_product
            certified_entity_type = "product"

        has_matchable_value = any(
            [
                certified_company,
                certified_brand,
                certified_product,
                certificate_identifier,
                source_url,
            ]
        )

        if not has_matchable_value:
            continue

        master_record_id = make_hash_key(
            certification_name,
            evidence_level,
            certified_company,
            certified_brand,
            certified_product,
            certificate_identifier,
            source_url,
            str(path),
            sheet_name,
            source_index,
        )

        master_rows.append(
            {
                "master_record_id": master_record_id,
                "certification": certification_name,
                "certification_full_name": certification_name,
                "evidence_level": evidence_level,
                "registry_match_level_raw": registry_match_level_raw,
                "applies_to_configurator_product_by": applies_to_configurator_product_by(evidence_level),
                "certified_entity_name": certified_entity_name,
                "certified_entity_type": certified_entity_type,
                "certified_entity_name_normalized": normalize_for_matching(certified_entity_name),
                "certified_entity_name_normalized_strict": normalize_for_matching(
                    certified_entity_name,
                    remove_legal_suffixes=True,
                ),
                "certified_company": certified_company,
                "certified_company_normalized": normalize_for_matching(certified_company),
                "certified_company_normalized_strict": normalize_for_matching(
                    certified_company,
                    remove_legal_suffixes=True,
                ),
                "certified_brand": certified_brand,
                "certified_brand_normalized": normalize_for_matching(certified_brand),
                "certified_brand_normalized_strict": normalize_for_matching(
                    certified_brand,
                    remove_legal_suffixes=True,
                ),
                "certified_product": certified_product,
                "certified_product_normalized": normalize_for_matching(certified_product),
                "certified_product_normalized_strict": normalize_for_matching(
                    certified_product,
                    remove_legal_suffixes=True,
                ),
                "product_category": product_category,
                "product_category_normalized": normalize_for_matching(product_category),
                "country_or_scope": country_or_scope,
                "country_or_scope_normalized": normalize_for_matching(country_or_scope),
                "certification_claim_or_standard": certification_claim_or_standard,
                "certificate_identifier": certificate_identifier,
                "source_url": source_url,
                "source_file": str(path),
                "source_sheet": sheet_name,
                "source_row_number": int(source_index) + 2,
                "evidence_text": evidence_text,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

    standardized_df = pd.DataFrame(master_rows)

    if standardized_df.empty:
        standardized_df = pd.DataFrame(columns=MASTER_COLUMNS)

    source_info = {
        "source_file": str(path),
        "source_sheet": sheet_name,
        "source_rows": len(df),
        "standardized_rows": len(standardized_df),
        "certification_inferred": certification_name,
        "company_column": company_col or "",
        "brand_column": brand_col or "",
        "product_column": product_col or "",
        "category_column": category_col or "",
        "country_column": country_col or "",
        "claim_column": claim_col or "",
        "identifier_column": identifier_col or "",
        "url_column": url_col or "",
        "evidence_column": evidence_col or "",
        "match_level_column": match_level_col or "",
    }

    return standardized_df, source_info


def deduplicate_master(master_df: pd.DataFrame) -> pd.DataFrame:
    if master_df.empty:
        return master_df.copy()

    dedupe_columns = [
        "certification",
        "evidence_level",
        "certified_company_normalized_strict",
        "certified_brand_normalized_strict",
        "certified_product_normalized_strict",
        "certificate_identifier",
        "source_url",
    ]

    existing_dedupe_columns = [
        column for column in dedupe_columns if column in master_df.columns
    ]

    deduped_df = master_df.drop_duplicates(
        subset=existing_dedupe_columns,
        keep="first",
    ).reset_index(drop=True)

    return deduped_df


def build_summary(master_df: pd.DataFrame) -> pd.DataFrame:
    if master_df.empty:
        return pd.DataFrame(
            columns=[
                "certification",
                "evidence_level",
                "rows",
                "unique_entities",
                "unique_companies",
                "unique_brands",
                "unique_products",
                "source_files",
            ]
        )

    summary_df = (
        master_df.groupby(
            [
                "certification",
                "evidence_level",
            ],
            dropna=False,
        )
        .agg(
            rows=("master_record_id", "count"),
            unique_entities=("certified_entity_name_normalized_strict", "nunique"),
            unique_companies=("certified_company_normalized_strict", "nunique"),
            unique_brands=("certified_brand_normalized_strict", "nunique"),
            unique_products=("certified_product_normalized_strict", "nunique"),
            source_files=("source_file", lambda values: " | ".join(sorted(set(values))[:20])),
        )
        .reset_index()
    )

    return summary_df.sort_values(
        [
            "certification",
            "evidence_level",
        ]
    ).reset_index(drop=True)


def build_master_registry(certifications_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    input_files, folder_inventory = collect_input_files(certifications_dir)

    print("Building master certification registry...")
    print(f"Input directory: {certifications_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Input files selected: {len(input_files)}")
    print("")

    all_master_frames = []
    source_inventory_rows = []

    for path in input_files:
        print(f"Reading: {path}")

        try:
            tables = read_tables_from_file(path)
        except Exception as error:
            source_inventory_rows.append(
                {
                    "source_file": str(path),
                    "source_sheet": "",
                    "source_rows": 0,
                    "standardized_rows": 0,
                    "read_error": str(error),
                }
            )
            print(f"  ERROR: {error}")
            continue

        if not tables:
            source_inventory_rows.append(
                {
                    "source_file": str(path),
                    "source_sheet": "",
                    "source_rows": 0,
                    "standardized_rows": 0,
                    "read_error": "No readable tables found",
                }
            )
            print("  No readable tables found.")
            continue

        for sheet_name, df in tables:
            try:
                standardized_df, source_info = standardize_table(
                    df=df,
                    path=path,
                    sheet_name=sheet_name,
                )

                source_info["read_error"] = ""

                all_master_frames.append(standardized_df)
                source_inventory_rows.append(source_info)

                print(
                    f"  Sheet/table: {sheet_name} | "
                    f"source rows: {source_info['source_rows']} | "
                    f"standardized rows: {source_info['standardized_rows']} | "
                    f"certification: {source_info['certification_inferred']}"
                )

            except Exception as error:
                source_inventory_rows.append(
                    {
                        "source_file": str(path),
                        "source_sheet": sheet_name,
                        "source_rows": len(df),
                        "standardized_rows": 0,
                        "read_error": str(error),
                    }
                )
                print(f"  ERROR in sheet/table {sheet_name}: {error}")

    if all_master_frames:
        master_df = pd.concat(all_master_frames, ignore_index=True)
    else:
        master_df = pd.DataFrame(columns=MASTER_COLUMNS)

    for column in MASTER_COLUMNS:
        if column not in master_df.columns:
            master_df[column] = ""

    master_df = master_df[MASTER_COLUMNS].copy()

    before_dedupe = len(master_df)
    master_df = deduplicate_master(master_df)
    after_dedupe = len(master_df)

    if not master_df.empty:
        master_df = master_df.sort_values(
            [
                "certification",
                "evidence_level",
                "certified_entity_name_normalized_strict",
                "certified_product_normalized_strict",
            ]
        ).reset_index(drop=True)

    summary_df = build_summary(master_df)
    source_inventory_df = pd.DataFrame(source_inventory_rows)
    folder_inventory_df = pd.DataFrame(folder_inventory)

    master_df = sanitize_dataframe_for_excel(master_df)
    summary_df = sanitize_dataframe_for_excel(summary_df)
    source_inventory_df = sanitize_dataframe_for_excel(source_inventory_df)
    folder_inventory_df = sanitize_dataframe_for_excel(folder_inventory_df)

    master_csv = output_dir / "master_certification_registry.csv"
    summary_csv = output_dir / "master_certification_registry_summary.csv"
    sources_csv = output_dir / "master_certification_registry_sources.csv"
    folders_csv = output_dir / "master_certification_registry_folder_inventory.csv"
    excel_path = output_dir / "master_certification_registry.xlsx"

    master_df.to_csv(master_csv, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_csv, index=False, encoding="utf-8-sig")
    source_inventory_df.to_csv(sources_csv, index=False, encoding="utf-8-sig")
    folder_inventory_df.to_csv(folders_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        master_df.to_excel(writer, sheet_name="master_registry", index=False)
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        source_inventory_df.to_excel(writer, sheet_name="sources", index=False)
        folder_inventory_df.to_excel(writer, sheet_name="folder_inventory", index=False)

    print("")
    print("Master registry built.")
    print(f"Rows before dedupe: {before_dedupe}")
    print(f"Rows after dedupe: {after_dedupe}")
    print("")
    print("Saved files:")
    print(f"- {master_csv}")
    print(f"- {summary_csv}")
    print(f"- {sources_csv}")
    print(f"- {folders_csv}")
    print(f"- {excel_path}")

    missing_folders = folder_inventory_df[
        folder_inventory_df["selection_reason"].astype(str).eq("missing_folder")
    ]

    incomplete_folders = folder_inventory_df[
        folder_inventory_df["files_selected"].astype(str).eq("0")
        & ~folder_inventory_df["selection_reason"].astype(str).eq("missing_folder")
    ]

    if len(missing_folders) > 0:
        print("")
        print("Missing certification folders skipped:")
        for _, row in missing_folders.iterrows():
            print(f"- {row.get('expected_certification', '')}: {row.get('expected_folder', '')}")

    if len(incomplete_folders) > 0:
        print("")
        print("Existing folders with no selected registry files:")
        for _, row in incomplete_folders.iterrows():
            print(f"- {row.get('expected_certification', '')}: {row.get('actual_folder', '')} ({row.get('selection_reason', '')})")

    if summary_df.empty:
        print("")
        print("WARNING: summary is empty. No master rows were created.")
    else:
        print("")
        print("Summary preview:")
        print(summary_df.to_string(index=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a unified master registry from all local certification registry datasets."
        )
    )

    parser.add_argument(
        "--certifications-dir",
        default=str(DEFAULT_CERTIFICATIONS_DIR),
        help=f"Input certifications directory. Default: {DEFAULT_CERTIFICATIONS_DIR}",
    )

    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    certifications_dir = Path(args.certifications_dir)
    output_dir = Path(args.output_dir)

    build_master_registry(
        certifications_dir=certifications_dir,
        output_dir=output_dir,
    )


if __name__ == "__main__":
    main()