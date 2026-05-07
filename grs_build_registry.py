import argparse
import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pdfplumber


CERTIFICATION_NAME = "Global Recycled Standard"
CERTIFICATION_SHORT_NAME = "GRS"
REGISTRY_SECTION = "ICEA certified textile companies and products"
SOURCE_ORGANIZATION = "ICEA"
SOURCE_STANDARD_VERSION = "GRS 4.0"

DEFAULT_INPUT_DIR = Path("data") / "certifications" / "GRS"
DEFAULT_OUTPUT_DIR = Path("data") / "certifications" / "GRS"

PDF_TITLE = (
    "Register of textile companies and products certified by ICEA according "
    "to Global Recycled Standard (GRS 4.0)"
)

DATE_PATTERN = (
    r"\b\d{1,2}\s*[-–]{0,2}\s*"
    r"(?:gen|jan|feb|mar|apr|mag|may|giu|jun|lug|jul|ago|aug|set|sep|ott|oct|nov|dic|dec)"
    r"\s*[-–]{0,2}\s*\d{2,4}\b"
)

DATE_RE = re.compile(DATE_PATTERN, flags=re.IGNORECASE)

CERTIFICATE_RE = re.compile(
    r"\bGRS\s*\d{4}\s*[-–]\s*\d{3}\b",
    flags=re.IGNORECASE,
)

SECTION_RE = re.compile(
    r"^<<\s*(?P<section>.+?)\s*>>$",
    flags=re.IGNORECASE,
)

GRS_VERSION_RE = re.compile(
    r"\bGRS\s*(?P<version>\d+(?:\.\d+)?)\b\s*$",
    flags=re.IGNORECASE,
)

FACILITIES_AND_VERSION_RE = re.compile(
    r"(?P<description>.*?)\s+(?P<facilities>\d+)\s+GRS\s*(?P<version>\d+(?:\.\d+)?)\s*$",
    flags=re.IGNORECASE | re.DOTALL,
)

URL_RE = re.compile(
    r"\b(?:(?:https?|htttp|http;?)://[^\s]+|www\.[^\s]+|[A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\s]*)\b",
    flags=re.IGNORECASE,
)

COUNTRIES = [
    "United Arab Emirates",
    "United Kingdom",
    "United States",
    "South Korea",
    "Czech Republic",
    "Switzerland",
    "Bangladesh",
    "Netherlands",
    "Pakistan",
    "Portugal",
    "Germany",
    "Ireland",
    "Türkiye",
    "Turkey",
    "France",
    "Poland",
    "India",
    "Spain",
    "Italy",
    "Italia",
    "taly",
    "China",
    "USA",
    "Taiwan",
    "Tunisia",
    "Romania",
    "Bulgaria",
    "Austria",
    "Belgium",
    "Greece",
    "Croatia",
    "Denmark",
    "Finland",
    "Sweden",
    "Norway",
    "Canada",
    "Mexico",
    "Brazil",
    "Morocco",
    "Egypt",
    "Pakistan",
    "Vietnam",
    "Japan",
    "Thailand",
    "Indonesia",
    "Sri Lanka",
]

COUNTRIES_SORTED = sorted(COUNTRIES, key=len, reverse=True)

NOISE_PATTERNS = [
    r"^ICEA\s*-\s*GRS\s*M\.?0403",
    r"^Last update",
    r"^Pag\.",
    r"^Page\s+\d+",
    r"^LICENSEE$",
    r"^CERTIFICATE$",
    r"^CERTIFIED PRODUCTS",
    r"^PROCESSES$",
    r"^Facilities$",
    r"^GRS\s+Version$",
    r"^Company name$",
    r"^State$",
    r"^Web$",
    r"^N°\s*Certificate$",
    r"^First issue$",
    r"^Revision$",
    r"^Expiring$",
    r"^Product\s*/\s*Process description$",
    r"^No\.$",
    r"^date$",
    r"^issue$",
    r"^LEGENDA",
    r"^Legend",
    r"^IT\s+EN$",
    r"^Nuove certificazioni",
    r"^SOMMARIO",
    r"^Index$",
    r"^Registro delle ditte",
    r"^Register of textile",
    r"^Maggio,\s*\d{4}$",
    r"^May,\s*\d{4}$",
    r"^GRS\s*M0403$",
]


