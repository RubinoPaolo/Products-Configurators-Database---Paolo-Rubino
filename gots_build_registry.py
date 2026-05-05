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


CERTIFICATION_NAME = "Global Organic Textile Standard"
CERTIFICATION_SHORT_NAME = "GOTS"

SUPPLIERS_URL = "https://global-standard.org/find-suppliers-shops-and-inputs/certifiedsuppliers"

OUTPUT_DIR = Path("data") / "certifications" / "gots"
DEBUG_DIR = OUTPUT_DIR / "debug"

DEFAULT_SUPPLIER_PER_PAGE = 100


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


def extract_total_count(text: str) -> Optional[int]:
    patterns = [
        r"([0-9,]+)\s+entries\s+were\s+found",
        r"([0-9,]+)\s+entry\s+were\s+found",
        r"([0-9,]+)\s+results",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)

        if match:
            return int(match.group(1).replace(",", ""))

    return None


def save_debug_page(page: Page, reason: str, prefix: str = "gots_suppliers") -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "_", reason)

    screenshot_path = DEBUG_DIR / f"{prefix}_{safe_reason}_{timestamp}.png"
    text_path = DEBUG_DIR / f"{prefix}_{safe_reason}_{timestamp}.txt"
    html_path = DEBUG_DIR / f"{prefix}_{safe_reason}_{timestamp}.html"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:
        pass

    try:
        body_text = page.locator("body").inner_text(timeout=5000)
        text_path.write_text(body_text, encoding="utf-8", errors="ignore")
    except Exception:
        pass

    try:
        html_path.write_text(page.content(), encoding="utf-8", errors="ignore")
    except Exception:
        pass


def accept_cookies_if_present(page: Page) -> None:
    cookie_patterns = [
        re.compile(r"allow cookies", flags=re.IGNORECASE),
        re.compile(r"accept", flags=re.IGNORECASE),
        re.compile(r"agree", flags=re.IGNORECASE),
        re.compile(r"allow only selection", flags=re.IGNORECASE),
        re.compile(r"decline", flags=re.IGNORECASE),
        re.compile(r"ok", flags=re.IGNORECASE),
    ]

    for pattern in cookie_patterns:
        try:
            button = page.get_by_role("button", name=pattern).first

            if button.is_visible(timeout=800):
                button.click(timeout=2500)
                time.sleep(0.5)
                return
        except Exception:
            pass

        try:
            link = page.get_by_role("link", name=pattern).first

            if link.is_visible(timeout=800):
                link.click(timeout=2500)
                time.sleep(0.5)
                return
        except Exception:
            pass


