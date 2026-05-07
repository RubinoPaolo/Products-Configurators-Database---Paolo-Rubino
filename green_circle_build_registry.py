import argparse
import hashlib
import math
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from playwright.sync_api import Browser, BrowserContext, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from tqdm import tqdm


CERTIFICATION_NAME = "GreenCircle Certified"
CERTIFICATION_SHORT_NAME = "GreenCircle"
REGISTRY_SECTION = "GreenCircle Certified Product Database"

START_URL = "https://db.greencirclecertified.com/certificate"

OUTPUT_DIR = Path("data") / "certifications" / "green_circle"
DEBUG_DIR = OUTPUT_DIR / "debug"

DEFAULT_RESULTS_PER_PAGE = 25

EXCEL_ILLEGAL_CHARACTERS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def strip_excel_illegal_characters(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = EXCEL_ILLEGAL_CHARACTERS_RE.sub("", text)
    return text


def clean_text(value: object) -> str:
    if value is None:
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


def absolute_url(url: str) -> str:
    url = clean_text(url)

    if not url:
        return ""

    if url.startswith("http://") or url.startswith("https://"):
        return url

    if url.startswith("//"):
        return "https:" + url

    if url.startswith("/"):
        return "https://db.greencirclecertified.com" + url

    return url


def save_debug_page(page: Page, reason: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "_", reason)

    screenshot_path = DEBUG_DIR / f"{safe_reason}_{timestamp}.png"
    text_path = DEBUG_DIR / f"{safe_reason}_{timestamp}.txt"
    html_path = DEBUG_DIR / f"{safe_reason}_{timestamp}.html"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:
        pass

    try:
        body_text = page.locator("body").inner_text(timeout=5000)
        text_path.write_text(clean_text(body_text), encoding="utf-8", errors="ignore")
    except Exception:
        pass

    try:
        html_path.write_text(page.content(), encoding="utf-8", errors="ignore")
    except Exception:
        pass


def accept_cookies_if_present(page: Page) -> None:
    cookie_patterns = [
        re.compile(r"accept", flags=re.IGNORECASE),
        re.compile(r"agree", flags=re.IGNORECASE),
        re.compile(r"allow", flags=re.IGNORECASE),
        re.compile(r"ok", flags=re.IGNORECASE),
        re.compile(r"continue", flags=re.IGNORECASE),
        re.compile(r"reject", flags=re.IGNORECASE),
    ]

    for pattern in cookie_patterns:
        try:
            button = page.get_by_role("button", name=pattern).first

            if button.is_visible(timeout=800):
                button.click(timeout=2500)
                time.sleep(0.5)
                return
        except Exception:
            continue


def wait_for_green_circle_table(page: Page, timeout_ms: int) -> None:
    try:
        page.wait_for_function(
            """
            () => {
              const bodyText = document.body.innerText || "";
              const rows = document.querySelectorAll("tbody tr");

              const hasHeaders =
                /Certificate/i.test(bodyText) &&
                /Company/i.test(bodyText) &&
                /Product/i.test(bodyText) &&
                /Certification/i.test(bodyText) &&
                /Expiration/i.test(bodyText);

              return hasHeaders && rows.length > 0;
            }
            """,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        save_debug_page(page, "wait_for_green_circle_table_timeout")
        raise


def get_current_page_number(page: Page) -> Optional[int]:
    try:
        current_page = page.evaluate(
            """
            () => {
              const activeSelectors = [
                ".ant-pagination-item-active",
                "li[aria-current='page']",
                "[aria-current='page']"
              ];

              for (const selector of activeSelectors) {
                const element = document.querySelector(selector);

                if (element) {
                  const text = (element.innerText || element.textContent || "")
                    .replace(/\\s+/g, " ")
                    .trim();

                  const match = text.match(/\\d+/);

                  if (match) {
                    return Number(match[0]);
                  }
                }
              }

              return null;
            }
            """
        )

        if current_page is None:
            return None

        return int(current_page)

    except Exception:
        return None


def get_total_pages(page: Page) -> Optional[int]:
    try:
        total_pages = page.evaluate(
            """
            () => {
              const candidates = Array.from(
                document.querySelectorAll(
                  ".ant-pagination-item, .ant-pagination-item-link, li, button, a"
                )
              );

              const numbers = [];

              for (const element of candidates) {
                const text = (element.innerText || element.textContent || "")
                  .replace(/\\s+/g, " ")
                  .trim();

                if (/^\\d+$/.test(text)) {
                  numbers.push(Number(text));
                }

                const title = element.getAttribute("title") || "";

                if (/^\\d+$/.test(title.trim())) {
                  numbers.push(Number(title.trim()));
                }
              }

              if (numbers.length === 0) {
                return null;
              }

              return Math.max(...numbers);
            }
            """
        )

        if total_pages is None:
            return None

        return int(total_pages)

    except Exception:
        return None


def get_page_signature(page: Page) -> str:
    try:
        return clean_text(
            page.evaluate(
                """
                () => {
                  const row = document.querySelector("tbody tr");

                  if (!row) {
                    return "";
                  }

                  return row.innerText || row.textContent || "";
                }
                """
            )
        )
    except Exception:
        return ""


def extract_visible_rows(page: Page, page_number: int) -> List[Dict[str, object]]:
    raw_rows = page.evaluate(
        """
        () => {
          function cleanText(text) {
            return (text || "")
              .replace(/\\u00a0/g, " ")
              .replace(/\\s+/g, " ")
              .trim();
          }

          function absoluteUrl(url) {
            if (!url) return "";

            try {
              return new URL(url, window.location.href).href;
            } catch {
              return url;
            }
          }

          function getDownloadUrl(row) {
            const links = Array.from(row.querySelectorAll("a[href]"));

            for (const link of links) {
              const href = link.getAttribute("href") || "";

              if (!href) {
                continue;
              }

              return absoluteUrl(href);
            }

            const buttons = Array.from(row.querySelectorAll("button"));

            for (const button of buttons) {
              const aria = button.getAttribute("aria-label") || "";
              const title = button.getAttribute("title") || "";

              if (/download/i.test(`${aria} ${title}`)) {
                return "";
              }
            }

            return "";
          }

          const rows = Array.from(document.querySelectorAll("tbody tr"));

          return rows.map((row) => {
            const cells = Array.from(row.querySelectorAll("td"));

            return {
              certificate_id: cleanText(cells[0] ? cells[0].innerText : ""),
              company_name: cleanText(cells[1] ? cells[1].innerText : ""),
              product_name: cleanText(cells[2] ? cells[2].innerText : ""),
              product_type: cleanText(cells[3] ? cells[3].innerText : ""),
              certification_claim: cleanText(cells[4] ? cells[4].innerText : ""),
              effective_date: cleanText(cells[5] ? cells[5].innerText : ""),
              expiration_date: cleanText(cells[6] ? cells[6].innerText : ""),
              location: cleanText(cells[7] ? cells[7].innerText : ""),
              download_url: getDownloadUrl(row),
              evidence_text: cleanText(row.innerText || row.textContent || "")
            };
          });
        }
        """
    )

    rows = []

    for raw in raw_rows:
        certificate_id = clean_text(raw.get("certificate_id", ""))
        company_name = clean_text(raw.get("company_name", ""))
        product_name = clean_text(raw.get("product_name", ""))

        if not certificate_id and not company_name and not product_name:
            continue

        product_type = clean_text(raw.get("product_type", ""))
        certification_claim = clean_text(raw.get("certification_claim", ""))
        effective_date = clean_text(raw.get("effective_date", ""))
        expiration_date = clean_text(raw.get("expiration_date", ""))
        location = clean_text(raw.get("location", ""))
        download_url = absolute_url(clean_text(raw.get("download_url", "")))
        evidence_text = clean_text(raw.get("evidence_text", ""))

        row = {
            "certification": CERTIFICATION_SHORT_NAME,
            "certification_full_name": CERTIFICATION_NAME,
            "registry_section": REGISTRY_SECTION,
            "registry_source": "GreenCircle Certified Product Database",
            "registry_match_level": "product_certificate",
            "page_number": page_number,
            "certificate_id": certificate_id,
            "certificate_id_normalized": normalize_for_matching(certificate_id),
            "company_name": company_name,
            "company_name_normalized": normalize_for_matching(company_name),
            "product_name": product_name,
            "product_name_normalized": normalize_for_matching(product_name),
            "product_type": product_type,
            "product_type_normalized": normalize_for_matching(product_type),
            "certification_claim": certification_claim,
            "certification_claim_normalized": normalize_for_matching(certification_claim),
            "effective_date": effective_date,
            "expiration_date": expiration_date,
            "location": location,
            "location_normalized": normalize_for_matching(location),
            "download_url": download_url,
            "source_url": START_URL,
            "evidence_text": evidence_text,
            "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        row["record_key"] = make_hash_key(
            row["certificate_id"],
            row["company_name"],
            row["product_name"],
            row["product_type"],
            row["certification_claim"],
            row["effective_date"],
            row["expiration_date"],
            row["location"],
        )

        rows.append(row)

    return rows


def deduplicate_rows(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    deduped = []

    for row in rows:
        key = clean_text(row.get("record_key", ""))

        if not key:
            key = make_hash_key(
                row.get("certificate_id", ""),
                row.get("company_name", ""),
                row.get("product_name", ""),
                row.get("product_type", ""),
                row.get("certification_claim", ""),
                row.get("effective_date", ""),
                row.get("expiration_date", ""),
                row.get("location", ""),
            )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(row)

    return deduped


def click_next_page(page: Page, timeout_ms: int) -> bool:
    previous_signature = get_page_signature(page)
    previous_page_number = get_current_page_number(page)

    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(0.3)
    except Exception:
        pass

    clicked = page.evaluate(
        """
        () => {
          function isVisible(element) {
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();

            return (
              style &&
              style.display !== "none" &&
              style.visibility !== "hidden" &&
              rect.width > 0 &&
              rect.height > 0
            );
          }

          function isDisabled(element) {
            const className = (element.className || "").toString().toLowerCase();

            return (
              element.disabled === true ||
              element.getAttribute("disabled") !== null ||
              element.getAttribute("aria-disabled") === "true" ||
              className.includes("disabled")
            );
          }

          const directSelectors = [
            ".ant-pagination-next button",
            ".ant-pagination-next",
            "li[title='Next Page'] button",
            "li[title='Next Page']",
            "button[aria-label='next']",
            "button[aria-label='Next']"
          ];

          for (const selector of directSelectors) {
            const element = document.querySelector(selector);

            if (element && isVisible(element) && !isDisabled(element)) {
              element.scrollIntoView({
                block: "center",
                inline: "center"
              });

              element.click();

              return {
                clicked: true,
                reason: "direct_selector",
                selector
              };
            }
          }

          const elements = Array.from(
            document.querySelectorAll("button, a, li, [role='button']")
          )
            .filter(isVisible)
            .filter((element) => !isDisabled(element));

          const candidates = elements.map((element) => {
            const text = (element.innerText || element.textContent || "")
              .replace(/\\s+/g, " ")
              .trim();

            const aria = element.getAttribute("aria-label") || "";
            const title = element.getAttribute("title") || "";
            const className = (element.className || "").toString();
            const rect = element.getBoundingClientRect();

            let score = 0;

            if (/next/i.test(`${text} ${aria} ${title} ${className}`)) {
              score += 160;
            }

            if (/›|»|→/.test(text)) {
              score += 130;
            }

            if (element.querySelector("svg")) {
              score += 25;
            }

            if (rect.left > window.innerWidth * 0.45) {
              score += 20;
            }

            if (/previous|sign in|download|certificate|company|product|search|sort|page/i.test(text)) {
              score -= 80;
            }

            if (/^\\d+$/.test(text)) {
              score -= 80;
            }

            return {
              element,
              score,
              text,
              aria,
              title,
              className,
              x: rect.x,
              y: rect.y,
              width: rect.width,
              height: rect.height
            };
          })
          .filter((item) => item.score > 0)
          .sort((a, b) => b.score - a.score);

          if (candidates.length === 0) {
            return {
              clicked: false,
              reason: "candidate_not_found"
            };
          }

          const chosen = candidates[0];

          chosen.element.scrollIntoView({
            block: "center",
            inline: "center"
          });

          chosen.element.click();

          return {
            clicked: true,
            reason: "scored_candidate",
            candidate: {
              score: chosen.score,
              text: chosen.text,
              aria: chosen.aria,
              title: chosen.title,
              className: chosen.className,
              x: chosen.x,
              y: chosen.y,
              width: chosen.width,
              height: chosen.height
            }
          };
        }
        """
    )

    if not clicked.get("clicked"):
        print(f"Next page button not clicked: {clicked}")
        return False

    try:
        page.wait_for_function(
            """
            ([oldSignature, oldPageNumber]) => {
              const row = document.querySelector("tbody tr");
              const newSignature = row ? (row.innerText || row.textContent || "").replace(/\\s+/g, " ").trim() : "";

              let currentPageNumber = null;

              const active = document.querySelector(".ant-pagination-item-active, li[aria-current='page'], [aria-current='page']");

              if (active) {
                const text = (active.innerText || active.textContent || "").replace(/\\s+/g, " ").trim();
                const match = text.match(/\\d+/);

                if (match) {
                  currentPageNumber = Number(match[0]);
                }
              }

              const signatureChanged = newSignature && newSignature !== oldSignature;
              const pageChanged =
                oldPageNumber === null ||
                currentPageNumber === null ||
                currentPageNumber !== oldPageNumber;

              return signatureChanged || pageChanged;
            }
            """,
            arg=[previous_signature, previous_page_number],
            timeout=timeout_ms,
        )

        return True

    except Exception:
        new_signature = get_page_signature(page)
        new_page_number = get_current_page_number(page)

        if new_signature and new_signature != previous_signature:
            return True

        if (
            previous_page_number is not None
            and new_page_number is not None
            and previous_page_number != new_page_number
        ):
            return True

        print(
            "Warning: next was clicked but page did not appear to change. "
            f"Previous page: {previous_page_number}, new page: {new_page_number}"
        )

        return False


def save_checkpoint(
    rows: List[Dict[str, object]],
    scrape_log: List[Dict[str, object]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows_df = sanitize_dataframe_for_excel(pd.DataFrame(deduplicate_rows(rows)))
    scrape_log_df = sanitize_dataframe_for_excel(pd.DataFrame(scrape_log))

    checkpoint_path = output_dir / "green_circle_registry_CHECKPOINT.xlsx"

    with pd.ExcelWriter(checkpoint_path, engine="openpyxl") as writer:
        rows_df.to_excel(writer, sheet_name="products", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print(f"Checkpoint saved: {checkpoint_path}")


def build_company_summary(rows_df: pd.DataFrame) -> pd.DataFrame:
    if rows_df.empty:
        return pd.DataFrame()

    summary_df = (
        rows_df.groupby(
            [
                "company_name",
                "company_name_normalized",
                "location",
                "location_normalized",
            ],
            dropna=False,
        )
        .agg(
            green_circle_rows=("record_key", "count"),
            unique_certificates=("certificate_id_normalized", "nunique"),
            products=(
                "product_name",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:120]
                ),
            ),
            product_types=(
                "product_type",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:80]
                ),
            ),
            certification_claims=(
                "certification_claim",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:80]
                ),
            ),
            certificate_ids=(
                "certificate_id",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:80]
                ),
            ),
            source_url=("source_url", "first"),
        )
        .reset_index()
    )

    summary_df["certification"] = CERTIFICATION_SHORT_NAME
    summary_df["certification_full_name"] = CERTIFICATION_NAME
    summary_df["registry_section"] = "Company Summary"
    summary_df["registry_match_level"] = "company"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['company_name']} appears in {row['green_circle_rows']} GreenCircle product row(s), "
            f"with {row['unique_certificates']} unique certificate id(s)."
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
            "location",
            "location_normalized",
            "green_circle_rows",
            "unique_certificates",
            "certificate_ids",
            "products",
            "product_types",
            "certification_claims",
            "source_url",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        [
            "company_name_normalized",
            "location_normalized",
        ]
    ).reset_index(drop=True)