def clean_text(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = text.replace("\ufffe", "-")
    text = text.replace("￾", "-")
    text = text.replace("‐", "-")
    text = text.replace("-", "-")
    text = text.replace("–", "-")
    text = text.replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    text = text.replace("pre- consumer", "pre-consumer")
    text = text.replace("post- consumer", "post-consumer")
    text = text.replace("pre - consumer", "pre-consumer")
    text = text.replace("post - consumer", "post-consumer")
    return text.strip()


def normalize_for_matching(value: object) -> str:
    text = clean_text(value).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def make_hash_key(*values: object) -> str:
    raw_key = "|".join(clean_text(value) for value in values)
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def normalize_certificate_number(value: str) -> str:
    text = clean_text(value).upper()
    text = re.sub(r"\s+", " ", text)
    text = text.replace(" – ", "-")
    text = re.sub(r"\s*-\s*", "-", text)
    return text


def normalize_date_token(value: str) -> str:
    text = clean_text(value).lower()
    text = text.replace(" ", "")
    text = text.replace("--", "-")
    text = text.replace("ò", "o")
    return text


def is_noise_line(line: str) -> bool:
    line = clean_text(line)

    if not line:
        return True

    for pattern in NOISE_PATTERNS:
        if re.search(pattern, line, flags=re.IGNORECASE):
            return True

    if re.fullmatch(r"\d+", line):
        return True

    return False


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


def parse_section_heading(line: str) -> Tuple[str, str, str]:
    line = clean_text(line)
    match = SECTION_RE.match(line)

    if not match:
        return "", "", ""

    section = clean_text(match.group("section"))

    if " - " in section:
        italian, english = section.split(" - ", 1)
    elif " – " in section:
        italian, english = section.split(" – ", 1)
    else:
        parts = re.split(r"\s+-\s+|\s+–\s+", section, maxsplit=1)
        if len(parts) == 2:
            italian, english = parts
        else:
            italian, english = section, ""

    return section, clean_text(italian), clean_text(english)


def looks_like_company_continuation(line: str) -> bool:
    line = clean_text(line)

    if not line:
        return False

    if CERTIFICATE_RE.search(line):
        return False

    if DATE_RE.search(line):
        return False

    if re.search(r"\d+%", line):
        return False

    if re.search(
        r"\b(recycled|regenerated|fiber|fibres|fabrics|yarns|cotton|polyester|polyamide|wool|process|consumer|chemical|formulation|chips|woven|knitted|textile)\b",
        line,
        flags=re.IGNORECASE,
    ):
        return False

    if len(line) <= 45 and re.search(
        r"(^&\s*|\b(srl|s\.r\.l|spa|s\.p\.a|snc|sas|s\.a\.|sa|ltd|limited|gmbh|co\.|company|inc\.?)\b)",
        line,
        flags=re.IGNORECASE,
    ):
        return True

    return False


def split_country_and_web(prefix: str) -> Tuple[str, str, str]:
    prefix = clean_text(prefix)

    for country in COUNTRIES_SORTED:
        pattern = re.compile(
            rf"^(?P<company>.+?)\s+(?P<country>{re.escape(country)})\s*(?P<tail>.*)$",
            flags=re.IGNORECASE,
        )

        match = pattern.match(prefix)

        if match:
            company_name = clean_text(match.group("company"))
            country_value = clean_text(match.group("country"))
            tail = clean_text(match.group("tail"))

            web = ""

            url_match = URL_RE.search(tail)
            if url_match:
                web = clean_text(url_match.group(0))
            elif tail and not DATE_RE.search(tail):
                web = tail

            if country_value.lower() == "taly":
                country_value = "Italy"

            if country_value.lower() == "italia":
                country_value = "Italy"

            return company_name, country_value, web

    return prefix, "", ""


def split_description_facilities_version(rest: str) -> Tuple[str, str, str]:
    rest = clean_text(rest)

    match = FACILITIES_AND_VERSION_RE.search(rest)

    if match:
        description = clean_text(match.group("description"))
        facilities_no = clean_text(match.group("facilities"))
        grs_version = clean_text(match.group("version"))
        return description, facilities_no, f"GRS {grs_version}"

    version_match = GRS_VERSION_RE.search(rest)
    if version_match:
        grs_version = f"GRS {version_match.group('version')}"
        description = GRS_VERSION_RE.sub("", rest)
        return clean_text(description), "", grs_version

    return rest, "", ""


def parse_dates_and_description(rest: str) -> Tuple[str, str, str, str]:
    rest = clean_text(rest)

    date_matches = list(DATE_RE.finditer(rest))
    date_values = [normalize_date_token(match.group(0)) for match in date_matches]

    first_issue_date = ""
    revision_date = ""
    expiring_date = ""

    if len(date_values) >= 3:
        first_issue_date = date_values[0]
        revision_date = date_values[1]
        expiring_date = date_values[2]
        description_start = date_matches[2].end()
    elif len(date_values) == 2:
        first_issue_date = date_values[0]
        expiring_date = date_values[1]
        description_start = date_matches[1].end()
    elif len(date_values) == 1:
        first_issue_date = date_values[0]
        description_start = date_matches[0].end()
    else:
        description_start = 0

    description = clean_text(rest[description_start:])

    return first_issue_date, revision_date, expiring_date, description


def compute_parse_confidence(record: Dict[str, object]) -> float:
    score = 0.0

    if clean_text(record.get("company_name")):
        score += 0.20

    if clean_text(record.get("country")):
        score += 0.10

    if clean_text(record.get("certificate_number")):
        score += 0.20

    if clean_text(record.get("product_process_description")):
        score += 0.20

    if clean_text(record.get("product_category_raw")):
        score += 0.10

    if clean_text(record.get("expiring_date")):
        score += 0.10

    if clean_text(record.get("grs_version")):
        score += 0.10

    return round(min(score, 1.0), 2)


def parse_record_start_line(
    line: str,
    page_number: int,
    source_file: Path,
    product_category_raw: str,
    product_category_it: str,
    product_category_en: str,
) -> Optional[Dict[str, object]]:
    line = clean_text(line)
    certificate_match = CERTIFICATE_RE.search(line)

    if not certificate_match:
        return None

    certificate_number = normalize_certificate_number(certificate_match.group(0))
    prefix = clean_text(line[: certificate_match.start()])
    rest = clean_text(line[certificate_match.end() :])

    company_name, country, web = split_country_and_web(prefix)

    first_issue_date, revision_date, expiring_date, rest_after_dates = (
        parse_dates_and_description(rest)
    )

    description, facilities_no, grs_version = split_description_facilities_version(
        rest_after_dates
    )

    record = {
        "certification": CERTIFICATION_SHORT_NAME,
        "certification_full_name": CERTIFICATION_NAME,
        "registry_section": REGISTRY_SECTION,
        "registry_source": SOURCE_ORGANIZATION,
        "registry_match_level": "company_certificate_product_process",
        "product_category_raw": product_category_raw,
        "product_category_it": product_category_it,
        "product_category_en": product_category_en,
        "company_name": company_name,
        "company_name_normalized": normalize_for_matching(company_name),
        "country": country,
        "country_normalized": normalize_for_matching(country),
        "web": web,
        "certificate_number": certificate_number,
        "certificate_number_normalized": normalize_for_matching(certificate_number),
        "first_issue_date": first_issue_date,
        "revision_date": revision_date,
        "expiring_date": expiring_date,
        "product_process_description": description,
        "product_process_description_normalized": normalize_for_matching(description),
        "facilities_no": facilities_no,
        "grs_version": grs_version,
        "source_pdf": str(source_file),
        "source_file_name": source_file.name,
        "source_page": page_number,
        "source_title": PDF_TITLE,
        "raw_start_line": line,
        "evidence_text": line,
        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    record["record_key"] = make_hash_key(
        record["company_name"],
        record["country"],
        record["certificate_number"],
        record["product_category_raw"],
        record["product_process_description"],
        record["source_page"],
    )

    record["parse_confidence"] = compute_parse_confidence(record)

    return record


def finalize_record(record: Dict[str, object]) -> Dict[str, object]:
    description = clean_text(record.get("product_process_description", ""))

    description = description.replace("pre- consumer", "pre-consumer")
    description = description.replace("post- consumer", "post-consumer")
    description = description.replace("pre - consumer", "pre-consumer")
    description = description.replace("post - consumer", "post-consumer")

    record["product_process_description"] = description
    record["product_process_description_normalized"] = normalize_for_matching(description)

    evidence = clean_text(record.get("evidence_text", ""))
    record["evidence_text"] = evidence

    record["company_name"] = clean_text(record.get("company_name", ""))
    record["company_name_normalized"] = normalize_for_matching(record["company_name"])

    record["record_key"] = make_hash_key(
        record["company_name"],
        record["country"],
        record["certificate_number"],
        record["product_category_raw"],
        record["product_process_description"],
        record["source_page"],
    )

    record["parse_confidence"] = compute_parse_confidence(record)

    return record


def extract_pdf_lines(
    pdf_path: Path,
    start_page: int,
    max_pages: Optional[int],
) -> List[Dict[str, object]]:
    rows = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)

        start_index = max(start_page - 1, 0)

        if max_pages is None:
            end_index = total_pages
        else:
            end_index = min(start_index + max_pages, total_pages)

        for page_index in range(start_index, end_index):
            page = pdf.pages[page_index]

            text = page.extract_text(
                x_tolerance=1,
                y_tolerance=3,
                layout=False,
            )

            if not text:
                continue

            for line_number, raw_line in enumerate(text.splitlines(), start=1):
                line = clean_text(raw_line)

                if not line:
                    continue

                rows.append(
                    {
                        "source_pdf": str(pdf_path),
                        "source_file_name": pdf_path.name,
                        "source_page": page_index + 1,
                        "line_number": line_number,
                        "raw_line": line,
                    }
                )

    return rows


def build_records_from_lines(
    line_rows: List[Dict[str, object]],
    source_file: Path,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    records = []
    rejected_lines = []

    current_record: Optional[Dict[str, object]] = None
    current_product_category_raw = ""
    current_product_category_it = ""
    current_product_category_en = ""

    for line_row in line_rows:
        line = clean_text(line_row["raw_line"])
        page_number = int(line_row["source_page"])

        section_raw, section_it, section_en = parse_section_heading(line)

        if section_raw:
            if current_record is not None:
                records.append(finalize_record(current_record))
                current_record = None

            current_product_category_raw = section_raw
            current_product_category_it = section_it
            current_product_category_en = section_en

            rejected_lines.append(
                {
                    **line_row,
                    "reason": "section_heading",
                    "product_category_raw": current_product_category_raw,
                }
            )
            continue

        if is_noise_line(line):
            rejected_lines.append(
                {
                    **line_row,
                    "reason": "header_footer_or_noise",
                    "product_category_raw": current_product_category_raw,
                }
            )
            continue

        new_record = parse_record_start_line(
            line=line,
            page_number=page_number,
            source_file=source_file,
            product_category_raw=current_product_category_raw,
            product_category_it=current_product_category_it,
            product_category_en=current_product_category_en,
        )

        if new_record is not None:
            if current_record is not None:
                records.append(finalize_record(current_record))

            current_record = new_record
            continue

        if current_record is not None:
            if looks_like_company_continuation(line):
                current_record["company_name"] = clean_text(
                    f"{current_record.get('company_name', '')} {line}"
                )
                current_record["evidence_text"] = clean_text(
                    f"{current_record.get('evidence_text', '')} | {line}"
                )
            else:
                current_record["product_process_description"] = clean_text(
                    f"{current_record.get('product_process_description', '')} {line}"
                )
                current_record["evidence_text"] = clean_text(
                    f"{current_record.get('evidence_text', '')} | {line}"
                )
        else:
            rejected_lines.append(
                {
                    **line_row,
                    "reason": "unassigned_line_without_current_record",
                    "product_category_raw": current_product_category_raw,
                }
            )

    if current_record is not None:
        records.append(finalize_record(current_record))

    records_df = pd.DataFrame(records)
    rejected_df = pd.DataFrame(rejected_lines)

    if not records_df.empty:
        records_df = records_df.drop_duplicates(
            subset=["record_key"],
            keep="first",
        ).reset_index(drop=True)

    return records_df, rejected_df


def build_company_summary(records_df: pd.DataFrame) -> pd.DataFrame:
    if records_df.empty:
        return pd.DataFrame()

    summary_df = (
        records_df.groupby(
            [
                "company_name",
                "company_name_normalized",
                "country",
                "country_normalized",
                "web",
            ],
            dropna=False,
        )
        .agg(
            grs_rows=("record_key", "count"),
            unique_certificates=("certificate_number_normalized", "nunique"),
            product_categories=(
                "product_category_en",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))
                ),
            ),
            certificate_numbers=(
                "certificate_number",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))
                ),
            ),
            first_source_page=("source_page", "min"),
            last_source_page=("source_page", "max"),
            source_pdf=("source_pdf", "first"),
            source_file_name=("source_file_name", "first"),
        )
        .reset_index()
    )

    summary_df["certification"] = CERTIFICATION_SHORT_NAME
    summary_df["certification_full_name"] = CERTIFICATION_NAME
    summary_df["registry_section"] = "Company Summary"
    summary_df["registry_match_level"] = "company"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['company_name']} appears in {row['grs_rows']} GRS row(s), "
            f"with {row['unique_certificates']} unique certificate(s). "
            f"Product categories: {row['product_categories']}"
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "company_name",
            "company_name_normalized",
            "country",
            "country_normalized",
            "web",
            "grs_rows",
            "unique_certificates",
            "certificate_numbers",
            "product_categories",
            "first_source_page",
            "last_source_page",
            "source_pdf",
            "source_file_name",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        ["company_name_normalized", "country_normalized"]
    ).reset_index(drop=True)


