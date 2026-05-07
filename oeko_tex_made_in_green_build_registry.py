import argparse
import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup


CERTIFICATION_NAME = "OEKO-TEX MADE IN GREEN"
CERTIFICATION_DISPLAY_NAME = "OEKO-TEX® MADE IN GREEN"
CERTIFICATION_GROUP = "OEKO-TEX"
REGISTRY_SECTION = "OEKO-TEX Directory - Brands"
OFFICIAL_SOURCE_URL = "https://www.oeko-tex.com/en/oeko-tex-directory/"

DEFAULT_INPUT_DIR = Path("data") / "certifications" / "oeko_tex_made_in_green"
DEFAULT_OUTPUT_DIR = Path("data") / "certifications" / "oeko_tex_made_in_green"

STANDARD_CODE_LABELS = {
    "mig": "MADE IN GREEN",
    "std100": "STANDARD 100",
}


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


def get_html_files(input_dir: Path, explicit_html: Optional[Path]) -> List[Path]:
    if explicit_html is not None:
        if not explicit_html.exists():
            raise FileNotFoundError(f"HTML file not found: {explicit_html}")

        return [explicit_html]

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    html_files = sorted(
        list(input_dir.glob("*.html"))
        + list(input_dir.glob("*.htm"))
    )

    if not html_files:
        raise FileNotFoundError(
            f"No HTML files found in: {input_dir}. "
            "Save the OEKO-TEX Directory page HTML in this folder, or pass --html."
        )

    return html_files


def download_live_html(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = output_dir / f"oeko_tex_directory_live_{timestamp}.html"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
    }

    response = requests.get(
        OFFICIAL_SOURCE_URL,
        headers=headers,
        timeout=45,
    )
    response.raise_for_status()

    html_path.write_text(response.text, encoding="utf-8", errors="ignore")

    return html_path


def read_html_file(html_path: Path) -> str:
    encodings = [
        "utf-8",
        "utf-8-sig",
        "cp1252",
        "latin-1",
    ]

    for encoding in encodings:
        try:
            return html_path.read_text(encoding=encoding, errors="strict")
        except UnicodeDecodeError:
            continue

    return html_path.read_text(encoding="utf-8", errors="ignore")


def absolute_url(url: str) -> str:
    url = clean_text(url)

    if not url:
        return ""

    if url.startswith("http://") or url.startswith("https://"):
        return url

    if url.startswith("//"):
        return "https:" + url

    if url.startswith("/"):
        return "https://www.oeko-tex.com" + url

    return url


def parse_country_map(soup: BeautifulSoup) -> Dict[str, str]:
    country_map: Dict[str, str] = {}

    country_select = soup.select_one("select[data-filter-country]")

    if not country_select:
        return country_map

    for option in country_select.select("option"):
        country_id = clean_text(option.get("value", ""))
        country_name = clean_text(option.get_text(" ", strip=True))

        if not country_id:
            continue

        if not country_name or country_name.lower() == "choose country":
            continue

        country_map[country_id] = country_name

    return country_map


def standards_codes_to_labels(standards_raw: str) -> str:
    codes = [
        clean_text(code).lower()
        for code in clean_text(standards_raw).split(",")
        if clean_text(code)
    ]

    labels = []

    for code in codes:
        labels.append(STANDARD_CODE_LABELS.get(code, code.upper()))

    return " | ".join(labels)