def build_certification_claim_summary(rows_df: pd.DataFrame) -> pd.DataFrame:
    if rows_df.empty:
        return pd.DataFrame()

    summary_df = (
        rows_df.groupby(
            [
                "certification_claim",
                "certification_claim_normalized",
            ],
            dropna=False,
        )
        .agg(
            product_rows=("record_key", "count"),
            unique_companies=("company_name_normalized", "nunique"),
            unique_certificates=("certificate_id_normalized", "nunique"),
            product_types=(
                "product_type",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:100]
                ),
            ),
            company_names=(
                "company_name",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:120]
                ),
            ),
            source_url=("source_url", "first"),
        )
        .reset_index()
    )

    summary_df["certification"] = CERTIFICATION_SHORT_NAME
    summary_df["certification_full_name"] = CERTIFICATION_NAME
    summary_df["registry_section"] = "Certification Claim Summary"
    summary_df["registry_match_level"] = "certification_claim"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['certification_claim']} appears in {row['product_rows']} GreenCircle product row(s), "
            f"covering {row['unique_companies']} unique company name(s)."
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "certification_claim",
            "certification_claim_normalized",
            "product_rows",
            "unique_companies",
            "unique_certificates",
            "product_types",
            "company_names",
            "source_url",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        ["certification_claim_normalized"]
    ).reset_index(drop=True)