def build_certificate_summary(records_df: pd.DataFrame) -> pd.DataFrame:
    if records_df.empty:
        return pd.DataFrame()

    summary_df = (
        records_df.groupby(
            [
                "certificate_number",
                "certificate_number_normalized",
                "company_name",
                "company_name_normalized",
                "country",
                "country_normalized",
            ],
            dropna=False,
        )
        .agg(
            grs_rows=("record_key", "count"),
            product_categories=(
                "product_category_en",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))
                ),
            ),
            first_issue_dates=(
                "first_issue_date",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))
                ),
            ),
            revision_dates=(
                "revision_date",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))
                ),
            ),
            expiring_dates=(
                "expiring_date",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))
                ),
            ),
            grs_versions=(
                "grs_version",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))
                ),
            ),
            first_source_page=("source_page", "min"),
            last_source_page=("source_page", "max"),
            source_pdf=("source_pdf", "first"),
            source_file_name=("source_file_name", "first"),
        )
        .reset_index()
    )

    summary_df["certification"] = CERTIFICATION_SHORT_NAME
    summary_df["certification_full_name"] = CERTIFICATION_NAME
    summary_df["registry_section"] = "Certificate Summary"
    summary_df["registry_match_level"] = "certificate"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['certificate_number']} for {row['company_name']} appears in "
            f"{row['grs_rows']} row(s). Product categories: {row['product_categories']}"
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "certificate_number",
            "certificate_number_normalized",
            "company_name",
            "company_name_normalized",
            "country",
            "country_normalized",
            "grs_rows",
            "product_categories",
            "first_issue_dates",
            "revision_dates",
            "expiring_dates",
            "grs_versions",
            "first_source_page",
            "last_source_page",
            "source_pdf",
            "source_file_name",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        ["certificate_number_normalized", "company_name_normalized"]
    ).reset_index(drop=True)


