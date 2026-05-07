import argparse
import hashlib
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd

try:
    from rapidfuzz import fuzz, process

    RAPIDFUZZ_AVAILABLE = True
except Exception:
    from difflib import SequenceMatcher

    RAPIDFUZZ_AVAILABLE = False


DEFAULT_CONFIGURATOR_DATASET = Path("Dataset_Enhanced_LEME_Paolo_Rubino.xlsx")
DEFAULT_MASTER_REGISTRY_CSV = (
    Path("data")
    / "certifications"
    / "master_registry"
    / "master_certification_registry.csv"
)
DEFAULT_MASTER_REGISTRY_XLSX = (
    Path("data")
    / "certifications"
    / "master_registry"
    / "master_certification_registry.xlsx"
)
DEFAULT_OUTPUT_DIR = Path("data") / "certifications" / "matching_v2"

EXCEL_ILLEGAL_CHARACTERS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


CONFIGURATOR_COLUMN_CANDIDATES = {
    "industry": ["Industry", "industry"],
    "country": ["Country", "country"],
    "company": ["Company", "company", "azienda"],
    "product": ["Product", "product", "prodotto"],
    "configurator_url": [
        "Configurator URL",
        "configurator_url",
        "ConfiguratorURL",
        "url",
    ],
    "alternative_url": [
        "Configurator URL alternativa",
        "Configurator URL alternativa ",
        "alternative_url",
        "Configurator URL alternative",
    ],
    "database_detail_url": [
        "Database detail URL",
        "database_detail_url",
        "detail_url",
    ],
}


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


GENERIC_REGISTRY_DOMAINS = [
    "bcorporation.net",
    "www.bcorporation.net",
    "environdec.com",
    "www.environdec.com",
    "greencirclecertified.com",
    "db.greencirclecertified.com",
    "petaapprovedvegan.peta.org",
    "peta.org",
    "www.blauer-engel.de",
    "blauer-engel.de",
    "c2ccertified.org",
    "www.c2ccertified.org",
    "environmental-data.ec.europa.eu",
    "ec.europa.eu",
    "ewg.org",
    "www.ewg.org",
    "fairforlife.org",
    "www.fairforlife.org",
    "global-standard.org",
    "www.global-standard.org",
    "app.powerbi.com",
    "powerbi.com",
    "oeko-tex.com",
    "www.oeko-tex.com",
]


SUPPLIER_ORIENTED_CERTIFICATIONS = {
    "fsc",
    "forest stewardship council",
    "global organic textile standard",
    "gots",
    "global recycled standard",
    "grs",
    "bluesign",
    "fair for life",
}


DIRECT_ORIENTED_CERTIFICATIONS = {
    "b corp",
    "certified b corporation",
    "peta approved vegan",
    "peta-approved vegan",
    "blue angel",
    "cradle to cradle certified",
    "eu ecolabel",
    "ewg verified",
    "greencircle certified",
    "greencircle",
    "environmental product declaration",
    "epd",
    "oeko tex made in green",
    "oeko-tex made in green",
}