def build_product_type_summary(rows_df: pd.DataFrame) -> pd.DataFrame:
    if rows_df.empty:
        return pd.DataFrame()

    summary_df = (
        rows_df.groupby(
            [
                "product_type",
                "product_type_normalized",
            ],
            dropna=False,
        )
        .agg(
            product_rows=("record_key", "count"),
            unique_companies=("company_name_normalized", "nunique"),
            certification_claims=(
                "certification_claim",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:80]
                ),
            ),
            company_names=(
                "company_name",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:120]
                ),
            ),
            source_url=("source_url", "first"),
        )
        .reset_index()
    )

    summary_df["certification"] = CERTIFICATION_SHORT_NAME
    summary_df["certification_full_name"] = CERTIFICATION_NAME
    summary_df["registry_section"] = "Product Type Summary"
    summary_df["registry_match_level"] = "product_type"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['product_type']} appears in {row['product_rows']} GreenCircle product row(s), "
            f"covering {row['unique_companies']} unique company name(s)."
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "product_type",
            "product_type_normalized",
            "product_rows",
            "unique_companies",
            "certification_claims",
            "company_names",
            "source_url",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        ["product_type_normalized"]
    ).reset_index(drop=True)


def build_metadata(
    rows_df: pd.DataFrame,
    companies_df: pd.DataFrame,
    claim_summary_df: pd.DataFrame,
    type_summary_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    detected_total_pages: Optional[int],
    args: argparse.Namespace,
) -> pd.DataFrame:
    metadata = [
        {
            "certification": CERTIFICATION_SHORT_NAME,
            "certification_full_name": CERTIFICATION_NAME,
            "registry_section": REGISTRY_SECTION,
            "source_type": "Dynamic website scraped with Playwright",
            "source_url": START_URL,
            "product_certificate_rows_extracted": len(rows_df),
            "company_summary_rows": len(companies_df),
            "certification_claim_summary_rows": len(claim_summary_df),
            "product_type_summary_rows": len(type_summary_df),
            "detected_total_pages": detected_total_pages,
            "pages_scraped": int(scrape_log_df["page_number"].max())
            if not scrape_log_df.empty and "page_number" in scrape_log_df.columns
            else 0,
            "max_pages_requested": args.max_pages,
            "headless": args.headless,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": (
                "This GreenCircle registry is product/certificate-level and is built from "
                "the public GreenCircle Certified Product Database. Download URLs are captured "
                "when directly available in the table DOM."
            ),
        }
    ]

    return pd.DataFrame(metadata)