def build_category_summary(records_df: pd.DataFrame) -> pd.DataFrame:
    if records_df.empty:
        return pd.DataFrame()

    summary_df = (
        records_df.groupby(
            [
                "product_category_raw",
                "product_category_it",
                "product_category_en",
            ],
            dropna=False,
        )
        .agg(
            grs_rows=("record_key", "count"),
            unique_companies=("company_name_normalized", "nunique"),
            unique_certificates=("certificate_number_normalized", "nunique"),
            countries=(
                "country",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))
                ),
            ),
            first_source_page=("source_page", "min"),
            last_source_page=("source_page", "max"),
            source_pdf=("source_pdf", "first"),
            source_file_name=("source_file_name", "first"),
        )
        .reset_index()
    )

    summary_df["certification"] = CERTIFICATION_SHORT_NAME
    summary_df["certification_full_name"] = CERTIFICATION_NAME
    summary_df["registry_section"] = "Product / Process Category Summary"
    summary_df["registry_match_level"] = "product_process_category"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['product_category_raw']} contains {row['grs_rows']} GRS row(s), "
            f"{row['unique_companies']} unique companies and "
            f"{row['unique_certificates']} unique certificates."
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "product_category_raw",
            "product_category_it",
            "product_category_en",
            "grs_rows",
            "unique_companies",
            "unique_certificates",
            "countries",
            "first_source_page",
            "last_source_page",
            "source_pdf",
            "source_file_name",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(["product_category_raw"]).reset_index(drop=True)