def build_country_summary(all_brands_df: pd.DataFrame) -> pd.DataFrame:
    if all_brands_df.empty:
        return pd.DataFrame()

    summary_df = (
        all_brands_df.groupby(
            [
                "country_id",
                "country_name",
                "country_name_normalized",
            ],
            dropna=False,
        )
        .agg(
            total_brand_rows=("brand_name", "count"),
            unique_brand_names=("brand_name_normalized", "nunique"),
            made_in_green_brand_rows=("has_made_in_green", "sum"),
            standard100_brand_rows=("has_standard_100", "sum"),
            brand_names=(
                "brand_name",
                lambda values: " | ".join(
                    sorted(
                        set(
                            clean_text(value)
                            for value in values
                            if clean_text(value)
                        )
                    )[:80]
                ),
            ),
            source_url=("source_url", "first"),
        )
        .reset_index()
    )

    summary_df["certification_group"] = CERTIFICATION_GROUP
    summary_df["registry_section"] = "Country Summary"
    summary_df["registry_match_level"] = "country_summary"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['country_name'] or 'Unknown country'} has "
            f"{row['total_brand_rows']} OEKO-TEX brand row(s), including "
            f"{row['made_in_green_brand_rows']} MADE IN GREEN brand row(s)."
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification_group",
            "registry_section",
            "registry_match_level",
            "country_id",
            "country_name",
            "country_name_normalized",
            "total_brand_rows",
            "unique_brand_names",
            "made_in_green_brand_rows",
            "standard100_brand_rows",
            "brand_names",
            "source_url",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        [
            "country_name_normalized",
            "country_id",
        ]
    ).reset_index(drop=True)


def build_standards_summary(all_brands_df: pd.DataFrame) -> pd.DataFrame:
    if all_brands_df.empty:
        return pd.DataFrame()

    rows = []

    standards = [
        {
            "standard_code": "mig",
            "standard_label": "MADE IN GREEN",
            "column": "has_made_in_green",
        },
        {
            "standard_code": "std100",
            "standard_label": "STANDARD 100",
            "column": "has_standard_100",
        },
    ]

    for standard in standards:
        filtered = all_brands_df[all_brands_df[standard["column"]] == True]

        rows.append(
            {
                "certification_group": CERTIFICATION_GROUP,
                "registry_section": "Standards Summary",
                "registry_match_level": "standard_summary",
                "standard_code": standard["standard_code"],
                "standard_label": standard["standard_label"],
                "brand_rows": len(filtered),
                "unique_brand_names": filtered["brand_name_normalized"].nunique()
                if not filtered.empty
                else 0,
                "countries": " | ".join(
                    sorted(
                        set(
                            clean_text(value)
                            for value in filtered["country_name"].tolist()
                            if clean_text(value)
                        )
                    )
                )
                if not filtered.empty
                else "",
                "source_url": OFFICIAL_SOURCE_URL,
                "evidence_text": (
                    f"{standard['standard_label']} has {len(filtered)} brand row(s) "
                    f"in the parsed OEKO-TEX Directory HTML."
                ),
            }
        )

    return pd.DataFrame(rows)


