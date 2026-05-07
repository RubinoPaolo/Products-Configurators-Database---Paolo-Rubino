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


CERTIFICATION_NAME = "PETA-Approved Vegan"
CERTIFICATION_SHORT_NAME = "PETA-Approved Vegan"
REGISTRY_SECTION = "Search PETA-Approved Vegan"

START_URL = "https://petaapprovedvegan.peta.org/search-peta-approved-vegan/"

OUTPUT_DIR = Path("data") / "certifications" / "peta_approved_vegan"
DEBUG_DIR = OUTPUT_DIR / "debug"

EXCEL_ILLEGAL_CHARACTERS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


COMPLIANCE_LABELS = {
    "100-vegan-company": "100% Vegan Company",
    "has-vegan-only-section": "Has Vegan Only Section",
    "has-vegan-options": "Has Vegan Options",
    "offers-fruit-based-leather": "Offers Fruit-Based Leather",
}


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
        return "https://petaapprovedvegan.peta.org" + url

    return url


def extract_domain(url: str) -> str:
    url = clean_text(url)

    if not url:
        return ""

    url = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    url = re.sub(r"^www\.", "", url, flags=re.IGNORECASE)
    return clean_text(url.split("/")[0])


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


def close_popups_if_present(page: Page) -> None:
    button_patterns = [
        re.compile(r"continue\s+to\s+site", flags=re.IGNORECASE),
        re.compile(r"close", flags=re.IGNORECASE),
        re.compile(r"accept", flags=re.IGNORECASE),
        re.compile(r"agree", flags=re.IGNORECASE),
        re.compile(r"ok", flags=re.IGNORECASE),
    ]

    for pattern in button_patterns:
        try:
            button = page.get_by_role("button", name=pattern).first

            if button.is_visible(timeout=700):
                button.click(timeout=2500)
                time.sleep(0.4)
        except Exception:
            continue

    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def wait_for_peta_results(page: Page, timeout_ms: int) -> None:
    try:
        page.wait_for_function(
            """
            () => {
              const text = document.body.innerText || "";
              const hasTitle = /Search\\s+PETA-Approved\\s+Vegan/i.test(text);
              const hasCompanyCount = /\\d+\\s+Companies/i.test(text);

              const resultNodes = document.querySelectorAll(
                ".company-filter h2 a[data-compliance], .company-filter h2 span[title], h2 a[data-compliance], h2 span[title]"
              );

              return hasTitle && hasCompanyCount && resultNodes.length > 0;
            }
            """,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        save_debug_page(page, "wait_for_peta_results_timeout")
        raise


def extract_total_company_count(page: Page) -> Optional[int]:
    try:
        count = page.evaluate(
            """
            () => {
              const countNode = document.querySelector(".company-search__company-count");
              const sourceText = countNode
                ? countNode.innerText || countNode.textContent || ""
                : document.body.innerText || "";

              const match = sourceText.match(/([0-9,]+)\\s+Companies/i);

              if (match) {
                return Number(match[1].replace(/,/g, ""));
              }

              if (window.FWP && window.FWP.settings && window.FWP.settings.pager) {
                const totalRows = window.FWP.settings.pager.total_rows_unfiltered || window.FWP.settings.pager.total_rows;

                if (totalRows) {
                  return Number(totalRows);
                }
              }

              return null;
            }
            """
        )

        if count is None:
            return None

        return int(count)

    except Exception:
        return None


def get_current_page_number(page: Page) -> Optional[int]:
    try:
        current_page = page.evaluate(
            """
            () => {
              const active = document.querySelector("a.facetwp-page.active[data-page]");

              if (active) {
                return Number(active.getAttribute("data-page"));
              }

              if (window.FWP && typeof window.FWP.paged !== "undefined") {
                return Number(window.FWP.paged || 1);
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


def get_total_pages(page: Page, reported_total_count: Optional[int]) -> Optional[int]:
    try:
        total_pages = page.evaluate(
            """
            () => {
              const lastPage = document.querySelector("a.facetwp-page.last[data-page]");

              if (lastPage) {
                const value = Number(lastPage.getAttribute("data-page"));

                if (value > 0) {
                  return value;
                }
              }

              const pageNumbers = Array.from(document.querySelectorAll("a.facetwp-page[data-page]"))
                .map((element) => Number(element.getAttribute("data-page")))
                .filter((value) => Number.isFinite(value) && value > 0);

              if (pageNumbers.length > 0) {
                return Math.max(...pageNumbers);
              }

              if (window.FWP && window.FWP.settings && window.FWP.settings.pager) {
                const totalPages = window.FWP.settings.pager.total_pages;

                if (totalPages) {
                  return Number(totalPages);
                }
              }

              return null;
            }
            """
        )

        if total_pages is not None:
            return int(total_pages)

    except Exception:
        pass

    if reported_total_count:
        return math.ceil(reported_total_count / 30)

    return None


def get_page_signature(page: Page) -> str:
    try:
        return clean_text(
            page.evaluate(
                """
                () => {
                  const nodes = Array.from(document.querySelectorAll(
                    ".company-filter h2 a[data-compliance], .company-filter h2 span[title], h2 a[data-compliance], h2 span[title]"
                  ));

                  return nodes
                    .slice(0, 8)
                    .map((node) => {
                      const title = node.getAttribute("title") || "";
                      const text = (node.innerText || node.textContent || "").replace(/\\s+/g, " ").trim();
                      const href = node.getAttribute("href") || "";
                      return `${title}|${text}|${href}`;
                    })
                    .join(" || ");
                }
                """
            )
        )
    except Exception:
        return ""


def compliance_label_from_code(compliance_code: str) -> str:
    compliance_code = clean_text(compliance_code)
    return COMPLIANCE_LABELS.get(compliance_code, "")


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

          function findResultsRoot() {
            const preferred = [
              ".company-filter__results",
              ".facetwp-template",
              ".company-filter"
            ];

            for (const selector of preferred) {
              const element = document.querySelector(selector);

              if (element) {
                const resultCount = element.querySelectorAll("h2 a[data-compliance], h2 span[title]").length;

                if (resultCount > 0) {
                  return element;
                }
              }
            }

            return document.body;
          }

          const root = findResultsRoot();

          const headingNodes = Array.from(
            root.querySelectorAll("h2")
          )
            .filter(isVisible)
            .filter((heading) => {
              return heading.querySelector("a[data-compliance], span[title]");
            });

          const rows = [];

          for (const heading of headingNodes) {
            const link = heading.querySelector("a[data-compliance]");
            const fallbackSpan = heading.querySelector("span[title]");

            const node = link || fallbackSpan;

            if (!node) {
              continue;
            }

            const rawText = cleanText(heading.innerText || heading.textContent || "");
            const title = cleanText(node.getAttribute("title") || "");
            const href = link ? absoluteUrl(link.getAttribute("href") || "") : "";
            const complianceCode = link ? cleanText(link.getAttribute("data-compliance") || "") : "";

            const veganOptionsNode = heading.querySelector(".vegan-compliance");
            const veganOptionsText = veganOptionsNode
              ? cleanText(veganOptionsNode.innerText || veganOptionsNode.textContent || "")
              : "";

            let companyName = title || rawText;

            companyName = companyName.replace(/Vegan\\s+options\\s+available/ig, "");
            companyName = cleanText(companyName);

            if (!companyName) {
              continue;
            }

            rows.push({
              company_name: companyName,
              website_url: href,
              compliance_code: complianceCode,
              vegan_options_text: veganOptionsText,
              raw_company_text: rawText,
              evidence_text: heading.outerHTML
            });
          }

          return rows;
        }
        """
    )

    rows = []

    for raw in raw_rows:
        company_name = clean_text(raw.get("company_name", ""))

        if not company_name:
            continue

        website_url = absolute_url(clean_text(raw.get("website_url", "")))
        compliance_code = clean_text(raw.get("compliance_code", ""))
        compliance_label = compliance_label_from_code(compliance_code)
        vegan_options_text = clean_text(raw.get("vegan_options_text", ""))
        raw_company_text = clean_text(raw.get("raw_company_text", ""))
        evidence_text = clean_text(raw.get("evidence_text", raw_company_text))

        has_vegan_options_available_label = (
            compliance_code == "has-vegan-options"
            or bool(
                re.search(
                    r"\bVegan\s+options\s+available\b",
                    raw_company_text,
                    flags=re.IGNORECASE,
                )
            )
        )

        row = {
            "certification": CERTIFICATION_SHORT_NAME,
            "certification_full_name": CERTIFICATION_NAME,
            "registry_section": REGISTRY_SECTION,
            "registry_source": "PETA-Approved Vegan search directory",
            "registry_match_level": "company",
            "page_number": page_number,
            "company_name": company_name,
            "company_name_normalized": normalize_for_matching(company_name),
            "website_url": website_url,
            "website_domain": extract_domain(website_url),
            "compliance_code": compliance_code,
            "compliance_label": compliance_label,
            "is_100_vegan_company": compliance_code == "100-vegan-company",
            "has_vegan_only_section": compliance_code == "has-vegan-only-section",
            "has_vegan_options_available_label": has_vegan_options_available_label,
            "offers_fruit_based_leather": compliance_code == "offers-fruit-based-leather",
            "vegan_options_text": vegan_options_text,
            "raw_company_text": raw_company_text,
            "is_linked": bool(website_url),
            "source_url": START_URL,
            "evidence_text": evidence_text,
            "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        row["company_key"] = make_hash_key(
            row["company_name"],
            row["website_url"],
            row["compliance_code"],
        )

        rows.append(row)

    return rows


def deduplicate_rows(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    deduped = []

    for row in rows:
        key = clean_text(row.get("company_key", ""))

        if not key:
            key = make_hash_key(
                row.get("company_name", ""),
                row.get("website_url", ""),
                row.get("compliance_code", ""),
            )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(row)

    return deduped


def go_to_peta_page(page: Page, target_page_number: int, timeout_ms: int) -> bool:
    previous_signature = get_page_signature(page)
    previous_page_number = get_current_page_number(page)

    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(0.2)
    except Exception:
        pass

    navigation_result = page.evaluate(
        """
        ([targetPageNumber]) => {
          function clickVisibleElement(element) {
            if (!element) {
              return false;
            }

            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();

            const visible =
              style &&
              style.display !== "none" &&
              style.visibility !== "hidden" &&
              rect.width > 0 &&
              rect.height > 0;

            if (!visible) {
              return false;
            }

            element.scrollIntoView({
              block: "center",
              inline: "center"
            });

            element.click();

            return true;
          }

          if (window.FWP && typeof window.FWP.refresh === "function") {
            window.FWP.paged = Number(targetPageNumber);
            window.FWP.refresh();

            return {
              method: "FWP.refresh",
              requested_page: targetPageNumber,
              ok: true
            };
          }

          const directLink = document.querySelector(`a.facetwp-page[data-page="${targetPageNumber}"]`);

          if (clickVisibleElement(directLink)) {
            return {
              method: "click_facetwp_page",
              requested_page: targetPageNumber,
              ok: true
            };
          }

          return {
            method: "none",
            requested_page: targetPageNumber,
            ok: false
          };
        }
        """,
        [target_page_number],
    )

    if not navigation_result.get("ok"):
        print(f"Could not request PETA page {target_page_number}: {navigation_result}")
        return False

    try:
        page.wait_for_function(
            """
            ([oldSignature, oldPageNumber, requestedPage]) => {
              const nodes = Array.from(document.querySelectorAll(
                ".company-filter h2 a[data-compliance], .company-filter h2 span[title], h2 a[data-compliance], h2 span[title]"
              ));

              const newSignature = nodes
                .slice(0, 8)
                .map((node) => {
                  const title = node.getAttribute("title") || "";
                  const text = (node.innerText || node.textContent || "").replace(/\\s+/g, " ").trim();
                  const href = node.getAttribute("href") || "";
                  return `${title}|${text}|${href}`;
                })
                .join(" || ");

              let currentPageNumber = null;

              const active = document.querySelector("a.facetwp-page.active[data-page]");

              if (active) {
                currentPageNumber = Number(active.getAttribute("data-page"));
              } else if (window.FWP && typeof window.FWP.paged !== "undefined") {
                currentPageNumber = Number(window.FWP.paged || 1);
              }

              const signatureChanged = newSignature && newSignature !== oldSignature;
              const pageIsRequested = currentPageNumber === Number(requestedPage);
              const pageChanged =
                oldPageNumber === null ||
                currentPageNumber === null ||
                currentPageNumber !== oldPageNumber;

              return signatureChanged || pageIsRequested || pageChanged;
            }
            """,
            arg=[previous_signature, previous_page_number, target_page_number],
            timeout=timeout_ms,
        )

        return True

    except Exception:
        new_signature = get_page_signature(page)
        new_page_number = get_current_page_number(page)

        if new_signature and new_signature != previous_signature:
            return True

        if new_page_number == target_page_number:
            return True

        print(
            "Warning: page request was made but the results did not appear to change. "
            f"Previous page: {previous_page_number}, requested page: {target_page_number}, "
            f"current page: {new_page_number}"
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

    checkpoint_path = output_dir / "peta_approved_vegan_registry_CHECKPOINT.xlsx"

    with pd.ExcelWriter(checkpoint_path, engine="openpyxl") as writer:
        rows_df.to_excel(writer, sheet_name="companies", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print(f"Checkpoint saved: {checkpoint_path}")


def build_compliance_summary(rows_df: pd.DataFrame) -> pd.DataFrame:
    if rows_df.empty:
        return pd.DataFrame()

    summary_df = (
        rows_df.groupby(
            [
                "compliance_code",
                "compliance_label",
            ],
            dropna=False,
        )
        .agg(
            company_rows=("company_key", "count"),
            unique_company_names=("company_name_normalized", "nunique"),
            linked_companies=("is_linked", "sum"),
            company_names=(
                "company_name",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:150]
                ),
            ),
            source_url=("source_url", "first"),
        )
        .reset_index()
    )

    summary_df["certification"] = CERTIFICATION_SHORT_NAME
    summary_df["certification_full_name"] = CERTIFICATION_NAME
    summary_df["registry_section"] = "Compliance Summary"
    summary_df["registry_match_level"] = "compliance_summary"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['company_rows']} company row(s) have compliance_code='{row['compliance_code']}' "
            f"and compliance_label='{row['compliance_label']}'."
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "compliance_code",
            "compliance_label",
            "company_rows",
            "unique_company_names",
            "linked_companies",
            "company_names",
            "source_url",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        [
            "compliance_code",
            "compliance_label",
        ]
    ).reset_index(drop=True)