def build_metadata(
    pdf_files: List[Path],
    raw_lines_df: pd.DataFrame,
    records_df: pd.DataFrame,
    companies_df: pd.DataFrame,
    certificates_df: pd.DataFrame,
    categories_df: pd.DataFrame,
    rejected_df: pd.DataFrame,
    args: argparse.Namespace,
) -> pd.DataFrame:
    low_confidence_rows = 0

    if not records_df.empty and "parse_confidence" in records_df.columns:
        low_confidence_rows = int((records_df["parse_confidence"] < 0.7).sum())

    metadata = [
        {
            "certification": CERTIFICATION_SHORT_NAME,
            "certification_full_name": CERTIFICATION_NAME,
            "source_organization": SOURCE_ORGANIZATION,
            "source_standard_version": SOURCE_STANDARD_VERSION,
            "source_title": PDF_TITLE,
            "source_type": "PDF parsed with pdfplumber",
            "source_files": " | ".join(str(path) for path in pdf_files),
            "pdf_files_processed": len(pdf_files),
            "raw_lines_extracted": len(raw_lines_df),
            "registry_rows_extracted": len(records_df),
            "company_summary_rows": len(companies_df),
            "certificate_summary_rows": len(certificates_df),
            "category_summary_rows": len(categories_df),
            "rejected_or_noise_lines": len(rejected_df),
            "low_confidence_rows_below_0_70": low_confidence_rows,
            "start_page": args.start_page,
            "max_pages": args.max_pages,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": (
                "This registry is built from an ICEA PDF register. PDF table extraction can contain "
                "line wrapping artifacts, so rows include evidence_text, source_page and parse_confidence "
                "for quality control."
            ),
        }
    ]

    return pd.DataFrame(metadata)