AUDIT_COLUMNS = [
    "configurator_row_number",
    "configurator_id",
    "configurator_company",
    "configurator_product",
    "configurator_industry",
    "configurator_country",
    "configurator_domains",
    "certification",
    "registry_usage_mode",
    "decision",
    "site_claim_type",
    "confidence",
    "final_score",
    "match_method",
    "matched_evidence_level",
    "matched_registry_entity",
    "matched_registry_company",
    "matched_registry_brand",
    "matched_registry_product",
    "matched_product_category",
    "matched_country_or_scope",
    "company_score",
    "product_score",
    "domain_score",
    "entity_exact_match",
    "product_exact_match",
    "master_record_id",
    "certificate_identifier",
    "source_file",
    "source_sheet",
    "source_row_number",
    "source_url",
    "evidence_text",
    "review_reason",
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


def truncate_for_excel(value: object, max_length: int = 2800) -> str:
    text = clean_text(value)

    if len(text) <= max_length:
        return text

    return text[:max_length] + " [...]"


def sanitize_dataframe_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    sanitized_df = df.copy()

    for column in sanitized_df.columns:
        if sanitized_df[column].dtype == "object":
            sanitized_df[column] = sanitized_df[column].apply(truncate_for_excel)

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
            suffix_normalized = normalize_for_matching(
                suffix,
                remove_legal_suffixes=False,
            )
            for token in suffix_normalized.split():
                suffixes.add(token)

        tokens = text.split()
        filtered_tokens = [token for token in tokens if token not in suffixes]

        text = " ".join(filtered_tokens)
        text = re.sub(r"\s+", " ", text).strip()

    return text


def make_hash_key(*values: object) -> str:
    raw_key = "|".join(clean_text(value) for value in values)
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def choose_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    lookup = {}

    for column in df.columns:
        normalized = normalize_column_name(column)

        if normalized and normalized not in lookup:
            lookup[normalized] = column

    for candidate in candidates:
        normalized_candidate = normalize_column_name(candidate)

        if normalized_candidate in lookup:
            return lookup[normalized_candidate]

    for candidate in candidates:
        normalized_candidate = normalize_column_name(candidate)

        for normalized_column, original_column in lookup.items():
            if normalized_candidate and normalized_candidate in normalized_column:
                return original_column

    return None


def get_row_value(row: pd.Series, column: Optional[str]) -> str:
    if not column:
        return ""

    if column not in row:
        return ""

    return clean_text(row[column])


def find_configurator_dataset(default_path: Path) -> Path:
    if default_path.exists():
        return default_path

    candidates = sorted(Path(".").glob("*Dataset*Enhanced*LEME*Paolo*Rubino*.xlsx"))

    if candidates:
        return candidates[0]

    candidates = sorted(Path(".").glob("*.xlsx"))

    for candidate in candidates:
        if "Dataset" in candidate.name:
            return candidate

    raise FileNotFoundError(
        "Configurator dataset not found. Pass --configurator-dataset explicitly."
    )


def read_configurator_dataset(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, dtype=str)
    df.columns = [clean_text(column) for column in df.columns]
    return df


def read_master_registry(csv_path: Path, xlsx_path: Path) -> pd.DataFrame:
    if csv_path.exists():
        return pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig").fillna("")

    if xlsx_path.exists():
        return pd.read_excel(
            xlsx_path,
            sheet_name="master_registry",
            dtype=str,
        ).fillna("")

    raise FileNotFoundError(
        "Master certification registry not found. Run build_master_certification_registry.py first."
    )


def safe_url_for_parsing(url: str) -> str:
    url = clean_text(url)

    if not url:
        return ""

    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        return "https://" + url

    return url


def extract_domain(url: str) -> str:
    url = clean_text(url)

    if not url:
        return ""

    try:
        parsed = urlparse(safe_url_for_parsing(url))
        domain = clean_text(parsed.netloc).casefold()
    except Exception:
        domain = ""

    domain = re.sub(r"^www\.", "", domain, flags=re.IGNORECASE)
    domain = domain.split(":")[0]

    return domain


def is_generic_registry_domain(domain: str) -> bool:
    domain = clean_text(domain).casefold()
    domain = re.sub(r"^www\.", "", domain)

    if not domain:
        return True

    for generic_domain in GENERIC_REGISTRY_DOMAINS:
        generic_domain = generic_domain.casefold()
        generic_domain = re.sub(r"^www\.", "", generic_domain)

        if domain == generic_domain or domain.endswith("." + generic_domain):
            return True

    return False


def get_configurator_domains(row: pd.Series, columns: Dict[str, Optional[str]]) -> List[str]:
    urls = [
        get_row_value(row, columns.get("configurator_url")),
        get_row_value(row, columns.get("alternative_url")),
        get_row_value(row, columns.get("database_detail_url")),
    ]

    domains = []

    for url in urls:
        domain = extract_domain(url)

        if domain and domain not in domains:
            domains.append(domain)

    return domains


def fuzzy_score(left: str, right: str) -> float:
    left = clean_text(left)
    right = clean_text(right)

    if not left or not right:
        return 0.0

    if left == right:
        return 100.0

    if RAPIDFUZZ_AVAILABLE:
        return float(
            max(
                fuzz.token_set_ratio(left, right),
                fuzz.token_sort_ratio(left, right),
                fuzz.partial_ratio(left, right),
                fuzz.WRatio(left, right),
            )
        )

    return float(SequenceMatcher(None, left, right).ratio() * 100)


def fuzzy_extract(
    query: str,
    choices: List[str],
    limit: int,
    score_cutoff: float,
) -> List[Tuple[str, float]]:
    query = clean_text(query)

    if not query or not choices:
        return []

    if RAPIDFUZZ_AVAILABLE:
        results = process.extract(
            query,
            choices,
            scorer=fuzz.token_set_ratio,
            limit=limit,
            score_cutoff=score_cutoff,
        )

        return [(str(choice), float(score)) for choice, score, _ in results]

    scored = []

    for choice in choices:
        score = fuzzy_score(query, choice)

        if score >= score_cutoff:
            scored.append((choice, score))

    scored.sort(key=lambda item: item[1], reverse=True)

    return scored[:limit]


def is_short_or_ambiguous_name(name: str) -> bool:
    normalized = normalize_for_matching(name, remove_legal_suffixes=True)
    tokens = normalized.split()

    if not normalized:
        return True

    if len(normalized) <= 3:
        return True

    if len(tokens) == 1 and len(normalized) <= 5:
        return True

    return False


def decision_priority(decision: str) -> int:
    decision = clean_text(decision)

    if decision == "Direct Yes":
        return 5

    if decision == "Direct Review":
        return 4

    if decision == "Supplier Candidate":
        return 3

    if decision == "No":
        return 1

    return 0


def confidence_priority(confidence: str) -> int:
    confidence = clean_text(confidence)

    if confidence == "High":
        return 3

    if confidence == "Medium":
        return 2

    if confidence == "Low":
        return 1

    return 0


def normalize_certification_key(certification: str) -> str:
    return normalize_for_matching(certification, remove_legal_suffixes=True)


def get_registry_usage_mode(certification: str, evidence_level: str) -> str:
    certification_key = normalize_certification_key(certification)
    evidence_level_key = normalize_for_matching(evidence_level)

    if certification_key in {
        normalize_certification_key(value)
        for value in SUPPLIER_ORIENTED_CERTIFICATIONS
    }:
        return "supplier_oriented_registry"

    if certification_key in {
        normalize_certification_key(value)
        for value in DIRECT_ORIENTED_CERTIFICATIONS
    }:
        return "direct_registry"

    if evidence_level_key in {"supplier", "organization", "organization certificate"}:
        return "supplier_oriented_registry"

    return "direct_registry"


def build_configurator_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    columns = {}

    for canonical_name, candidates in CONFIGURATOR_COLUMN_CANDIDATES.items():
        columns[canonical_name] = choose_column(df, candidates)

    if not columns.get("company"):
        raise ValueError("Could not identify Company column in configurator dataset.")

    if not columns.get("product"):
        raise ValueError("Could not identify Product column in configurator dataset.")

    return columns


def prepare_configurator_records(df: pd.DataFrame) -> pd.DataFrame:
    columns = build_configurator_columns(df)
    records = []

    for index, row in df.iterrows():
        company = get_row_value(row, columns.get("company"))
        product = get_row_value(row, columns.get("product"))
        industry = get_row_value(row, columns.get("industry"))
        country = get_row_value(row, columns.get("country"))
        configurator_url = get_row_value(row, columns.get("configurator_url"))
        alternative_url = get_row_value(row, columns.get("alternative_url"))
        database_detail_url = get_row_value(row, columns.get("database_detail_url"))

        domains = get_configurator_domains(row, columns)

        records.append(
            {
                "configurator_row_number": index + 2,
                "configurator_index": index,
                "configurator_id": index + 1,
                "company": company,
                "company_normalized": normalize_for_matching(company),
                "company_normalized_strict": normalize_for_matching(
                    company,
                    remove_legal_suffixes=True,
                ),
                "product": product,
                "product_normalized": normalize_for_matching(product),
                "product_normalized_strict": normalize_for_matching(
                    product,
                    remove_legal_suffixes=True,
                ),
                "industry": industry,
                "country": country,
                "configurator_url": configurator_url,
                "alternative_url": alternative_url,
                "database_detail_url": database_detail_url,
                "domains": domains,
                "domains_joined": " | ".join(domains),
            }
        )

    return pd.DataFrame(records)


def prepare_master_registry(master_df: pd.DataFrame) -> pd.DataFrame:
    master_df = master_df.fillna("").copy()

    required_columns = [
        "master_record_id",
        "certification",
        "evidence_level",
        "registry_match_level_raw",
        "certified_entity_name",
        "certified_entity_type",
        "certified_entity_name_normalized_strict",
        "certified_company",
        "certified_company_normalized_strict",
        "certified_brand",
        "certified_brand_normalized_strict",
        "certified_product",
        "certified_product_normalized_strict",
        "product_category",
        "country_or_scope",
        "certification_claim_or_standard",
        "certificate_identifier",
        "source_url",
        "source_file",
        "source_sheet",
        "source_row_number",
        "evidence_text",
    ]

    for column in required_columns:
        if column not in master_df.columns:
            master_df[column] = ""

    master_df["certification"] = master_df["certification"].apply(clean_text)
    master_df["evidence_level"] = master_df["evidence_level"].apply(clean_text)

    for column in [
        "certified_entity_name",
        "certified_company",
        "certified_brand",
        "certified_product",
        "product_category",
        "country_or_scope",
        "source_url",
    ]:
        master_df[column] = master_df[column].apply(clean_text)

    master_df["registry_domain"] = master_df["source_url"].apply(extract_domain)
    master_df["registry_domain_is_matchable"] = master_df["registry_domain"].apply(
        lambda domain: bool(domain) and not is_generic_registry_domain(domain)
    )

    master_df["candidate_entity_for_matching"] = master_df.apply(
        lambda row: clean_text(
            row.get("certified_company", "")
            or row.get("certified_brand", "")
            or row.get("certified_entity_name", "")
        ),
        axis=1,
    )

    master_df["candidate_entity_for_matching_strict"] = master_df[
        "candidate_entity_for_matching"
    ].apply(lambda value: normalize_for_matching(value, remove_legal_suffixes=True))

    master_df["candidate_product_for_matching_strict"] = master_df[
        "certified_product"
    ].apply(lambda value: normalize_for_matching(value, remove_legal_suffixes=True))

    master_df["registry_usage_mode"] = master_df.apply(
        lambda row: get_registry_usage_mode(
            certification=row.get("certification", ""),
            evidence_level=row.get("evidence_level", ""),
        ),
        axis=1,
    )

    return master_df


def build_certification_index(cert_df: pd.DataFrame) -> Dict[str, object]:
    entity_to_indices: Dict[str, List[int]] = {}
    product_to_indices: Dict[str, List[int]] = {}
    domain_to_indices: Dict[str, List[int]] = {}

    for index, row in cert_df.iterrows():
        entity_key = clean_text(row.get("candidate_entity_for_matching_strict", ""))
        product_key = clean_text(row.get("candidate_product_for_matching_strict", ""))
        domain = clean_text(row.get("registry_domain", ""))

        if entity_key:
            entity_to_indices.setdefault(entity_key, []).append(index)

        if product_key:
            product_to_indices.setdefault(product_key, []).append(index)

        if domain and bool(row.get("registry_domain_is_matchable", False)):
            domain_to_indices.setdefault(domain, []).append(index)

    return {
        "entity_to_indices": entity_to_indices,
        "product_to_indices": product_to_indices,
        "domain_to_indices": domain_to_indices,
        "entity_choices": sorted(entity_to_indices.keys()),
        "product_choices": sorted(product_to_indices.keys()),
    }


def calculate_candidate_scores(
    config_record: pd.Series,
    registry_row: pd.Series,
) -> Dict[str, object]:
    config_company = clean_text(config_record["company"])
    config_product = clean_text(config_record["product"])

    config_company_strict = clean_text(config_record["company_normalized_strict"])
    config_product_strict = clean_text(config_record["product_normalized_strict"])

    registry_entity = clean_text(registry_row.get("candidate_entity_for_matching", ""))
    registry_entity_strict = clean_text(
        registry_row.get("candidate_entity_for_matching_strict", "")
    )

    registry_product = clean_text(registry_row.get("certified_product", ""))
    registry_product_strict = clean_text(
        registry_row.get("candidate_product_for_matching_strict", "")
    )

    entity_exact_match = (
        bool(config_company_strict)
        and bool(registry_entity_strict)
        and config_company_strict == registry_entity_strict
    )

    product_exact_match = (
        bool(config_product_strict)
        and bool(registry_product_strict)
        and config_product_strict == registry_product_strict
    )

    company_score = fuzzy_score(config_company_strict, registry_entity_strict)
    product_score = fuzzy_score(config_product_strict, registry_product_strict)

    config_domains = config_record["domains"]
    registry_domain = clean_text(registry_row.get("registry_domain", ""))
    registry_domain_matchable = bool(registry_row.get("registry_domain_is_matchable", False))

    domain_score = 0.0

    if registry_domain_matchable and registry_domain and registry_domain in config_domains:
        domain_score = 100.0

    return {
        "company_score": round(company_score, 2),
        "product_score": round(product_score, 2),
        "domain_score": round(domain_score, 2),
        "entity_exact_match": entity_exact_match,
        "product_exact_match": product_exact_match,
        "registry_entity": registry_entity,
        "registry_product": registry_product,
        "short_or_ambiguous_config_company": is_short_or_ambiguous_name(config_company),
        "short_or_ambiguous_registry_entity": is_short_or_ambiguous_name(registry_entity),
    }


def decide_direct_registry_match(
    registry_row: pd.Series,
    scores: Dict[str, object],
    match_method_hint: str,
) -> Dict[str, object]:
    evidence_level = clean_text(registry_row.get("evidence_level", "")).casefold()

    company_score = float(scores["company_score"])
    product_score = float(scores["product_score"])
    domain_score = float(scores["domain_score"])
    entity_exact_match = bool(scores["entity_exact_match"])
    product_exact_match = bool(scores["product_exact_match"])

    short_name = bool(scores["short_or_ambiguous_config_company"]) or bool(
        scores["short_or_ambiguous_registry_entity"]
    )

    registry_product = clean_text(registry_row.get("certified_product", ""))

    decision = "No"
    site_claim_type = "none"
    confidence = ""
    final_score = 0.0
    match_method = match_method_hint
    review_reason = ""

    if evidence_level == "product":
        if domain_score == 100 and product_exact_match:
            decision = "Direct Yes"
            site_claim_type = "product_certified"
            confidence = "High"
            final_score = 100.0
            match_method = "domain_and_product_exact"
        elif entity_exact_match and product_exact_match:
            decision = "Direct Yes"
            site_claim_type = "product_certified"
            confidence = "High"
            final_score = 98.0
            match_method = "company_exact_and_product_exact"
        elif company_score >= 95 and product_score >= 85:
            decision = "Direct Yes"
            site_claim_type = "product_certified"
            confidence = "High"
            final_score = round((company_score * 0.55) + (product_score * 0.45), 2)
            match_method = "company_high_fuzzy_and_product_high_fuzzy"
        elif company_score >= 90 and product_score >= 75:
            decision = "Direct Yes"
            site_claim_type = "product_certified"
            confidence = "Medium"
            final_score = round((company_score * 0.55) + (product_score * 0.45), 2)
            match_method = "company_medium_fuzzy_and_product_medium_fuzzy"
        elif company_score >= 95 and registry_product:
            decision = "Direct Review"
            site_claim_type = "possible_product_certification"
            confidence = "Medium"
            final_score = round((company_score * 0.65) + (product_score * 0.35), 2)
            match_method = "company_high_but_product_uncertain"
            review_reason = (
                "Registry is product-level. Company is strong, but product name is not strong enough."
            )
        elif product_score >= 90 and company_score >= 75:
            decision = "Direct Review"
            site_claim_type = "possible_product_certification"
            confidence = "Medium"
            final_score = round((company_score * 0.45) + (product_score * 0.55), 2)
            match_method = "product_high_but_company_uncertain"
            review_reason = (
                "Product looks similar, but company/entity match is not strong enough."
            )

    else:
        if domain_score == 100:
            decision = "Direct Yes"
            site_claim_type = "company_or_brand_certified"
            confidence = "High"
            final_score = 100.0
            match_method = "domain_exact"
        elif entity_exact_match:
            decision = "Direct Yes"
            site_claim_type = "company_or_brand_certified"
            confidence = "High"
            final_score = 100.0
            match_method = "company_or_brand_exact_normalized"
        elif company_score >= 97:
            decision = "Direct Yes"
            site_claim_type = "company_or_brand_certified"
            confidence = "High" if not short_name else "Medium"
            final_score = company_score
            match_method = "company_or_brand_very_high_fuzzy"
            if short_name:
                review_reason = "Name is short or potentially ambiguous; confidence reduced."
        elif company_score >= 93:
            if short_name:
                decision = "Direct Review"
                site_claim_type = "possible_company_or_brand_certification"
                confidence = "Low"
                review_reason = (
                    "High fuzzy match, but one of the names is short/ambiguous."
                )
            else:
                decision = "Direct Yes"
                site_claim_type = "company_or_brand_certified"
                confidence = "Medium"

            final_score = company_score
            match_method = "company_or_brand_high_fuzzy"
        elif company_score >= 86:
            decision = "Direct Review"
            site_claim_type = "possible_company_or_brand_certification"
            confidence = "Medium"
            final_score = company_score
            match_method = "company_or_brand_possible_fuzzy"
            review_reason = "Possible company/brand match. Manual review recommended."

    if decision == "No":
        final_score = max(company_score, product_score, domain_score)

    return {
        "decision": decision,
        "site_claim_type": site_claim_type,
        "confidence": confidence,
        "final_score": round(final_score, 2),
        "match_method": match_method,
        "review_reason": review_reason,
    }


def decide_supplier_oriented_registry_match(
    registry_row: pd.Series,
    scores: Dict[str, object],
    match_method_hint: str,
) -> Dict[str, object]:
    company_score = float(scores["company_score"])
    product_score = float(scores["product_score"])
    domain_score = float(scores["domain_score"])
    entity_exact_match = bool(scores["entity_exact_match"])
    product_exact_match = bool(scores["product_exact_match"])

    short_name = bool(scores["short_or_ambiguous_config_company"]) or bool(
        scores["short_or_ambiguous_registry_entity"]
    )

    decision = "No"
    site_claim_type = "none"
    confidence = ""
    final_score = 0.0
    match_method = match_method_hint
    review_reason = ""

    if domain_score == 100:
        decision = "Direct Yes"
        site_claim_type = "company_or_brand_certified"
        confidence = "High"
        final_score = 100.0
        match_method = "supplier_oriented_registry_domain_exact"
    elif entity_exact_match:
        decision = "Direct Yes"
        site_claim_type = "company_or_brand_certified"
        confidence = "High"
        final_score = 100.0
        match_method = "supplier_oriented_registry_company_exact"
    elif company_score >= 98 and not short_name:
        decision = "Direct Yes"
        site_claim_type = "company_or_brand_certified"
        confidence = "Medium"
        final_score = company_score
        match_method = "supplier_oriented_registry_very_high_company_fuzzy"
    elif company_score >= 88:
        decision = "Supplier Candidate"
        site_claim_type = "possible_certified_supplier_entity"
        confidence = "Medium" if company_score >= 93 else "Low"
        final_score = company_score
        match_method = "supplier_oriented_registry_company_candidate"
        review_reason = (
            "This is a supplier-oriented registry. This row should not be treated as direct product/company certification "
            "unless a buyer-supplier relationship is later verified."
        )
    elif product_exact_match and company_score >= 70:
        decision = "Supplier Candidate"
        site_claim_type = "possible_certified_supplier_entity"
        confidence = "Low"
        final_score = round((company_score * 0.45) + (product_score * 0.55), 2)
        match_method = "supplier_oriented_registry_product_candidate"
        review_reason = (
            "Product/entity looks potentially related in a supplier-oriented registry. Supplier relationship must be verified."
        )
    elif product_score >= 88 and company_score >= 60:
        decision = "Supplier Candidate"
        site_claim_type = "possible_certified_supplier_entity"
        confidence = "Low"
        final_score = round((company_score * 0.45) + (product_score * 0.55), 2)
        match_method = "supplier_oriented_registry_product_fuzzy_candidate"
        review_reason = (
            "Possible supplier-side product/entity candidate. Not a direct certification match."
        )

    if decision == "No":
        final_score = max(company_score, product_score, domain_score)

    return {
        "decision": decision,
        "site_claim_type": site_claim_type,
        "confidence": confidence,
        "final_score": round(final_score, 2),
        "match_method": match_method,
        "review_reason": review_reason,
    }


def decide_match(
    registry_row: pd.Series,
    scores: Dict[str, object],
    match_method_hint: str,
) -> Dict[str, object]:
    registry_usage_mode = clean_text(registry_row.get("registry_usage_mode", ""))

    if registry_usage_mode == "supplier_oriented_registry":
        return decide_supplier_oriented_registry_match(
            registry_row=registry_row,
            scores=scores,
            match_method_hint=match_method_hint,
        )

    return decide_direct_registry_match(
        registry_row=registry_row,
        scores=scores,
        match_method_hint=match_method_hint,
    )


def build_audit_row(
    config_record: pd.Series,
    certification: str,
    registry_row: Optional[pd.Series],
    decision_data: Dict[str, object],
    scores: Optional[Dict[str, object]],
) -> Dict[str, object]:
    if registry_row is None:
        registry_row = pd.Series(dtype=object)

    if scores is None:
        scores = {
            "company_score": 0.0,
            "product_score": 0.0,
            "domain_score": 0.0,
            "entity_exact_match": False,
            "product_exact_match": False,
        }

    return {
        "configurator_row_number": config_record["configurator_row_number"],
        "configurator_id": config_record["configurator_id"],
        "configurator_company": config_record["company"],
        "configurator_product": config_record["product"],
        "configurator_industry": config_record["industry"],
        "configurator_country": config_record["country"],
        "configurator_domains": config_record["domains_joined"],
        "certification": certification,
        "registry_usage_mode": clean_text(registry_row.get("registry_usage_mode", "")),
        "decision": decision_data.get("decision", "No"),
        "site_claim_type": decision_data.get("site_claim_type", "none"),
        "confidence": decision_data.get("confidence", ""),
        "final_score": decision_data.get("final_score", 0),
        "match_method": decision_data.get("match_method", ""),
        "matched_evidence_level": clean_text(registry_row.get("evidence_level", "")),
        "matched_registry_entity": clean_text(registry_row.get("certified_entity_name", "")),
        "matched_registry_company": clean_text(registry_row.get("certified_company", "")),
        "matched_registry_brand": clean_text(registry_row.get("certified_brand", "")),
        "matched_registry_product": clean_text(registry_row.get("certified_product", "")),
        "matched_product_category": clean_text(registry_row.get("product_category", "")),
        "matched_country_or_scope": clean_text(registry_row.get("country_or_scope", "")),
        "company_score": scores.get("company_score", 0.0),
        "product_score": scores.get("product_score", 0.0),
        "domain_score": scores.get("domain_score", 0.0),
        "entity_exact_match": scores.get("entity_exact_match", False),
        "product_exact_match": scores.get("product_exact_match", False),
        "master_record_id": clean_text(registry_row.get("master_record_id", "")),
        "certificate_identifier": clean_text(registry_row.get("certificate_identifier", "")),
        "source_file": clean_text(registry_row.get("source_file", "")),
        "source_sheet": clean_text(registry_row.get("source_sheet", "")),
        "source_row_number": clean_text(registry_row.get("source_row_number", "")),
        "source_url": clean_text(registry_row.get("source_url", "")),
        "evidence_text": truncate_for_excel(registry_row.get("evidence_text", "")),
        "review_reason": decision_data.get("review_reason", ""),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def find_candidate_indices(
    config_record: pd.Series,
    cert_index: Dict[str, object],
    args: argparse.Namespace,
) -> Dict[int, str]:
    candidate_indices: Dict[int, str] = {}

    entity_to_indices = cert_index["entity_to_indices"]
    product_to_indices = cert_index["product_to_indices"]
    domain_to_indices = cert_index["domain_to_indices"]
    entity_choices = cert_index["entity_choices"]
    product_choices = cert_index["product_choices"]

    config_company_strict = clean_text(config_record["company_normalized_strict"])
    config_product_strict = clean_text(config_record["product_normalized_strict"])
    config_domains = config_record["domains"]

    if config_company_strict in entity_to_indices:
        for index in entity_to_indices[config_company_strict]:
            candidate_indices[index] = "company_or_brand_exact_normalized"

    for domain in config_domains:
        if domain in domain_to_indices:
            for index in domain_to_indices[domain]:
                candidate_indices[index] = "domain_exact"

    for matched_choice, _score in fuzzy_extract(
        config_company_strict,
        entity_choices,
        limit=args.company_fuzzy_limit,
        score_cutoff=args.company_candidate_cutoff,
    ):
        for index in entity_to_indices.get(matched_choice, [])[: args.records_per_fuzzy_name]:
            candidate_indices.setdefault(index, "company_or_brand_fuzzy_candidate")

    if config_product_strict:
        for matched_choice, _score in fuzzy_extract(
            config_product_strict,
            product_choices,
            limit=args.product_fuzzy_limit,
            score_cutoff=args.product_candidate_cutoff,
        ):
            for index in product_to_indices.get(matched_choice, [])[: args.records_per_fuzzy_name]:
                candidate_indices.setdefault(index, "product_fuzzy_candidate")

    return candidate_indices


def choose_best_candidate(audit_rows: List[Dict[str, object]]) -> Dict[str, object]:
    if not audit_rows:
        raise ValueError("No audit rows supplied.")

    sorted_rows = sorted(
        audit_rows,
        key=lambda row: (
            decision_priority(clean_text(row.get("decision", ""))),
            confidence_priority(clean_text(row.get("confidence", ""))),
            float(row.get("final_score", 0) or 0),
            float(row.get("company_score", 0) or 0),
            float(row.get("product_score", 0) or 0),
            float(row.get("domain_score", 0) or 0),
        ),
        reverse=True,
    )

    return sorted_rows[0]


def run_matching(
    configurators_df: pd.DataFrame,
    master_df: pd.DataFrame,
    args: argparse.Namespace,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    config_records_df = prepare_configurator_records(configurators_df)
    master_df = prepare_master_registry(master_df)

    certifications = sorted(
        [
            certification
            for certification in master_df["certification"].dropna().astype(str).unique().tolist()
            if clean_text(certification)
        ]
    )

    audit_best_rows = []
    audit_candidate_rows = []

    print("")
    print("Matching configurators against master certification registry...")
    print(f"Configurators: {len(config_records_df)}")
    print(f"Certifications: {len(certifications)}")
    print(f"RapidFuzz available: {RAPIDFUZZ_AVAILABLE}")
    print("")

    for certification in certifications:
        cert_df = master_df[master_df["certification"] == certification].copy()

        if cert_df.empty:
            continue

        cert_index = build_certification_index(cert_df)

        usage_modes = " | ".join(
            sorted(
                set(
                    clean_text(value)
                    for value in cert_df["registry_usage_mode"].dropna().astype(str).tolist()
                    if clean_text(value)
                )
            )
        )

        print(
            f"Certification: {certification} | registry rows: {len(cert_df)} | "
            f"entities: {len(cert_index['entity_choices'])} | "
            f"products: {len(cert_index['product_choices'])} | "
            f"mode: {usage_modes}"
        )

        for _, config_record in config_records_df.iterrows():
            candidate_indices = find_candidate_indices(
                config_record=config_record,
                cert_index=cert_index,
                args=args,
            )

            candidate_audit_rows = []

            for candidate_index, match_method_hint in candidate_indices.items():
                registry_row = cert_df.loc[candidate_index]

                scores = calculate_candidate_scores(
                    config_record=config_record,
                    registry_row=registry_row,
                )

                decision_data = decide_match(
                    registry_row=registry_row,
                    scores=scores,
                    match_method_hint=match_method_hint,
                )

                if (
                    decision_data["decision"] == "No"
                    and decision_data["final_score"] < args.keep_no_candidate_score
                ):
                    continue

                audit_row = build_audit_row(
                    config_record=config_record,
                    certification=certification,
                    registry_row=registry_row,
                    decision_data=decision_data,
                    scores=scores,
                )

                candidate_audit_rows.append(audit_row)

            if candidate_audit_rows:
                best_row = choose_best_candidate(candidate_audit_rows)
                audit_best_rows.append(best_row)

                candidate_audit_rows_sorted = sorted(
                    candidate_audit_rows,
                    key=lambda row: (
                        decision_priority(clean_text(row.get("decision", ""))),
                        confidence_priority(clean_text(row.get("confidence", ""))),
                        float(row.get("final_score", 0) or 0),
                    ),
                    reverse=True,
                )

                audit_candidate_rows.extend(
                    candidate_audit_rows_sorted[: args.candidates_to_keep_per_config_cert]
                )

            else:
                no_row = build_audit_row(
                    config_record=config_record,
                    certification=certification,
                    registry_row=None,
                    decision_data={
                        "decision": "No",
                        "site_claim_type": "none",
                        "confidence": "",
                        "final_score": 0,
                        "match_method": "no_candidate_found",
                        "review_reason": "",
                    },
                    scores=None,
                )
                audit_best_rows.append(no_row)

    audit_best_df = pd.DataFrame(audit_best_rows)
    audit_candidates_df = pd.DataFrame(audit_candidate_rows)

    for column in AUDIT_COLUMNS:
        if column not in audit_best_df.columns:
            audit_best_df[column] = ""

        if column not in audit_candidates_df.columns:
            audit_candidates_df[column] = ""

    audit_best_df = audit_best_df[AUDIT_COLUMNS]
    audit_candidates_df = audit_candidates_df[AUDIT_COLUMNS]

    summary_df = build_matching_summary(audit_best_df)

    return audit_best_df, audit_candidates_df, summary_df


def build_matching_summary(audit_best_df: pd.DataFrame) -> pd.DataFrame:
    if audit_best_df.empty:
        return pd.DataFrame()

    summary_df = (
        audit_best_df.groupby(
            [
                "certification",
                "registry_usage_mode",
                "decision",
                "confidence",
            ],
            dropna=False,
        )
        .agg(
            rows=("configurator_id", "count"),
            unique_configurators=("configurator_id", "nunique"),
            average_final_score=("final_score", "mean"),
        )
        .reset_index()
    )

    summary_df["average_final_score"] = summary_df["average_final_score"].round(2)

    return summary_df.sort_values(
        [
            "certification",
            "registry_usage_mode",
            "decision",
            "confidence",
        ]
    ).reset_index(drop=True)


def build_enriched_dataset(
    configurators_df: pd.DataFrame,
    audit_best_df: pd.DataFrame,
) -> pd.DataFrame:
    enriched_df = configurators_df.copy()

    certifications = sorted(
        [
            certification
            for certification in audit_best_df["certification"].dropna().astype(str).unique().tolist()
            if clean_text(certification)
        ]
    )

    audit_by_config_cert = {}

    for _, row in audit_best_df.iterrows():
        key = (
            int(row["configurator_id"]),
            clean_text(row["certification"]),
        )
        audit_by_config_cert[key] = row

    for certification in certifications:
        direct_status_column = f"{certification} Direct Certification Status"
        direct_claim_type_column = f"{certification} Direct Claim Type"
        direct_evidence_level_column = f"{certification} Direct Evidence Level"
        direct_confidence_column = f"{certification} Direct Confidence"
        direct_method_column = f"{certification} Direct Match Method"
        direct_entity_column = f"{certification} Direct Matched Entity"
        direct_product_column = f"{certification} Direct Matched Product"
        direct_score_column = f"{certification} Direct Match Score"
        direct_evidence_column = f"{certification} Direct Evidence"

        supplier_candidate_column = f"{certification} Supplier Candidate"
        supplier_candidate_entity_column = f"{certification} Supplier Candidate Entity"
        supplier_candidate_score_column = f"{certification} Supplier Candidate Score"
        supplier_candidate_reason_column = f"{certification} Supplier Candidate Reason"

        direct_statuses = []
        direct_claim_types = []
        direct_evidence_levels = []
        direct_confidences = []
        direct_methods = []
        direct_entities = []
        direct_products = []
        direct_scores = []
        direct_evidences = []

        supplier_candidates = []
        supplier_candidate_entities = []
        supplier_candidate_scores = []
        supplier_candidate_reasons = []

        for index in range(len(enriched_df)):
            configurator_id = index + 1
            audit_row = audit_by_config_cert.get((configurator_id, certification))

            if audit_row is None:
                direct_statuses.append("No")
                direct_claim_types.append("")
                direct_evidence_levels.append("")
                direct_confidences.append("")
                direct_methods.append("")
                direct_entities.append("")
                direct_products.append("")
                direct_scores.append(0)
                direct_evidences.append("")

                supplier_candidates.append("No")
                supplier_candidate_entities.append("")
                supplier_candidate_scores.append(0)
                supplier_candidate_reasons.append("")
                continue

            decision = clean_text(audit_row.get("decision", "No"))

            if decision == "Direct Yes":
                direct_status = "Yes"
            elif decision == "Direct Review":
                direct_status = "Review"
            else:
                direct_status = "No"

            direct_statuses.append(direct_status)

            if decision in {"Direct Yes", "Direct Review"}:
                direct_claim_types.append(clean_text(audit_row.get("site_claim_type", "")))
                direct_evidence_levels.append(clean_text(audit_row.get("matched_evidence_level", "")))
                direct_confidences.append(clean_text(audit_row.get("confidence", "")))
                direct_methods.append(clean_text(audit_row.get("match_method", "")))
                direct_entities.append(clean_text(audit_row.get("matched_registry_entity", "")))
                direct_products.append(clean_text(audit_row.get("matched_registry_product", "")))
                direct_scores.append(audit_row.get("final_score", 0))
                direct_evidences.append(truncate_for_excel(audit_row.get("evidence_text", "")))
            else:
                direct_claim_types.append("")
                direct_evidence_levels.append("")
                direct_confidences.append("")
                direct_methods.append("")
                direct_entities.append("")
                direct_products.append("")
                direct_scores.append(0)
                direct_evidences.append("")

            if decision == "Supplier Candidate":
                supplier_candidates.append("Yes")
                supplier_candidate_entities.append(
                    clean_text(audit_row.get("matched_registry_entity", ""))
                )
                supplier_candidate_scores.append(audit_row.get("final_score", 0))
                supplier_candidate_reasons.append(
                    clean_text(audit_row.get("review_reason", ""))
                )
            else:
                supplier_candidates.append("No")
                supplier_candidate_entities.append("")
                supplier_candidate_scores.append(0)
                supplier_candidate_reasons.append("")

        enriched_df[direct_status_column] = direct_statuses
        enriched_df[direct_claim_type_column] = direct_claim_types
        enriched_df[direct_evidence_level_column] = direct_evidence_levels
        enriched_df[direct_confidence_column] = direct_confidences
        enriched_df[direct_method_column] = direct_methods
        enriched_df[direct_entity_column] = direct_entities
        enriched_df[direct_product_column] = direct_products
        enriched_df[direct_score_column] = direct_scores
        enriched_df[direct_evidence_column] = direct_evidences

        enriched_df[supplier_candidate_column] = supplier_candidates
        enriched_df[supplier_candidate_entity_column] = supplier_candidate_entities
        enriched_df[supplier_candidate_score_column] = supplier_candidate_scores
        enriched_df[supplier_candidate_reason_column] = supplier_candidate_reasons

    return enriched_df


def save_outputs(
    output_dir: Path,
    enriched_df: pd.DataFrame,
    audit_best_df: pd.DataFrame,
    audit_candidates_df: pd.DataFrame,
    summary_df: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    direct_yes_df = audit_best_df[audit_best_df["decision"] == "Direct Yes"].copy()
    direct_review_df = audit_best_df[audit_best_df["decision"] == "Direct Review"].copy()
    supplier_candidate_df = audit_best_df[
        audit_best_df["decision"] == "Supplier Candidate"
    ].copy()
    no_df = audit_best_df[audit_best_df["decision"] == "No"].copy()

    enriched_df = sanitize_dataframe_for_excel(enriched_df)
    audit_best_df = sanitize_dataframe_for_excel(audit_best_df)
    audit_candidates_df = sanitize_dataframe_for_excel(audit_candidates_df)
    direct_yes_df = sanitize_dataframe_for_excel(direct_yes_df)
    direct_review_df = sanitize_dataframe_for_excel(direct_review_df)
    supplier_candidate_df = sanitize_dataframe_for_excel(supplier_candidate_df)
    no_df = sanitize_dataframe_for_excel(no_df)
    summary_df = sanitize_dataframe_for_excel(summary_df)

    enriched_path = output_dir / "Dataset_Enhanced_LEME_Paolo_Rubino_WITH_CERTIFICATIONS_DRAFT_V2.xlsx"
    audit_path = output_dir / "certification_matches_audit_v2.xlsx"

    audit_best_csv = output_dir / "certification_matches_best_v2.csv"
    audit_candidates_csv = output_dir / "certification_matches_candidates_v2.csv"
    direct_yes_csv = output_dir / "certification_matches_direct_yes_v2.csv"
    direct_review_csv = output_dir / "certification_matches_direct_review_v2.csv"
    supplier_candidate_csv = output_dir / "certification_matches_supplier_candidates_v2.csv"
    summary_csv = output_dir / "certification_matching_summary_v2.csv"

    enriched_df.to_excel(enriched_path, index=False)

    audit_best_df.to_csv(audit_best_csv, index=False, encoding="utf-8-sig")
    audit_candidates_df.to_csv(audit_candidates_csv, index=False, encoding="utf-8-sig")
    direct_yes_df.to_csv(direct_yes_csv, index=False, encoding="utf-8-sig")
    direct_review_df.to_csv(direct_review_csv, index=False, encoding="utf-8-sig")
    supplier_candidate_df.to_csv(supplier_candidate_csv, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(audit_path, engine="openpyxl") as writer:
        audit_best_df.to_excel(writer, sheet_name="best_match_per_cert", index=False)
        audit_candidates_df.to_excel(writer, sheet_name="candidate_matches", index=False)
        direct_yes_df.to_excel(writer, sheet_name="direct_yes", index=False)
        direct_review_df.to_excel(writer, sheet_name="direct_review", index=False)
        supplier_candidate_df.to_excel(writer, sheet_name="supplier_candidates", index=False)
        no_df.to_excel(writer, sheet_name="no_match", index=False)
        summary_df.to_excel(writer, sheet_name="summary", index=False)

    print("")
    print("Saved files:")
    print(f"- {enriched_path}")
    print(f"- {audit_path}")
    print(f"- {audit_best_csv}")
    print(f"- {audit_candidates_csv}")
    print(f"- {direct_yes_csv}")
    print(f"- {direct_review_csv}")
    print(f"- {supplier_candidate_csv}")
    print(f"- {summary_csv}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Match configurator products/companies against the unified master certification registry, "
            "separating direct certification matches from supplier-side candidates."
        )
    )

    parser.add_argument(
        "--configurator-dataset",
        default=str(DEFAULT_CONFIGURATOR_DATASET),
        help=f"Configurator dataset path. Default: {DEFAULT_CONFIGURATOR_DATASET}",
    )

    parser.add_argument(
        "--master-registry-csv",
        default=str(DEFAULT_MASTER_REGISTRY_CSV),
        help=f"Master registry CSV path. Default: {DEFAULT_MASTER_REGISTRY_CSV}",
    )

    parser.add_argument(
        "--master-registry-xlsx",
        default=str(DEFAULT_MASTER_REGISTRY_XLSX),
        help=f"Master registry XLSX fallback path. Default: {DEFAULT_MASTER_REGISTRY_XLSX}",
    )

    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )

    parser.add_argument(
        "--company-candidate-cutoff",
        type=float,
        default=80.0,
        help="Minimum company/entity fuzzy score to generate a candidate. Default: 80.",
    )

    parser.add_argument(
        "--product-candidate-cutoff",
        type=float,
        default=82.0,
        help="Minimum product fuzzy score to generate a candidate. Default: 82.",
    )

    parser.add_argument(
        "--company-fuzzy-limit",
        type=int,
        default=8,
        help="Maximum fuzzy entity choices per configurator/certification. Default: 8.",
    )

    parser.add_argument(
        "--product-fuzzy-limit",
        type=int,
        default=8,
        help="Maximum fuzzy product choices per configurator/certification. Default: 8.",
    )

    parser.add_argument(
        "--records-per-fuzzy-name",
        type=int,
        default=5,
        help="Maximum registry rows kept for each fuzzy-matched name. Default: 5.",
    )

    parser.add_argument(
        "--candidates-to-keep-per-config-cert",
        type=int,
        default=5,
        help="Maximum candidate matches saved per configurator/certification. Default: 5.",
    )

    parser.add_argument(
        "--keep-no-candidate-score",
        type=float,
        default=80.0,
        help=(
            "Keep No candidate rows only if final candidate score is at least this value. "
            "Default: 80."
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    configurator_dataset_path = find_configurator_dataset(
        Path(args.configurator_dataset)
    )
    master_registry_csv_path = Path(args.master_registry_csv)
    master_registry_xlsx_path = Path(args.master_registry_xlsx)
    output_dir = Path(args.output_dir)

    print("Loading data...")
    print(f"Configurator dataset: {configurator_dataset_path}")
    print(f"Master registry CSV: {master_registry_csv_path}")
    print(f"Master registry XLSX fallback: {master_registry_xlsx_path}")

    configurators_df = read_configurator_dataset(configurator_dataset_path)
    master_df = read_master_registry(
        csv_path=master_registry_csv_path,
        xlsx_path=master_registry_xlsx_path,
    )

    print(f"Configurator rows: {len(configurators_df)}")
    print(f"Master registry rows: {len(master_df)}")

    audit_best_df, audit_candidates_df, summary_df = run_matching(
        configurators_df=configurators_df,
        master_df=master_df,
        args=args,
    )

    enriched_df = build_enriched_dataset(
        configurators_df=configurators_df,
        audit_best_df=audit_best_df,
    )

    print("")
    print("Matching summary:")
    if summary_df.empty:
        print("No summary available.")
    else:
        print(summary_df.to_string(index=False))

    save_outputs(
        output_dir=output_dir,
        enriched_df=enriched_df,
        audit_best_df=audit_best_df,
        audit_candidates_df=audit_candidates_df,
        summary_df=summary_df,
    )


if __name__ == "__main__":
    main()