def parse_brand_rows_from_html(
    html: str,
    source_file: Path,
) -> Dict[str, pd.DataFrame]:
    soup = BeautifulSoup(html, "html.parser")

    country_map = parse_country_map(soup)

    rows: List[Dict[str, object]] = []

    brand_nodes = soup.select(".brand[data-filterable-name]")

    for brand_node in brand_nodes:
        brand_name = clean_text(brand_node.get("data-filterable-name", ""))

        if not brand_name:
            headline_node = brand_node.select_one(".brand__headline")
            brand_name = (
                clean_text(headline_node.get_text(" ", strip=True))
                if headline_node
                else ""
            )

        if not brand_name:
            continue

        standards_raw = clean_text(brand_node.get("data-filterable-standards", ""))
        standards_codes = [
            clean_text(code).lower()
            for code in standards_raw.split(",")
            if clean_text(code)
        ]

        country_id = clean_text(brand_node.get("data-filterable-country", ""))
        country_name = country_map.get(country_id, "")

        website_url = ""

        parent_link = brand_node.find_parent("a")

        if parent_link:
            website_url = absolute_url(parent_link.get("href", ""))

        group_node = brand_node.find_parent(class_="brands__group")
        letter_group = ""

        if group_node:
            letter_group = clean_text(group_node.get("data-filterable-letter", ""))

            if not letter_group:
                letter_heading = group_node.select_one(".brands__letter")
                letter_group = (
                    clean_text(letter_heading.get_text(" ", strip=True))
                    if letter_heading
                    else ""
                )

        standards_labels = standards_codes_to_labels(standards_raw)

        has_made_in_green = "mig" in standards_codes
        has_standard_100 = "std100" in standards_codes

        registry_match_level = "brand"

        if has_made_in_green:
            registry_match_level = "made_in_green_brand"

        brand_key = make_hash_key(
            brand_name,
            website_url,
            standards_raw,
            country_id,
            source_file.name,
        )

        evidence_text = (
            f"{brand_name} | standards={standards_raw} | "
            f"country_id={country_id} | country={country_name} | url={website_url}"
        )

        rows.append(
            {
                "certification": CERTIFICATION_NAME,
                "certification_display_name": CERTIFICATION_DISPLAY_NAME,
                "certification_group": CERTIFICATION_GROUP,
                "registry_section": REGISTRY_SECTION,
                "registry_source": "OEKO-TEX Directory HTML",
                "registry_match_level": registry_match_level,
                "brand_key": brand_key,
                "brand_name": brand_name,
                "brand_name_normalized": normalize_for_matching(brand_name),
                "website_url": website_url,
                "standards_raw": standards_raw,
                "standards_labels": standards_labels,
                "has_made_in_green": has_made_in_green,
                "has_standard_100": has_standard_100,
                "country_id": country_id,
                "country_name": country_name,
                "country_name_normalized": normalize_for_matching(country_name),
                "letter_group": letter_group,
                "source_url": OFFICIAL_SOURCE_URL,
                "source_file": str(source_file),
                "source_file_name": source_file.name,
                "evidence_text": evidence_text,
                "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

    all_brands_df = pd.DataFrame(rows)

    if all_brands_df.empty:
        return {
            "all_brands": all_brands_df,
            "made_in_green_brands": pd.DataFrame(),
            "standard100_brands": pd.DataFrame(),
            "country_summary": pd.DataFrame(),
            "standards_summary": pd.DataFrame(),
        }

    all_brands_df = all_brands_df.drop_duplicates(
        subset=[
            "brand_name_normalized",
            "website_url",
            "standards_raw",
            "country_id",
        ],
        keep="first",
    ).reset_index(drop=True)

    all_brands_df = all_brands_df.sort_values(
        [
            "brand_name_normalized",
            "country_name_normalized",
            "website_url",
        ]
    ).reset_index(drop=True)

    made_in_green_df = all_brands_df[
        all_brands_df["has_made_in_green"] == True
    ].copy()

    made_in_green_df["certification"] = CERTIFICATION_NAME
    made_in_green_df["certification_display_name"] = CERTIFICATION_DISPLAY_NAME
    made_in_green_df["registry_match_level"] = "made_in_green_brand"

    made_in_green_df = made_in_green_df.sort_values(
        [
            "brand_name_normalized",
            "country_name_normalized",
            "website_url",
        ]
    ).reset_index(drop=True)

    standard100_df = all_brands_df[
        all_brands_df["has_standard_100"] == True
    ].copy()

    standard100_df = standard100_df.sort_values(
        [
            "brand_name_normalized",
            "country_name_normalized",
            "website_url",
        ]
    ).reset_index(drop=True)

    country_summary_df = build_country_summary(all_brands_df)
    standards_summary_df = build_standards_summary(all_brands_df)

    return {
        "all_brands": all_brands_df,
        "made_in_green_brands": made_in_green_df,
        "standard100_brands": standard100_df,
        "country_summary": country_summary_df,
        "standards_summary": standards_summary_df,
    }


def build_metadata(
    html_files: List[Path],
    all_brands_df: pd.DataFrame,
    made_in_green_df: pd.DataFrame,
    standard100_df: pd.DataFrame,
    country_summary_df: pd.DataFrame,
    standards_summary_df: pd.DataFrame,
    args: argparse.Namespace,
) -> pd.DataFrame:
    metadata = [
        {
            "certification": CERTIFICATION_NAME,
            "certification_display_name": CERTIFICATION_DISPLAY_NAME,
            "certification_group": CERTIFICATION_GROUP,
            "registry_section": REGISTRY_SECTION,
            "source_type": "Static HTML parsed with BeautifulSoup html.parser",
            "source_url": OFFICIAL_SOURCE_URL,
            "source_files": " | ".join(str(path) for path in html_files),
            "html_files_processed": len(html_files),
            "all_oeko_tex_brand_rows": len(all_brands_df),
            "made_in_green_brand_rows": len(made_in_green_df),
            "standard100_brand_rows": len(standard100_df),
            "country_summary_rows": len(country_summary_df),
            "standards_summary_rows": len(standards_summary_df),
            "download_live": args.download_live,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": (
                "The OEKO-TEX Directory stores brand data in static HTML brand elements. "
                "The code 'mig' is interpreted as MADE IN GREEN and 'std100' as STANDARD 100. "
                "This registry is brand-level, not product-level."
            ),
        }
    ]

    return pd.DataFrame(metadata)


def merge_outputs(parsed_outputs: List[Dict[str, pd.DataFrame]]) -> Dict[str, pd.DataFrame]:
    result = {}

    sheet_names = [
        "all_brands",
        "made_in_green_brands",
        "standard100_brands",
        "country_summary",
        "standards_summary",
    ]

    for sheet_name in sheet_names:
        frames = [
            output[sheet_name]
            for output in parsed_outputs
            if sheet_name in output and not output[sheet_name].empty
        ]

        if frames:
            df = pd.concat(frames, ignore_index=True)
        else:
            df = pd.DataFrame()

        if sheet_name in {
            "all_brands",
            "made_in_green_brands",
            "standard100_brands",
        } and not df.empty:
            df = df.drop_duplicates(
                subset=[
                    "brand_name_normalized",
                    "website_url",
                    "standards_raw",
                    "country_id",
                ],
                keep="first",
            ).reset_index(drop=True)

            df = df.sort_values(
                [
                    "brand_name_normalized",
                    "country_name_normalized",
                    "website_url",
                ]
            ).reset_index(drop=True)

        result[sheet_name] = df

    if not result["all_brands"].empty:
        result["country_summary"] = build_country_summary(result["all_brands"])
        result["standards_summary"] = build_standards_summary(result["all_brands"])

    return result


def save_outputs(
    output_dir: Path,
    all_brands_df: pd.DataFrame,
    made_in_green_df: pd.DataFrame,
    standard100_df: pd.DataFrame,
    country_summary_df: pd.DataFrame,
    standards_summary_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    made_in_green_csv = output_dir / "oeko_tex_made_in_green_brands.csv"
    all_brands_csv = output_dir / "oeko_tex_all_brands.csv"
    standard100_csv = output_dir / "oeko_tex_standard100_brands.csv"
    countries_csv = output_dir / "oeko_tex_country_summary.csv"
    standards_csv = output_dir / "oeko_tex_standards_summary.csv"
    metadata_csv = output_dir / "oeko_tex_made_in_green_metadata.csv"
    excel_path = output_dir / "oeko_tex_made_in_green_registry.xlsx"

    made_in_green_df.to_csv(made_in_green_csv, index=False, encoding="utf-8-sig")
    all_brands_df.to_csv(all_brands_csv, index=False, encoding="utf-8-sig")
    standard100_df.to_csv(standard100_csv, index=False, encoding="utf-8-sig")
    country_summary_df.to_csv(countries_csv, index=False, encoding="utf-8-sig")
    standards_summary_df.to_csv(standards_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        made_in_green_df.to_excel(writer, sheet_name="made_in_green_brands", index=False)
        all_brands_df.to_excel(writer, sheet_name="all_oeko_tex_brands", index=False)
        standard100_df.to_excel(writer, sheet_name="standard100_brands", index=False)
        country_summary_df.to_excel(writer, sheet_name="country_summary", index=False)
        standards_summary_df.to_excel(writer, sheet_name="standards_summary", index=False)
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)

    print("")
    print("Saved files:")
    print(f"- {made_in_green_csv}")
    print(f"- {all_brands_csv}")
    print(f"- {standard100_csv}")
    print(f"- {countries_csv}")
    print(f"- {standards_csv}")
    print(f"- {metadata_csv}")
    print(f"- {excel_path}")


def build_oeko_tex_made_in_green_registry(
    input_dir: Path,
    output_dir: Path,
    html_path: Optional[Path],
    args: argparse.Namespace,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.download_live:
        downloaded_html = download_live_html(output_dir=output_dir)
        html_files = [downloaded_html]
    else:
        html_files = get_html_files(input_dir=input_dir, explicit_html=html_path)

    print("Building OEKO-TEX MADE IN GREEN registry from directory HTML...")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print(f"HTML files: {len(html_files)}")
    print("")

    parsed_outputs = []

    for current_html_path in html_files:
        print(f"Reading HTML: {current_html_path}")

        html = read_html_file(current_html_path)

        parsed_output = parse_brand_rows_from_html(
            html=html,
            source_file=current_html_path,
        )

        parsed_outputs.append(parsed_output)

        print(f"  All OEKO-TEX brand rows: {len(parsed_output['all_brands'])}")
        print(f"  MADE IN GREEN brand rows: {len(parsed_output['made_in_green_brands'])}")
        print(f"  STANDARD 100 brand rows: {len(parsed_output['standard100_brands'])}")

    merged = merge_outputs(parsed_outputs)

    all_brands_df = merged["all_brands"]
    made_in_green_df = merged["made_in_green_brands"]
    standard100_df = merged["standard100_brands"]
    country_summary_df = merged["country_summary"]
    standards_summary_df = merged["standards_summary"]

    metadata_df = build_metadata(
        html_files=html_files,
        all_brands_df=all_brands_df,
        made_in_green_df=made_in_green_df,
        standard100_df=standard100_df,
        country_summary_df=country_summary_df,
        standards_summary_df=standards_summary_df,
        args=args,
    )

    print("")
    print("Registry summary:")
    print(f"  All OEKO-TEX brand rows: {len(all_brands_df)}")
    print(f"  MADE IN GREEN brand rows: {len(made_in_green_df)}")
    print(f"  STANDARD 100 brand rows: {len(standard100_df)}")
    print(f"  Countries: {len(country_summary_df)}")

    if made_in_green_df.empty:
        print("")
        print("WARNING: No MADE IN GREEN brands were extracted.")
        print("Check that the HTML contains brand elements with data-filterable-standards='mig'.")

    save_outputs(
        output_dir=output_dir,
        all_brands_df=all_brands_df,
        made_in_green_df=made_in_green_df,
        standard100_df=standard100_df,
        country_summary_df=country_summary_df,
        standards_summary_df=standards_summary_df,
        metadata_df=metadata_df,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local OEKO-TEX MADE IN GREEN brand registry from the OEKO-TEX Directory HTML."
        )
    )

    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help=f"Directory containing OEKO-TEX Directory HTML files. Default: {DEFAULT_INPUT_DIR}",
    )

    parser.add_argument(
        "--html",
        default=None,
        help="Optional explicit HTML file path. If omitted, all .html/.htm files in input-dir are processed.",
    )

    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )

    parser.add_argument(
        "--download-live",
        action="store_true",
        help=(
            "Download the live OEKO-TEX Directory page and parse it. "
            "Default: parse local HTML files from input-dir."
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    html_path = Path(args.html) if args.html else None

    build_oeko_tex_made_in_green_registry(
        input_dir=input_dir,
        output_dir=output_dir,
        html_path=html_path,
        args=args,
    )


if __name__ == "__main__":
    main()