def save_outputs(
    output_dir: Path,
    records_df: pd.DataFrame,
    companies_df: pd.DataFrame,
    certificates_df: pd.DataFrame,
    categories_df: pd.DataFrame,
    raw_lines_df: pd.DataFrame,
    rejected_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    records_csv = output_dir / "grs_products_processes_registry.csv"
    companies_csv = output_dir / "grs_companies.csv"
    certificates_csv = output_dir / "grs_certificates.csv"
    categories_csv = output_dir / "grs_product_process_categories.csv"
    raw_lines_csv = output_dir / "grs_raw_lines.csv"
    rejected_csv = output_dir / "grs_rejected_lines.csv"
    metadata_csv = output_dir / "grs_metadata.csv"
    excel_path = output_dir / "grs_registry.xlsx"

    records_df.to_csv(records_csv, index=False, encoding="utf-8-sig")
    companies_df.to_csv(companies_csv, index=False, encoding="utf-8-sig")
    certificates_df.to_csv(certificates_csv, index=False, encoding="utf-8-sig")
    categories_df.to_csv(categories_csv, index=False, encoding="utf-8-sig")
    raw_lines_df.to_csv(raw_lines_csv, index=False, encoding="utf-8-sig")
    rejected_df.to_csv(rejected_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        records_df.to_excel(writer, sheet_name="products_processes", index=False)
        companies_df.to_excel(writer, sheet_name="companies", index=False)
        certificates_df.to_excel(writer, sheet_name="certificates", index=False)
        categories_df.to_excel(writer, sheet_name="categories", index=False)
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        rejected_df.to_excel(writer, sheet_name="rejected_lines", index=False)
        raw_lines_df.to_excel(writer, sheet_name="raw_lines", index=False)

    print("")
    print("Saved files:")
    print(f"- {records_csv}")
    print(f"- {companies_csv}")
    print(f"- {certificates_csv}")
    print(f"- {categories_csv}")
    print(f"- {metadata_csv}")
    print(f"- {rejected_csv}")
    print(f"- {raw_lines_csv}")
    print(f"- {excel_path}")


def build_grs_registry(
    input_dir: Path,
    output_dir: Path,
    pdf_path: Optional[Path],
    args: argparse.Namespace,
) -> None:
    pdf_files = get_pdf_files(input_dir=input_dir, explicit_pdf=pdf_path)

    all_raw_lines = []
    all_records = []
    all_rejected = []

    print("Building GRS registry from ICEA PDF file(s)...")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Start page: {args.start_page}")
    print(f"Max pages: {args.max_pages}")
    print("")

    for current_pdf_path in pdf_files:
        print(f"Reading PDF: {current_pdf_path}")

        line_rows = extract_pdf_lines(
            pdf_path=current_pdf_path,
            start_page=args.start_page,
            max_pages=args.max_pages,
        )

        raw_lines_df = pd.DataFrame(line_rows)

        records_df, rejected_df = build_records_from_lines(
            line_rows=line_rows,
            source_file=current_pdf_path,
        )

        print(f"  Raw lines extracted: {len(raw_lines_df)}")
        print(f"  Registry rows extracted: {len(records_df)}")
        print(f"  Rejected/noise lines: {len(rejected_df)}")

        all_raw_lines.append(raw_lines_df)
        all_records.append(records_df)
        all_rejected.append(rejected_df)

    combined_raw_lines_df = (
        pd.concat(all_raw_lines, ignore_index=True)
        if all_raw_lines
        else pd.DataFrame()
    )

    combined_records_df = (
        pd.concat(all_records, ignore_index=True)
        if all_records
        else pd.DataFrame()
    )

    combined_rejected_df = (
        pd.concat(all_rejected, ignore_index=True)
        if all_rejected
        else pd.DataFrame()
    )

    if not combined_records_df.empty:
        combined_records_df = combined_records_df.drop_duplicates(
            subset=["record_key"],
            keep="first",
        ).reset_index(drop=True)

        combined_records_df = combined_records_df.sort_values(
            [
                "company_name_normalized",
                "certificate_number_normalized",
                "product_category_raw",
                "source_page",
            ]
        ).reset_index(drop=True)

    companies_df = build_company_summary(combined_records_df)
    certificates_df = build_certificate_summary(combined_records_df)
    categories_df = build_category_summary(combined_records_df)

    metadata_df = build_metadata(
        pdf_files=pdf_files,
        raw_lines_df=combined_raw_lines_df,
        records_df=combined_records_df,
        companies_df=companies_df,
        certificates_df=certificates_df,
        categories_df=categories_df,
        rejected_df=combined_rejected_df,
        args=args,
    )

    print("")
    print("Registry summary:")
    print(f"  Product/process rows: {len(combined_records_df)}")
    print(f"  Company rows: {len(companies_df)}")
    print(f"  Certificate rows: {len(certificates_df)}")
    print(f"  Category rows: {len(categories_df)}")

    if not combined_records_df.empty and "parse_confidence" in combined_records_df.columns:
        low_confidence_count = int((combined_records_df["parse_confidence"] < 0.7).sum())
        print(f"  Low-confidence rows (<0.70): {low_confidence_count}")

    save_outputs(
        output_dir=output_dir,
        records_df=combined_records_df,
        companies_df=companies_df,
        certificates_df=certificates_df,
        categories_df=categories_df,
        raw_lines_df=combined_raw_lines_df,
        rejected_df=combined_rejected_df,
        metadata_df=metadata_df,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local GRS registry from the ICEA PDF register of textile companies "
            "and products certified according to Global Recycled Standard."
        )
    )

    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help=f"Directory containing GRS PDF files. Default: {DEFAULT_INPUT_DIR}",
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

    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="PDF page to start from, 1-based. Default: 1.",
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional number of pages to process. Default: all pages.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    pdf_path = Path(args.pdf) if args.pdf else None

    build_grs_registry(
        input_dir=input_dir,
        output_dir=output_dir,
        pdf_path=pdf_path,
        args=args,
    )


if __name__ == "__main__":
    main()