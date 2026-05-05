from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


DEFAULT_CERTIFICATIONS_FILE = "Certificazioni_da_verificare.xlsx"
DEFAULT_JSON_OUTPUT = "certification_registry_map.json"
DEFAULT_EXCEL_OUTPUT = "certification_registry_map.xlsx"


@dataclass
class RegistrySource:
    certification: str
    description: str
    canonical_key: str
    registry_type: str
    official_source_name: str
    official_source_url: str
    public_registry_availability: str
    automated_strategy: str
    primary_match_target: str
    secondary_match_target: str
    expected_confidence: str
    notes: str


def normalize_text(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("\t", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_key(value: object) -> str:
    text = normalize_text(value).lower()

    replacements = {
        "®": "",
        "™": "",
        "(": " ",
        ")": " ",
        "&": " and ",
        "-": " ",
        "/": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def read_certifications(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Certification file not found: {path}")

    df = pd.read_excel(path, header=None)

    if df.shape[1] < 1:
        raise ValueError("The certification file appears to have no columns.")

    df = df.rename(columns={0: "Certification", 1: "Description"})

    if "Description" not in df.columns:
        df["Description"] = ""

    df["Certification"] = df["Certification"].apply(normalize_text)
    df["Description"] = df["Description"].apply(normalize_text)

    df = df[df["Certification"].str.len() > 0].copy()
    df = df.reset_index(drop=True)

    return df


def classify_certification(certification_name: str, description: str) -> RegistrySource:
    key = normalize_key(certification_name)

    if "blue angel" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="blue_angel",
            registry_type="official_product_catalogue",
            official_source_name="Blue Angel products and services",
            official_source_url="https://www.blauer-engel.de/en/products",
            public_registry_availability="HIGH",
            automated_strategy="registry_search_then_company_product_fuzzy_match",
            primary_match_target="product_or_service_name",
            secondary_match_target="company_name",
            expected_confidence="VERIFIED if product/company match is found in official catalogue; LIKELY if only company/product family matches",
            notes="Official catalogue lists certified products/services and companies. Good candidate for registry-first verification.",
        )

    if "bluesign" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="bluesign",
            registry_type="official_brand_product_directory",
            official_source_name="bluesign sustainable brands and products",
            official_source_url="https://www.bluesign.com/find-sustainable-brands",
            public_registry_availability="MEDIUM",
            automated_strategy="official_directory_search_then_company_product_fuzzy_match",
            primary_match_target="brand_or_company_name",
            secondary_match_target="product_or_category",
            expected_confidence="LIKELY if brand/company is listed; VERIFIED only if product-level evidence is found",
            notes="bluesign has consumer-facing brand/product information. Product-level coverage may vary; fallback website evidence may be needed.",
        )

    if "cradle to cradle" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="cradle_to_cradle_certified",
            registry_type="official_product_registry",
            official_source_name="Cradle to Cradle Certified products registry",
            official_source_url="https://c2ccertified.org/certified-products",
            public_registry_availability="HIGH",
            automated_strategy="registry_search_then_product_company_fuzzy_match",
            primary_match_target="product_name",
            secondary_match_target="company_name",
            expected_confidence="VERIFIED if product/company appears in official registry",
            notes="Strong registry-first candidate because the official site exposes a certified products registry.",
        )

    if "eu ecolabel" in key or "european ecolabel" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="eu_ecolabel",
            registry_type="official_product_catalogue",
            official_source_name="EU Ecolabel Product Catalogue",
            official_source_url="https://environment.ec.europa.eu/app/ecolabel-product-catalogue",
            public_registry_availability="HIGH",
            automated_strategy="registry_catalogue_or_dataset_search_then_company_product_fuzzy_match",
            primary_match_target="product_name",
            secondary_match_target="company_or_licence_holder",
            expected_confidence="VERIFIED if product/company/licence appears in EU catalogue",
            notes="EU catalogue may also expose downloadable/API data. Strong candidate for structured enrichment.",
        )

    if "ewg verified" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="ewg_verified",
            registry_type="official_product_database",
            official_source_name="EWG VERIFIED products",
            official_source_url="https://www.ewg.org/ewgverified/products.php",
            public_registry_availability="HIGH",
            automated_strategy="registry_search_then_brand_product_fuzzy_match",
            primary_match_target="product_name",
            secondary_match_target="brand_or_company_name",
            expected_confidence="VERIFIED if product appears in EWG VERIFIED product list",
            notes="Mostly relevant for cosmetics, personal care, cleaning and consumer health products.",
        )

    if "fair for life" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="fair_for_life",
            registry_type="official_certified_partners_directory",
            official_source_name="Fair for Life certified partners",
            official_source_url="https://www.fairforlife.org/en/our-partners/certified-partners/",
            public_registry_availability="MEDIUM",
            automated_strategy="partner_directory_search_then_company_fuzzy_match",
            primary_match_target="company_or_operator_name",
            secondary_match_target="product_category",
            expected_confidence="LIKELY if company/operator appears; VERIFIED only with product-specific evidence",
            notes="Directory is partner/operator-oriented rather than always product-level.",
        )

    if "fair rubber" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="fair_rubber",
            registry_type="official_members_directory",
            official_source_name="Fair Rubber members",
            official_source_url="https://fairrubber.org/members/",
            public_registry_availability="LOW_MEDIUM",
            automated_strategy="members_directory_search_then_company_fuzzy_match_plus_fallback_site_evidence",
            primary_match_target="company_or_member_name",
            secondary_match_target="rubber_product_evidence",
            expected_confidence="POSSIBLE or LIKELY unless product-specific evidence is found",
            notes="Official members page is useful, but it may not prove product-level certification by itself.",
        )

    if "global organic textile standard" in key or key == "gots":
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="gots",
            registry_type="official_certified_suppliers_database",
            official_source_name="GOTS Certified Suppliers Database",
            official_source_url="https://global-standard.org/de/oeffentliche-datenbanken/certifiedsuppliers",
            public_registry_availability="MEDIUM_HIGH",
            automated_strategy="supplier_database_search_then_company_product_group_fuzzy_match",
            primary_match_target="certified_entity_or_supplier_name",
            secondary_match_target="product_group",
            expected_confidence="LIKELY if company/supplier appears; VERIFIED if product group/entity evidence is strong",
            notes="GOTS database is supply-chain/entity oriented. Product retail names may not match directly.",
        )

    if "global recycled standard" in key or key == "grs":
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="global_recycled_standard",
            registry_type="textile_exchange_certified_company_database",
            official_source_name="Textile Exchange Find a Certified Company",
            official_source_url="https://textileexchange.org/find-certified-company/",
            public_registry_availability="MEDIUM_HIGH",
            automated_strategy="certified_company_database_search_filtered_by_standard_then_company_product_group_fuzzy_match",
            primary_match_target="certified_company_name",
            secondary_match_target="standard_scope_material_or_product_category",
            expected_confidence="LIKELY if company/scope appears; VERIFIED only with product-level or scope-certificate evidence",
            notes="Textile Exchange database is company/scope-certificate oriented, not always final product retail-name oriented.",
        )

    if "recycled claim standard" in key or "rcs blended" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="recycled_claim_standard_blended",
            registry_type="textile_exchange_certified_company_database",
            official_source_name="Textile Exchange Find a Certified Company",
            official_source_url="https://textileexchange.org/find-certified-company/",
            public_registry_availability="MEDIUM_HIGH",
            automated_strategy="certified_company_database_search_filtered_by_standard_then_company_product_group_fuzzy_match",
            primary_match_target="certified_company_name",
            secondary_match_target="standard_scope_material_or_product_category",
            expected_confidence="LIKELY if company/scope appears; VERIFIED only with product-level or scope-certificate evidence",
            notes="RCS is handled through Textile Exchange company/scope data. Product-level verification may require additional evidence.",
        )

    if "organic content standard" in key or "ocs blended" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="organic_content_standard_blended",
            registry_type="textile_exchange_certified_company_database",
            official_source_name="Textile Exchange Find a Certified Company",
            official_source_url="https://textileexchange.org/find-certified-company/",
            public_registry_availability="MEDIUM_HIGH",
            automated_strategy="certified_company_database_search_filtered_by_standard_then_company_product_group_fuzzy_match",
            primary_match_target="certified_company_name",
            secondary_match_target="standard_scope_material_or_product_category",
            expected_confidence="LIKELY if company/scope appears; VERIFIED only with product-level or scope-certificate evidence",
            notes="OCS is company/scope-certificate oriented. Product-level claims need caution.",
        )

    if "plant based fiber" in key or "plant based fibre" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="plant_based_fiber_blended",
            registry_type="amazon_climate_pledge_friendly_program_attribute",
            official_source_name="Amazon Climate Pledge Friendly certification information",
            official_source_url="https://www.amazon.it/b?ie=UTF8&node=22423405031",
            public_registry_availability="LOW",
            automated_strategy="not_checkable_by_public_registry_use_amazon_or_company_site_evidence",
            primary_match_target="amazon_product_or_asin",
            secondary_match_target="company_site_claim",
            expected_confidence="POSSIBLE unless Amazon product evidence is found",
            notes="This appears to be an Amazon Climate Pledge Friendly-related attribute rather than a broad independent public registry.",
        )

    if "oeko tex standard 100" in key or "standard 100" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="oeko_tex_standard_100",
            registry_type="official_label_check",
            official_source_name="OEKO-TEX Label Check",
            official_source_url="https://www.oeko-tex.com/en/label-check/",
            public_registry_availability="MEDIUM",
            automated_strategy="label_number_check_if_available_otherwise_company_site_evidence",
            primary_match_target="certificate_or_label_number",
            secondary_match_target="company_product_text_evidence",
            expected_confidence="VERIFIED if label number is checked; POSSIBLE/LIKELY if only website evidence exists",
            notes="OEKO-TEX Label Check is strongest when a certificate or label number is available.",
        )

    if "oeko tex made in green" in key or "made in green" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="oeko_tex_made_in_green",
            registry_type="official_label_check",
            official_source_name="OEKO-TEX Label Check",
            official_source_url="https://www.oeko-tex.com/en/label-check/",
            public_registry_availability="MEDIUM",
            automated_strategy="label_number_check_if_available_otherwise_company_site_evidence",
            primary_match_target="certificate_or_label_number",
            secondary_match_target="company_product_text_evidence",
            expected_confidence="VERIFIED if label number is checked; POSSIBLE/LIKELY if only website evidence exists",
            notes="MADE IN GREEN is traceable through OEKO-TEX label information when product ID/label number is available.",
        )

    if "altro tipo" in key or "other certification" in key:
        return RegistrySource(
            certification=certification_name,
            description=description,
            canonical_key="other_certification",
            registry_type="fallback_detection",
            official_source_name="Company/configurator website and recognized certification keywords",
            official_source_url="",
            public_registry_availability="VARIABLE",
            automated_strategy="fallback_site_crawl_detect_known_certification_keywords",
            primary_match_target="certification_keyword",
            secondary_match_target="company_product_context",
            expected_confidence="POSSIBLE unless source page provides strong product-specific evidence",
            notes="Used to capture certifications not included in the initial list, such as FSC, PEFC, ISO 14001, GREENGUARD, B Corp, etc.",
        )

    return RegistrySource(
        certification=certification_name,
        description=description,
        canonical_key="unmapped",
        registry_type="manual_review_required",
        official_source_name="",
        official_source_url="",
        public_registry_availability="UNKNOWN",
        automated_strategy="manual_mapping_required_before_automation",
        primary_match_target="",
        secondary_match_target="",
        expected_confidence="NOT_CHECKABLE until mapped",
        notes="This certification was not recognized by the current mapping rules and should be reviewed manually.",
    )