def build_domain_summary(rows_df: pd.DataFrame) -> pd.DataFrame:
    if rows_df.empty:
        return pd.DataFrame()

    linked_df = rows_df[rows_df["website_domain"].astype(str).str.len() > 0].copy()

    if linked_df.empty:
        return pd.DataFrame()

    summary_df = (
        linked_df.groupby(
            ["website_domain"],
            dropna=False,
        )
        .agg(
            company_rows=("company_key", "count"),
            unique_company_names=("company_name_normalized", "nunique"),
            company_names=(
                "company_name",
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
    summary_df["registry_section"] = "Domain Summary"
    summary_df["registry_match_level"] = "domain_summary"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['website_domain']} appears for {row['company_rows']} company row(s)."
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "website_domain",
            "company_rows",
            "unique_company_names",
            "company_names",
            "source_url",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(["website_domain"]).reset_index(drop=True)


def build_metadata(
    companies_df: pd.DataFrame,
    compliance_summary_df: pd.DataFrame,
    domain_summary_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    reported_total_count: Optional[int],
    detected_total_pages: Optional[int],
    args: argparse.Namespace,
) -> pd.DataFrame:
    metadata = [
        {
            "certification": CERTIFICATION_SHORT_NAME,
            "certification_full_name": CERTIFICATION_NAME,
            "registry_section": REGISTRY_SECTION,
            "source_type": "Dynamic website scraped with Playwright and FacetWP pagination",
            "source_url": START_URL,
            "reported_total_company_count": reported_total_count,
            "company_rows_extracted": len(companies_df),
            "unique_company_names": companies_df["company_name_normalized"].nunique()
            if not companies_df.empty
            else 0,
            "companies_with_website_url": int(companies_df["is_linked"].sum())
            if not companies_df.empty and "is_linked" in companies_df.columns
            else 0,
            "companies_100_vegan": int(companies_df["is_100_vegan_company"].sum())
            if not companies_df.empty and "is_100_vegan_company" in companies_df.columns
            else 0,
            "companies_with_vegan_only_section": int(companies_df["has_vegan_only_section"].sum())
            if not companies_df.empty and "has_vegan_only_section" in companies_df.columns
            else 0,
            "companies_with_vegan_options_label": int(companies_df["has_vegan_options_available_label"].sum())
            if not companies_df.empty and "has_vegan_options_available_label" in companies_df.columns
            else 0,
            "companies_offering_fruit_based_leather": int(companies_df["offers_fruit_based_leather"].sum())
            if not companies_df.empty and "offers_fruit_based_leather" in companies_df.columns
            else 0,
            "compliance_summary_rows": len(compliance_summary_df),
            "domain_summary_rows": len(domain_summary_df),
            "detected_total_pages": detected_total_pages,
            "pages_scraped": int(scrape_log_df["page_number"].max())
            if not scrape_log_df.empty and "page_number" in scrape_log_df.columns
            else 0,
            "max_pages_requested": args.max_pages,
            "headless": args.headless,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": (
                "This registry is company-level. The PETA-Approved Vegan directory lists companies, "
                "not individual certified products. Compliance codes are extracted from each result link's "
                "data-compliance attribute when available."
            ),
        }
    ]

    return pd.DataFrame(metadata)


def save_outputs(
    companies_df: pd.DataFrame,
    compliance_summary_df: pd.DataFrame,
    domain_summary_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    companies_df = sanitize_dataframe_for_excel(companies_df)
    compliance_summary_df = sanitize_dataframe_for_excel(compliance_summary_df)
    domain_summary_df = sanitize_dataframe_for_excel(domain_summary_df)
    scrape_log_df = sanitize_dataframe_for_excel(scrape_log_df)
    metadata_df = sanitize_dataframe_for_excel(metadata_df)

    companies_csv = output_dir / "peta_approved_vegan_companies.csv"
    compliance_summary_csv = output_dir / "peta_approved_vegan_compliance_summary.csv"
    domain_summary_csv = output_dir / "peta_approved_vegan_domain_summary.csv"
    scrape_log_csv = output_dir / "peta_approved_vegan_scrape_log.csv"
    metadata_csv = output_dir / "peta_approved_vegan_metadata.csv"
    excel_path = output_dir / "peta_approved_vegan_registry.xlsx"

    companies_df.to_csv(companies_csv, index=False, encoding="utf-8-sig")
    compliance_summary_df.to_csv(compliance_summary_csv, index=False, encoding="utf-8-sig")
    domain_summary_df.to_csv(domain_summary_csv, index=False, encoding="utf-8-sig")
    scrape_log_df.to_csv(scrape_log_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        companies_df.to_excel(writer, sheet_name="companies", index=False)
        compliance_summary_df.to_excel(writer, sheet_name="compliance_summary", index=False)
        domain_summary_df.to_excel(writer, sheet_name="domain_summary", index=False)
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print("")
    print("Saved files:")
    print(f"- {companies_csv}")
    print(f"- {compliance_summary_csv}")
    print(f"- {domain_summary_csv}")
    print(f"- {metadata_csv}")
    print(f"- {scrape_log_csv}")
    print(f"- {excel_path}")


def build_peta_approved_vegan_registry(args: argparse.Namespace) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    all_rows: List[Dict[str, object]] = []
    scrape_log: List[Dict[str, object]] = []

    reported_total_count: Optional[int] = None
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

        print("Opening PETA-Approved Vegan directory...")
        print(f"Start URL: {START_URL}")
        print(f"Headless: {args.headless}")
        print("")

        page.goto(START_URL, wait_until="domcontentloaded", timeout=args.timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        close_popups_if_present(page)
        wait_for_peta_results(page, timeout_ms=args.timeout_ms)

        reported_total_count = extract_total_company_count(page)
        detected_total_pages = get_total_pages(
            page=page,
            reported_total_count=reported_total_count,
        )

        if args.max_pages is not None:
            max_pages = args.max_pages
        elif detected_total_pages:
            max_pages = detected_total_pages
        elif reported_total_count:
            max_pages = math.ceil(reported_total_count / 30)
        else:
            max_pages = 10000

        print(f"Reported total companies: {reported_total_count}")
        print(f"Detected total pages: {detected_total_pages}")
        print(f"Pages to scrape: {max_pages}")
        print("")

        for loop_index in tqdm(range(1, max_pages + 1), desc="Scraping PETA pages"):
            try:
                close_popups_if_present(page)
                wait_for_peta_results(page, timeout_ms=args.timeout_ms)

                current_page_number = get_current_page_number(page) or loop_index

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
                        "loop_index": loop_index,
                        "rows_extracted_on_page": len(rows),
                        "new_rows_collected": new_rows,
                        "unique_rows_collected": after_count,
                        "reported_total_count": reported_total_count,
                        "detected_total_pages": detected_total_pages,
                        "page_url": page.url,
                        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                )

                print(
                    f"Page {current_page_number}: rows {len(rows)}, "
                    f"new {new_rows}, unique collected {after_count}"
                )

                if args.checkpoint_every > 0 and loop_index % args.checkpoint_every == 0:
                    try:
                        save_checkpoint(
                            rows=all_rows,
                            scrape_log=scrape_log,
                            output_dir=OUTPUT_DIR,
                        )
                    except Exception as checkpoint_error:
                        print(f"Checkpoint warning: {checkpoint_error}")

                if reported_total_count is not None and len(all_rows) >= reported_total_count:
                    print("Reported total company count reached. Stopping.")
                    break

                if loop_index < max_pages:
                    next_page_number = current_page_number + 1

                    moved = go_to_peta_page(
                        page=page,
                        target_page_number=next_page_number,
                        timeout_ms=args.timeout_ms,
                    )

                    if not moved:
                        print(f"Could not move to PETA page {next_page_number}.")
                        save_debug_page(page, f"next_failed_page_{current_page_number}")
                        break

                    time.sleep(args.page_delay)

            except Exception as error:
                print(f"Error on PETA page {loop_index}: {error}")
                save_debug_page(page, f"error_page_{loop_index}")

                if args.stop_on_error:
                    raise

                break

        context.close()
        browser.close()

    companies_df = pd.DataFrame(deduplicate_rows(all_rows))

    if not companies_df.empty:
        companies_df = companies_df.sort_values(
            [
                "company_name_normalized",
                "website_domain",
                "website_url",
                "compliance_code",
            ]
        ).reset_index(drop=True)

    compliance_summary_df = build_compliance_summary(companies_df)
    domain_summary_df = build_domain_summary(companies_df)
    scrape_log_df = pd.DataFrame(scrape_log)

    metadata_df = build_metadata(
        companies_df=companies_df,
        compliance_summary_df=compliance_summary_df,
        domain_summary_df=domain_summary_df,
        scrape_log_df=scrape_log_df,
        reported_total_count=reported_total_count,
        detected_total_pages=detected_total_pages,
        args=args,
    )

    print("")
    print("Registry summary:")
    print(f"  Company rows extracted: {len(companies_df)}")
    print(
        "  Unique company names: "
        f"{companies_df['company_name_normalized'].nunique() if not companies_df.empty else 0}"
    )
    print(
        "  Companies with website URL: "
        f"{int(companies_df['is_linked'].sum()) if not companies_df.empty and 'is_linked' in companies_df.columns else 0}"
    )
    print(
        "  100% vegan companies: "
        f"{int(companies_df['is_100_vegan_company'].sum()) if not companies_df.empty and 'is_100_vegan_company' in companies_df.columns else 0}"
    )
    print(
        "  Companies with vegan options label: "
        f"{int(companies_df['has_vegan_options_available_label'].sum()) if not companies_df.empty and 'has_vegan_options_available_label' in companies_df.columns else 0}"
    )
    print(f"  Reported total company count: {reported_total_count}")
    print(f"  Detected total pages: {detected_total_pages}")

    if companies_df.empty:
        print("")
        print("WARNING: No PETA-Approved Vegan companies were extracted.")
        print(f"Debug files are available in: {DEBUG_DIR}")

    save_outputs(
        companies_df=companies_df,
        compliance_summary_df=compliance_summary_df,
        domain_summary_df=domain_summary_df,
        scrape_log_df=scrape_log_df,
        metadata_df=metadata_df,
        output_dir=OUTPUT_DIR,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local PETA-Approved Vegan company registry from the official directory."
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
        default=0.8,
        help="Delay after changing page, in seconds. Default: 0.8.",
    )

    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=5,
        help="Save checkpoint every N pages. Default: 5.",
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
    build_peta_approved_vegan_registry(args)


if __name__ == "__main__":
    main()