def save_outputs(
    rows_df: pd.DataFrame,
    companies_df: pd.DataFrame,
    claim_summary_df: pd.DataFrame,
    type_summary_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows_df = sanitize_dataframe_for_excel(rows_df)
    companies_df = sanitize_dataframe_for_excel(companies_df)
    claim_summary_df = sanitize_dataframe_for_excel(claim_summary_df)
    type_summary_df = sanitize_dataframe_for_excel(type_summary_df)
    scrape_log_df = sanitize_dataframe_for_excel(scrape_log_df)
    metadata_df = sanitize_dataframe_for_excel(metadata_df)

    products_csv = output_dir / "green_circle_products.csv"
    companies_csv = output_dir / "green_circle_companies.csv"
    claims_csv = output_dir / "green_circle_certification_claims.csv"
    types_csv = output_dir / "green_circle_product_types.csv"
    scrape_log_csv = output_dir / "green_circle_scrape_log.csv"
    metadata_csv = output_dir / "green_circle_metadata.csv"
    excel_path = output_dir / "green_circle_registry.xlsx"

    rows_df.to_csv(products_csv, index=False, encoding="utf-8-sig")
    companies_df.to_csv(companies_csv, index=False, encoding="utf-8-sig")
    claim_summary_df.to_csv(claims_csv, index=False, encoding="utf-8-sig")
    type_summary_df.to_csv(types_csv, index=False, encoding="utf-8-sig")
    scrape_log_df.to_csv(scrape_log_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        rows_df.to_excel(writer, sheet_name="products", index=False)
        companies_df.to_excel(writer, sheet_name="companies", index=False)
        claim_summary_df.to_excel(writer, sheet_name="certification_claims", index=False)
        type_summary_df.to_excel(writer, sheet_name="product_types", index=False)
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print("")
    print("Saved files:")
    print(f"- {products_csv}")
    print(f"- {companies_csv}")
    print(f"- {claims_csv}")
    print(f"- {types_csv}")
    print(f"- {metadata_csv}")
    print(f"- {scrape_log_csv}")
    print(f"- {excel_path}")


def build_green_circle_registry(args: argparse.Namespace) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    all_rows: List[Dict[str, object]] = []
    scrape_log: List[Dict[str, object]] = []

    detected_total_pages: Optional[int] = None

    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(
            headless=args.headless,
            slow_mo=args.slow_mo,
        )

        context: BrowserContext = browser.new_context(
            viewport={
                "width": args.viewport_width,
                "height": args.viewport_height,
            },
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            locale="en-US",
        )

        page: Page = context.new_page()

        print("Opening GreenCircle Certified Product Database...")
        print(f"Start URL: {START_URL}")
        print(f"Headless: {args.headless}")
        print("")

        page.goto(START_URL, wait_until="domcontentloaded", timeout=args.timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        accept_cookies_if_present(page)
        wait_for_green_circle_table(page, timeout_ms=args.timeout_ms)

        detected_total_pages = get_total_pages(page)

        if args.max_pages is not None:
            max_pages = args.max_pages
        elif detected_total_pages:
            max_pages = detected_total_pages
        else:
            max_pages = 10000

        print(f"Detected total pages: {detected_total_pages}")
        print(f"Pages to scrape: {max_pages}")
        print("")

        for page_index in tqdm(range(1, max_pages + 1), desc="Scraping GreenCircle pages"):
            try:
                wait_for_green_circle_table(page, timeout_ms=args.timeout_ms)

                current_page_number = get_current_page_number(page) or page_index

                rows = extract_visible_rows(
                    page=page,
                    page_number=current_page_number,
                )

                before_count = len(all_rows)

                all_rows.extend(rows)
                all_rows = deduplicate_rows(all_rows)

                after_count = len(all_rows)
                new_rows = after_count - before_count

                scrape_log.append(
                    {
                        "certification": CERTIFICATION_SHORT_NAME,
                        "registry_section": REGISTRY_SECTION,
                        "page_number": current_page_number,
                        "loop_index": page_index,
                        "rows_extracted_on_page": len(rows),
                        "new_rows_collected": new_rows,
                        "unique_rows_collected": after_count,
                        "detected_total_pages": detected_total_pages,
                        "page_url": page.url,
                        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                )

                print(
                    f"Page {current_page_number}: rows {len(rows)}, "
                    f"new {new_rows}, unique collected {after_count}"
                )

                if args.checkpoint_every > 0 and page_index % args.checkpoint_every == 0:
                    try:
                        save_checkpoint(
                            rows=all_rows,
                            scrape_log=scrape_log,
                            output_dir=OUTPUT_DIR,
                        )
                    except Exception as checkpoint_error:
                        print(f"Checkpoint warning: {checkpoint_error}")

                if page_index < max_pages:
                    clicked = click_next_page(page, timeout_ms=args.timeout_ms)

                    if not clicked:
                        print(f"Could not move to next GreenCircle page after page {current_page_number}.")
                        save_debug_page(page, f"next_failed_page_{current_page_number}")
                        break

                    time.sleep(args.page_delay)

            except Exception as error:
                print(f"Error on GreenCircle page {page_index}: {error}")
                save_debug_page(page, f"error_page_{page_index}")

                if args.stop_on_error:
                    raise

                break

        context.close()
        browser.close()

    rows_df = pd.DataFrame(deduplicate_rows(all_rows))

    if not rows_df.empty:
        rows_df = rows_df.sort_values(
            [
                "company_name_normalized",
                "product_name_normalized",
                "certificate_id_normalized",
            ]
        ).reset_index(drop=True)

    companies_df = build_company_summary(rows_df)
    claim_summary_df = build_certification_claim_summary(rows_df)
    type_summary_df = build_product_type_summary(rows_df)
    scrape_log_df = pd.DataFrame(scrape_log)

    metadata_df = build_metadata(
        rows_df=rows_df,
        companies_df=companies_df,
        claim_summary_df=claim_summary_df,
        type_summary_df=type_summary_df,
        scrape_log_df=scrape_log_df,
        detected_total_pages=detected_total_pages,
        args=args,
    )

    print("")
    print("Registry summary:")
    print(f"  Product/certificate rows extracted: {len(rows_df)}")
    print(f"  Company summary rows: {len(companies_df)}")
    print(f"  Certification claim summary rows: {len(claim_summary_df)}")
    print(f"  Product type summary rows: {len(type_summary_df)}")
    print(f"  Detected total pages: {detected_total_pages}")

    if rows_df.empty:
        print("")
        print("WARNING: No GreenCircle rows were extracted.")
        print(f"Debug files are available in: {DEBUG_DIR}")

    save_outputs(
        rows_df=rows_df,
        companies_df=companies_df,
        claim_summary_df=claim_summary_df,
        type_summary_df=type_summary_df,
        scrape_log_df=scrape_log_df,
        metadata_df=metadata_df,
        output_dir=OUTPUT_DIR,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local GreenCircle Certified product registry from the public "
            "GreenCircle Certified Product Database."
        )
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium in headless mode. Default: visible browser.",
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum pages to scrape. Default: detected total pages.",
    )

    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Timeout in milliseconds. Default: 30000.",
    )

    parser.add_argument(
        "--page-delay",
        type=float,
        default=0.7,
        help="Delay after changing page, in seconds. Default: 0.7.",
    )

    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=10,
        help="Save checkpoint every N pages. Default: 10.",
    )

    parser.add_argument(
        "--slow-mo",
        type=int,
        default=0,
        help="Playwright slow motion in milliseconds. Default: 0.",
    )

    parser.add_argument(
        "--viewport-width",
        type=int,
        default=1800,
        help="Browser viewport width. Default: 1800.",
    )

    parser.add_argument(
        "--viewport-height",
        type=int,
        default=1000,
        help="Browser viewport height. Default: 1000.",
    )

    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop immediately if a page fails.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_green_circle_registry(args)


if __name__ == "__main__":
    main()