def build_registry_map(certifications_df: pd.DataFrame) -> List[RegistrySource]:
    registry_map: List[RegistrySource] = []

    for _, row in certifications_df.iterrows():
        certification = normalize_text(row["Certification"])
        description = normalize_text(row.get("Description", ""))

        registry_map.append(
            classify_certification(
                certification_name=certification,
                description=description,
            )
        )

    return registry_map


def export_registry_map(
    registry_map: List[RegistrySource],
    json_output_path: Path,
    excel_output_path: Path,
) -> None:
    rows = [asdict(item) for item in registry_map]

    json_output_path.write_text(
        json.dumps(rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    df = pd.DataFrame(rows)
    df.to_excel(excel_output_path, index=False)


def print_summary(registry_map: List[RegistrySource]) -> None:
    print("\nCertification registry map created.")
    print(f"Certifications mapped: {len(registry_map)}")

    by_availability: Dict[str, int] = {}

    for item in registry_map:
        by_availability[item.public_registry_availability] = (
            by_availability.get(item.public_registry_availability, 0) + 1
        )

    print("\nPublic registry availability:")
    for availability, count in sorted(by_availability.items()):
        print(f"- {availability}: {count}")

    print("\nMapped certifications:")
    for item in registry_map:
        print(
            f"- {item.certification} | "
            f"{item.registry_type} | "
            f"{item.public_registry_availability}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a registry-source map for sustainability certifications."
    )

    parser.add_argument(
        "--certifications",
        default=DEFAULT_CERTIFICATIONS_FILE,
        help=f"Input certification Excel file. Default: {DEFAULT_CERTIFICATIONS_FILE}",
    )

    parser.add_argument(
        "--json-output",
        default=DEFAULT_JSON_OUTPUT,
        help=f"Output JSON registry map. Default: {DEFAULT_JSON_OUTPUT}",
    )

    parser.add_argument(
        "--excel-output",
        default=DEFAULT_EXCEL_OUTPUT,
        help=f"Output Excel registry map. Default: {DEFAULT_EXCEL_OUTPUT}",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    certifications_path = Path(args.certifications)
    json_output_path = Path(args.json_output)
    excel_output_path = Path(args.excel_output)

    certifications_df = read_certifications(certifications_path)
    registry_map = build_registry_map(certifications_df)

    export_registry_map(
        registry_map=registry_map,
        json_output_path=json_output_path,
        excel_output_path=excel_output_path,
    )

    print_summary(registry_map)
    print(f"\nJSON saved to: {json_output_path}")
    print(f"Excel saved to: {excel_output_path}")


if __name__ == "__main__":
    main()