def wait_for_supplier_results(page: Page, timeout_ms: int) -> None:
    try:
        page.wait_for_function(
            """
            () => {
              const info = document.querySelector("#csd__info");
              const table = document.querySelector("#csd__dataTable");
              const rows = table ? table.querySelectorAll("tbody tr") : [];
              const bodyText = document.body.innerText || "";

              return (
                info &&
                /entries\\s+were\\s+found/i.test(info.innerText || "") &&
                table &&
                rows.length > 0 &&
                /Company/i.test(bodyText) &&
                /Product Category/i.test(bodyText)
              );
            }
            """,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        save_debug_page(page, "supplier_results_timeout")
        raise


def click_supplier_search_if_needed(page: Page, timeout_ms: int) -> None:
    try:
        if page.locator("#csd__dataTable tbody tr").count() > 0:
            return
    except Exception:
        pass

    try:
        button = page.get_by_role(
            "button",
            name=re.compile(r"search\s+for\s+suppliers|search", flags=re.IGNORECASE),
        ).first

        if button.is_visible(timeout=2000):
            button.click(timeout=5000)

            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass

            wait_for_supplier_results(page, timeout_ms=timeout_ms)
            return
    except Exception:
        pass


def get_supplier_signature(page: Page) -> str:
    try:
        return clean_text(
            page.evaluate(
                """
                () => {
                  const row = document.querySelector("#csd__dataTable tbody tr");

                  if (!row) {
                    return "";
                  }

                  return row.innerText + " " + Array.from(row.querySelectorAll("a[href]"))
                    .map((a) => a.href)
                    .join(" ");
                }
                """
            )
        )
    except Exception:
        return ""


def set_supplier_per_page(page: Page, per_page: int, timeout_ms: int) -> None:
    if per_page <= 0:
        return

    previous_signature = get_supplier_signature(page)

    clicked = page.evaluate(
        """
        ([perPage]) => {
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

          const wanted = String(perPage);

          const candidates = Array.from(
            document.querySelectorAll("#csd__perPageButtons button, #csd__perPageButtons a, button, a")
          )
            .filter(isVisible)
            .filter((element) => {
              const text = (element.innerText || element.textContent || "")
                .replace(/\\s+/g, " ")
                .trim();

              return text === wanted;
            });

          if (candidates.length === 0) {
            return false;
          }

          candidates[0].scrollIntoView({
            block: "center",
            inline: "center"
          });

          candidates[0].click();
          return true;
        }
        """,
        [per_page],
    )

    if not clicked:
        print(f"Could not set suppliers per page to {per_page}. Continuing with default page size.")
        return

    try:
        page.wait_for_function(
            """
            ([oldSignature]) => {
              const row = document.querySelector("#csd__dataTable tbody tr");

              if (!row) {
                return false;
              }

              const current = (row.innerText || "") + " " + Array.from(row.querySelectorAll("a[href]"))
                .map((a) => a.href)
                .join(" ");

              return current.replace(/\\s+/g, " ").trim() !== oldSignature;
            }
            """,
            arg=[previous_signature],
            timeout=timeout_ms,
        )
    except Exception:
        pass

    time.sleep(0.8)


def extract_supplier_rows(page: Page, page_number: int) -> List[Dict[str, object]]:
    raw_rows = page.evaluate(
        """
        () => {
          function cleanText(text) {
            return (text || "")
              .replace(/\\u00a0/g, " ")
              .replace(/\\s+/g, " ")
              .trim();
          }

          function absoluteUrl(href) {
            if (!href) {
              return "";
            }

            try {
              return new URL(href, window.location.href).href;
            } catch {
              return href;
            }
          }

          const table = document.querySelector("#csd__dataTable");

          if (!table) {
            return [];
          }

          const rows = Array.from(table.querySelectorAll("tbody tr"));

          return rows.map((row) => {
            const cells = Array.from(row.querySelectorAll("td"));
            const detailLink = row.querySelector("a[href]");

            return {
              company_name: cleanText(cells[0] ? cells[0].innerText : ""),
              country: cleanText(cells[1] ? cells[1].innerText : ""),
              product_category: cleanText(cells[2] ? cells[2].innerText : ""),
              brand_name: cleanText(cells[3] ? cells[3].innerText : ""),
              detail_url: detailLink ? absoluteUrl(detailLink.getAttribute("href") || "") : "",
              evidence_text: cleanText(row.innerText || "")
            };
          });
        }
        """
    )

    rows = []

    for raw in raw_rows:
        company_name = clean_text(raw.get("company_name", ""))

        if not company_name:
            continue

        country = clean_text(raw.get("country", ""))
        product_category = clean_text(raw.get("product_category", ""))
        brand_name = clean_text(raw.get("brand_name", ""))
        detail_url = clean_text(raw.get("detail_url", ""))

        rows.append(
            {
                "certification": CERTIFICATION_SHORT_NAME,
                "certification_full_name": CERTIFICATION_NAME,
                "registry_section": "Certified Suppliers",
                "registry_source": "GOTS Certified Suppliers Database",
                "registry_match_level": "supplier",
                "page_number": page_number,
                "supplier_key": make_hash_key(
                    company_name,
                    country,
                    product_category,
                    brand_name,
                    detail_url,
                ),
                "company_name": company_name,
                "company_name_normalized": normalize_for_matching(company_name),
                "country": country,
                "country_normalized": normalize_for_matching(country),
                "product_category": product_category,
                "product_category_normalized": normalize_for_matching(product_category),
                "brand_name": brand_name,
                "brand_name_normalized": normalize_for_matching(brand_name),
                "detail_url": detail_url,
                "source_url": SUPPLIERS_URL,
                "evidence_text": clean_text(raw.get("evidence_text", "")),
                "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

    return rows


def deduplicate_rows(rows: List[Dict[str, object]], key_column: str) -> List[Dict[str, object]]:
    seen = set()
    deduped = []

    for row in rows:
        key = clean_text(row.get(key_column, ""))

        if not key:
            key = make_hash_key(*row.values())

        if key in seen:
            continue

        seen.add(key)
        deduped.append(row)

    return deduped


def click_supplier_next_page(page: Page, timeout_ms: int) -> bool:
    previous_signature = get_supplier_signature(page)

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
              element.getAttribute("aria-disabled") === "true" ||
              className.includes("disabled")
            );
          }

          const candidates = Array.from(
            document.querySelectorAll(
              "[aria-label='Next Page'], [aria-label='Next page'], [aria-label*='Next'], button, a"
            )
          )
            .filter(isVisible)
            .filter((element) => !isDisabled(element))
            .map((element) => {
              const text = (element.innerText || element.textContent || "")
                .replace(/\\s+/g, " ")
                .trim();

              const aria = element.getAttribute("aria-label") || "";
              const title = element.getAttribute("title") || "";
              const className = (element.className || "").toString();
              const rect = element.getBoundingClientRect();

              let score = 0;

              if (/next/i.test(`${text} ${aria} ${title} ${className}`)) {
                score += 150;
              }

              if (/›|»|→/.test(text)) {
                score += 120;
              }

              if (element.querySelector("svg")) {
                score += 20;
              }

              if (rect.left > window.innerWidth * 0.45) {
                score += 10;
              }

              if (/details|search|reset|show|100|50|25|15|10/i.test(text)) {
                score -= 120;
              }

              return {
                element,
                score
              };
            })
            .filter((item) => item.score > 0)
            .sort((a, b) => b.score - a.score);

          if (candidates.length === 0) {
            return false;
          }

          candidates[0].element.scrollIntoView({
            block: "center",
            inline: "center"
          });

          candidates[0].element.click();
          return true;
        }
        """
    )

    if not clicked:
        return False

    try:
        page.wait_for_function(
            """
            ([oldSignature]) => {
              const row = document.querySelector("#csd__dataTable tbody tr");

              if (!row) {
                return false;
              }

              const current = (row.innerText || "") + " " + Array.from(row.querySelectorAll("a[href]"))
                .map((a) => a.href)
                .join(" ");

              return current.replace(/\\s+/g, " ").trim() !== oldSignature;
            }
            """,
            arg=[previous_signature],
            timeout=timeout_ms,
        )

        return True

    except Exception:
        new_signature = get_supplier_signature(page)

        if new_signature and new_signature != previous_signature:
            return True

        return False


def save_checkpoint(
    supplier_rows: List[Dict[str, object]],
    scrape_log: List[Dict[str, object]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    suppliers_df = pd.DataFrame(deduplicate_rows(supplier_rows, "supplier_key"))
    scrape_log_df = pd.DataFrame(scrape_log)

    checkpoint_path = output_dir / "gots_registry_CHECKPOINT.xlsx"

    with pd.ExcelWriter(checkpoint_path, engine="openpyxl") as writer:
        suppliers_df.to_excel(writer, sheet_name="certified_suppliers", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print(f"Checkpoint saved: {checkpoint_path}")


def build_supplier_company_summary(suppliers_df: pd.DataFrame) -> pd.DataFrame:
    if suppliers_df.empty:
        return pd.DataFrame()

    summary_df = (
        suppliers_df.groupby(
            [
                "company_name",
                "company_name_normalized",
                "country",
                "country_normalized",
            ],
            dropna=False,
        )
        .agg(
            supplier_rows=("company_name", "count"),
            product_categories=(
                "product_category",
                lambda values: " | ".join(
                    sorted(set(v for v in values if clean_text(v)))[:100]
                ),
            ),
            brand_names=(
                "brand_name",
                lambda values: " | ".join(
                    sorted(set(v for v in values if clean_text(v)))[:100]
                ),
            ),
            detail_urls=(
                "detail_url",
                lambda values: " | ".join(
                    sorted(set(v for v in values if clean_text(v)))[:30]
                ),
            ),
            source_url=("source_url", "first"),
        )
        .reset_index()
    )

    summary_df["certification"] = CERTIFICATION_SHORT_NAME
    summary_df["certification_full_name"] = CERTIFICATION_NAME
    summary_df["registry_section"] = "Certified Supplier Company Summary"
    summary_df["registry_match_level"] = "supplier_company"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['company_name']} appears in {row['supplier_rows']} "
            f"GOTS certified supplier row(s). Product categories: {row['product_categories']}"
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
            "supplier_rows",
            "product_categories",
            "brand_names",
            "detail_urls",
            "source_url",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        ["company_name_normalized", "country_normalized"]
    ).reset_index(drop=True)


def build_metadata(
    suppliers_df: pd.DataFrame,
    supplier_company_summary_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    supplier_total_count: Optional[int],
    args: argparse.Namespace,
) -> pd.DataFrame:
    metadata = [
        {
            "certification": CERTIFICATION_SHORT_NAME,
            "certification_full_name": CERTIFICATION_NAME,
            "source_type": "Dynamic website scraped with Playwright",
            "certified_suppliers_source_url": SUPPLIERS_URL,
            "reported_certified_supplier_entries": supplier_total_count,
            "certified_supplier_rows_extracted": len(suppliers_df),
            "certified_supplier_company_rows": len(supplier_company_summary_df),
            "supplier_per_page": args.supplier_per_page,
            "max_pages_requested": args.max_pages,
            "headless": args.headless,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": (
                "GOTS Certified Suppliers is supplier/entity-level, not direct product-level proof. "
                "For formal verification, GOTS Scope Certificates and Transaction Certificates should be checked."
            ),
        }
    ]

    return pd.DataFrame(metadata)


def save_outputs(
    suppliers_df: pd.DataFrame,
    supplier_company_summary_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    suppliers_csv = output_dir / "gots_certified_suppliers.csv"
    supplier_companies_csv = output_dir / "gots_supplier_company_summary.csv"
    scrape_log_csv = output_dir / "gots_scrape_log.csv"
    metadata_csv = output_dir / "gots_metadata.csv"
    excel_path = output_dir / "gots_registry.xlsx"

    suppliers_df.to_csv(suppliers_csv, index=False, encoding="utf-8-sig")
    supplier_company_summary_df.to_csv(
        supplier_companies_csv,
        index=False,
        encoding="utf-8-sig",
    )
    scrape_log_df.to_csv(scrape_log_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        suppliers_df.to_excel(writer, sheet_name="certified_suppliers", index=False)
        supplier_company_summary_df.to_excel(
            writer,
            sheet_name="supplier_companies",
            index=False,
        )
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print("")
    print("Saved files:")
    print(f"- {suppliers_csv}")
    print(f"- {supplier_companies_csv}")
    print(f"- {metadata_csv}")
    print(f"- {scrape_log_csv}")
    print(f"- {excel_path}")


def scrape_certified_suppliers(
    context: BrowserContext,
    args: argparse.Namespace,
) -> Dict[str, object]:
    page = context.new_page()

    supplier_rows: List[Dict[str, object]] = []
    scrape_log: List[Dict[str, object]] = []
    supplier_total_count: Optional[int] = None

    print("")
    print("Opening GOTS Certified Suppliers Database...")
    print(f"URL: {SUPPLIERS_URL}")

    page.goto(SUPPLIERS_URL, wait_until="domcontentloaded", timeout=args.timeout_ms)

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    accept_cookies_if_present(page)
    click_supplier_search_if_needed(page, timeout_ms=args.timeout_ms)
    wait_for_supplier_results(page, timeout_ms=args.timeout_ms)

    body_text = page.locator("body").inner_text(timeout=args.timeout_ms)
    supplier_total_count = extract_total_count(body_text)

    set_supplier_per_page(
        page=page,
        per_page=args.supplier_per_page,
        timeout_ms=args.timeout_ms,
    )

    wait_for_supplier_results(page, timeout_ms=args.timeout_ms)

    if args.max_pages is not None:
        max_pages = args.max_pages
    elif supplier_total_count and args.supplier_per_page > 0:
        max_pages = math.ceil(supplier_total_count / args.supplier_per_page)
    else:
        max_pages = 10_000

    print(f"Reported supplier entries: {supplier_total_count}")
    print(f"Supplier pages to scrape: {max_pages}")

    for page_number in tqdm(range(1, max_pages + 1), desc="Scraping GOTS suppliers"):
        rows = extract_supplier_rows(page, page_number=page_number)
        supplier_rows.extend(rows)
        supplier_rows = deduplicate_rows(supplier_rows, "supplier_key")

        scrape_log.append(
            {
                "certification": CERTIFICATION_SHORT_NAME,
                "registry_section": "Certified Suppliers",
                "page_number": page_number,
                "rows_extracted_on_page": len(rows),
                "unique_rows_collected": len(supplier_rows),
                "reported_total_count": supplier_total_count,
                "page_url": page.url,
                "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

        print(
            f"Suppliers page {page_number}: rows {len(rows)}, unique collected {len(supplier_rows)}"
        )

        if args.checkpoint_every > 0 and page_number % args.checkpoint_every == 0:
            save_checkpoint(
                supplier_rows=supplier_rows,
                scrape_log=scrape_log,
                output_dir=OUTPUT_DIR,
            )

        if supplier_total_count is not None and len(supplier_rows) >= supplier_total_count:
            print("Supplier reported total reached. Stopping supplier scrape.")
            break

        if page_number < max_pages:
            clicked = click_supplier_next_page(page, timeout_ms=args.timeout_ms)

            if not clicked:
                print(f"Could not move to next suppliers page after page {page_number}.")
                save_debug_page(page, f"supplier_next_failed_page_{page_number}")
                break

            time.sleep(args.page_delay)

    page.close()

    return {
        "rows": supplier_rows,
        "scrape_log": scrape_log,
        "reported_total_count": supplier_total_count,
    }


def build_gots_registry(args: argparse.Namespace) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

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

        print("Building GOTS registry: Certified Suppliers only")
        print(f"Headless: {args.headless}")

        supplier_result = scrape_certified_suppliers(
            context=context,
            args=args,
        )

        context.close()
        browser.close()

    suppliers_df = pd.DataFrame(
        deduplicate_rows(supplier_result["rows"], "supplier_key")
    )

    if not suppliers_df.empty:
        suppliers_df = suppliers_df.sort_values(
            [
                "company_name_normalized",
                "country_normalized",
                "product_category_normalized",
            ]
        ).reset_index(drop=True)

    supplier_company_summary_df = build_supplier_company_summary(suppliers_df)
    scrape_log_df = pd.DataFrame(supplier_result["scrape_log"])

    metadata_df = build_metadata(
        suppliers_df=suppliers_df,
        supplier_company_summary_df=supplier_company_summary_df,
        scrape_log_df=scrape_log_df,
        supplier_total_count=supplier_result["reported_total_count"],
        args=args,
    )

    print("")
    print("Registry summary:")
    print(f"  Certified supplier rows: {len(suppliers_df)}")
    print(f"  Certified supplier company rows: {len(supplier_company_summary_df)}")
    print(f"  Reported supplier entries: {supplier_result['reported_total_count']}")

    save_outputs(
        suppliers_df=suppliers_df,
        supplier_company_summary_df=supplier_company_summary_df,
        scrape_log_df=scrape_log_df,
        metadata_df=metadata_df,
        output_dir=OUTPUT_DIR,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local GOTS registry from the official Certified Suppliers public database."
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
        help="Maximum Certified Suppliers pages to scrape. Default: all estimated pages.",
    )

    parser.add_argument(
        "--supplier-per-page",
        type=int,
        default=DEFAULT_SUPPLIER_PER_PAGE,
        help=f"Supplier rows per page to request. Default: {DEFAULT_SUPPLIER_PER_PAGE}.",
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
        default=0.6,
        help="Delay after changing page, in seconds. Default: 0.6.",
    )

    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=25,
        help="Save checkpoint every N pages. Default: 25.",
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
        default=1600,
        help="Browser viewport width. Default: 1600.",
    )

    parser.add_argument(
        "--viewport-height",
        type=int,
        default=1000,
        help="Browser viewport height. Default: 1000.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_gots_registry(args)


if __name__ == "__main__":
    main()