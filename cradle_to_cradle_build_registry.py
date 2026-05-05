import argparse
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import pandas as pd
from playwright.sync_api import Browser, BrowserContext, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from tqdm import tqdm


CERTIFICATION_NAME = "Cradle to Cradle Certified"
REGISTRY_SECTION = "Certified Products"
BASE_URL = "https://c2ccertified.org"
START_URL = "https://c2ccertified.org/certified-products"

OUTPUT_DIR = Path("data") / "certifications" / "cradle_to_cradle"
DEBUG_DIR = OUTPUT_DIR / "debug"

DEFAULT_MAX_PAGES = 52

CERTIFICATION_TYPE_RE = re.compile(
    r"C2C\s*Certified®?\s*(Full Scope|Material Health|Circularity)?",
    flags=re.IGNORECASE,
)

LEVEL_RE = re.compile(r"\b(Bronze|Silver|Gold|Platinum)\b", flags=re.IGNORECASE)
VERSION_RE = re.compile(r"\bversion\s*([0-9.]+)", flags=re.IGNORECASE)
CERTIFICATE_NUMBER_RE = re.compile(
    r"\bCertification Number\s+([0-9]+)\b",
    flags=re.IGNORECASE,
)
VALID_UNTIL_RE = re.compile(
    r"\bValid Until\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})\b",
    flags=re.IGNORECASE,
)


def clean_text(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_multiline_text(value: object) -> str:
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("\ufeff", "")
    lines = [clean_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def normalize_for_matching(value: object) -> str:
    text = clean_text(value).casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def absolute_url(href: str) -> str:
    return urljoin(BASE_URL, href)


def safe_slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return path.split("/")[-1] if path else ""


def extract_result_count(text: str) -> Optional[int]:
    match = re.search(r"\b([0-9,]+)\s+results\b", text, flags=re.IGNORECASE)

    if not match:
        return None

    return int(match.group(1).replace(",", ""))


def extract_level_and_version(certification_text: str) -> Dict[str, str]:
    level_match = LEVEL_RE.search(certification_text)
    version_match = VERSION_RE.search(certification_text)
    type_match = CERTIFICATION_TYPE_RE.search(certification_text)

    certification_type = ""
    certification_level = ""
    certification_version = ""

    if type_match:
        raw_type = clean_text(type_match.group(1))
        certification_type = raw_type if raw_type else "General"

    if level_match:
        certification_level = level_match.group(1).title()

    if version_match:
        certification_version = version_match.group(1)

    return {
        "certification_type": certification_type,
        "certification_level": certification_level,
        "certification_version": certification_version,
    }


def split_certification_texts(raw_certification_texts: List[str]) -> Dict[str, str]:
    certification_types = []
    certification_levels = []
    certification_versions = []
    certification_texts = []

    for raw_text in raw_certification_texts:
        text = clean_text(raw_text)

        if not text:
            continue

        parsed = extract_level_and_version(text)

        if parsed["certification_type"]:
            certification_types.append(parsed["certification_type"])

        if parsed["certification_level"]:
            certification_levels.append(parsed["certification_level"])

        if parsed["certification_version"]:
            certification_versions.append(parsed["certification_version"])

        certification_texts.append(text)

    return {
        "certification_types": " | ".join(dict.fromkeys(certification_types)),
        "certification_levels": " | ".join(dict.fromkeys(certification_levels)),
        "certification_versions": " | ".join(dict.fromkeys(certification_versions)),
        "certification_text": " | ".join(dict.fromkeys(certification_texts)),
    }


def get_first_product_url(page: Page) -> str:
    try:
        return clean_text(
            page.evaluate(
                """
                () => {
                  const first = document.querySelector("a.listinline[href]");
                  if (!first) return "";
                  return new URL(first.getAttribute("href"), "https://c2ccertified.org").href;
                }
                """
            )
        )
    except Exception:
        return ""


def get_current_visible_page_number(page: Page) -> Optional[int]:
    try:
        value = page.evaluate(
            """
            () => {
              const pagination = document.querySelector(".certified-products__pagination");
              if (!pagination) return null;

              const candidates = Array.from(
                pagination.querySelectorAll("button, a, span, div")
              );

              for (const element of candidates) {
                const text = (element.innerText || element.textContent || "")
                  .replace(/\\s+/g, " ")
                  .trim();

                const className = (element.className || "").toString().toLowerCase();
                const ariaCurrent = element.getAttribute("aria-current");

                if (/^\\d+$/.test(text)) {
                  const isActive =
                    ariaCurrent === "page" ||
                    className.includes("active") ||
                    className.includes("current") ||
                    className.includes("selected");

                  if (isActive) {
                    return Number(text);
                  }
                }
              }

              return null;
            }
            """
        )

        if value is None:
            return None

        return int(value)

    except Exception:
        return None


def accept_cookies_if_present(page: Page) -> None:
    cookie_patterns = [
        re.compile(r"accept", flags=re.IGNORECASE),
        re.compile(r"agree", flags=re.IGNORECASE),
        re.compile(r"allow", flags=re.IGNORECASE),
        re.compile(r"ok", flags=re.IGNORECASE),
        re.compile(r"reject", flags=re.IGNORECASE),
    ]

    for pattern in cookie_patterns:
        try:
            button = page.get_by_role("button", name=pattern).first

            if button.is_visible(timeout=800):
                button.click(timeout=2000)
                time.sleep(0.6)
                return
        except Exception:
            continue


def wait_for_products(page: Page, page_number: int, timeout_ms: int) -> None:
    try:
        page.wait_for_function(
            """
            () => {
              const text = document.body.innerText || "";
              const cards = document.querySelectorAll("a.listinline[href]");
              return /\\b\\d+\\s+results\\b/i.test(text) && cards.length > 0;
            }
            """,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        save_debug_page(page, page_number, "wait_for_products_timeout")
        raise


def save_debug_page(page: Page, page_number: int, reason: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "_", reason)

    screenshot_path = DEBUG_DIR / f"page_{page_number:03d}_{safe_reason}_{timestamp}.png"
    text_path = DEBUG_DIR / f"page_{page_number:03d}_{safe_reason}_{timestamp}.txt"
    html_path = DEBUG_DIR / f"page_{page_number:03d}_{safe_reason}_{timestamp}.html"

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


def extract_product_cards_from_dom(page: Page, page_number: int) -> List[Dict[str, object]]:
    raw_cards = page.evaluate(
        """
        () => {
          const baseUrl = "https://c2ccertified.org";

          function absoluteUrl(href) {
            try {
              return new URL(href, baseUrl).href;
            } catch {
              return "";
            }
          }

          function cleanText(text) {
            return (text || "")
              .replace(/\\u00a0/g, " ")
              .replace(/[ \\t]+/g, " ")
              .replace(/\\n\\s+/g, "\\n")
              .trim();
          }

          function visible(element) {
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();

            return (
              style &&
              style.visibility !== "hidden" &&
              style.display !== "none" &&
              rect.width > 0 &&
              rect.height > 0
            );
          }

          const cards = Array.from(document.querySelectorAll("a.listinline[href]"))
            .filter(visible);

          const rows = [];

          for (const card of cards) {
            const productUrl = absoluteUrl(card.getAttribute("href") || "");

            const supplierNode = card.querySelector(".listinline__text");
            const productNode = card.querySelector(".listinline__title");

            const supplierName = cleanText(supplierNode ? supplierNode.innerText : "");
            const productName = cleanText(productNode ? productNode.innerText : "");

            const tagNodes = Array.from(card.querySelectorAll(".listinline__tag"));
            const certificationTexts = [];
            let productCategory = "";

            for (const tag of tagNodes) {
              const tagClass = (tag.className || "").toString();
              const pretitleNode = tag.querySelector(".listinline__tag-pretitle");
              const titleNode = tag.querySelector(".listinline__tag-title");

              const pretitle = cleanText(pretitleNode ? pretitleNode.innerText : "");
              const title = cleanText(titleNode ? titleNode.innerText : "");
              const fullText = cleanText(`${pretitle} ${title}`);

              if (tagClass.includes("listinline__tag--topic")) {
                productCategory = title || fullText;
              } else if (/C2C\\s*Certified/i.test(fullText)) {
                certificationTexts.push(fullText);
              }
            }

            const image = card.querySelector("img");
            const imageUrl = image ? absoluteUrl(image.getAttribute("src") || "") : "";

            const evidenceText = cleanText(card.innerText || "");

            if (!supplierName && !productName && certificationTexts.length === 0) {
              continue;
            }

            rows.push({
              supplier_name: supplierName,
              product_name: productName,
              product_category: productCategory,
              certification_texts: certificationTexts,
              product_url: productUrl,
              image_url: imageUrl,
              evidence_text: evidenceText
            });
          }

          return rows;
        }
        """
    )

    parsed_cards = []

    for raw_card in raw_cards:
        supplier_name = clean_text(raw_card.get("supplier_name", ""))
        product_name = clean_text(raw_card.get("product_name", ""))
        product_category = clean_text(raw_card.get("product_category", ""))
        product_url = clean_text(raw_card.get("product_url", ""))
        image_url = clean_text(raw_card.get("image_url", ""))
        evidence_text = clean_text(raw_card.get("evidence_text", ""))

        raw_certification_texts = raw_card.get("certification_texts", [])

        if not isinstance(raw_certification_texts, list):
            raw_certification_texts = []

        certification_data = split_certification_texts(raw_certification_texts)

        parsed_cards.append(
            {
                "certification": CERTIFICATION_NAME,
                "registry_section": REGISTRY_SECTION,
                "registry_source": "Cradle to Cradle Certified Products listing",
                "page_number": page_number,
                "supplier_name": supplier_name,
                "supplier_name_normalized": normalize_for_matching(supplier_name),
                "product_name": product_name,
                "product_name_normalized": normalize_for_matching(product_name),
                "product_category": product_category,
                "product_category_normalized": normalize_for_matching(product_category),
                "certification_types": certification_data["certification_types"],
                "certification_levels": certification_data["certification_levels"],
                "certification_versions": certification_data["certification_versions"],
                "certification_text": certification_data["certification_text"],
                "product_url": product_url,
                "product_slug": safe_slug_from_url(product_url),
                "image_url": image_url,
                "evidence_text": evidence_text,
                "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

    return parsed_cards


def click_next_page(page: Page, page_number: int, timeout_ms: int) -> bool:
    try:
        page.locator(".certified-products__pagination-wrapper").scroll_into_view_if_needed(
            timeout=5000
        )
    except Exception:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    time.sleep(0.7)

    previous_first_product_url = get_first_product_url(page)
    previous_visible_page_number = get_current_visible_page_number(page)

    clicked_info = page.evaluate(
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

          function clean(text) {
            return (text || "").replace(/\\s+/g, " ").trim();
          }

          const pagination =
            document.querySelector(".certified-products__pagination") ||
            document.querySelector(".certified-products__pagination-wrapper");

          if (!pagination) {
            return {
              clicked: false,
              reason: "pagination_not_found"
            };
          }

          const elements = Array.from(
            pagination.querySelectorAll("button, a, [role='button']")
          )
            .filter(isVisible)
            .filter((element) => !isDisabled(element));

          const candidates = elements.map((element) => {
            const rect = element.getBoundingClientRect();
            const text = clean(element.innerText || element.textContent || "");
            const aria = clean(element.getAttribute("aria-label") || "");
            const title = clean(element.getAttribute("title") || "");
            const className = (element.className || "").toString();
            const hasSvg = Boolean(element.querySelector("svg"));

            let score = 0;

            if (hasSvg) {
              score += 100;
            }

            if (/next|right|forward|→|›|»/i.test(`${text} ${aria} ${title} ${className}`)) {
              score += 120;
            }

            if (/^\\d+$/.test(text)) {
              score -= 100;
            }

            if (text === "..." || /^\\.\\.\\.$/.test(text)) {
              score -= 100;
            }

            score += rect.left / 100;

            return {
              element,
              score,
              text,
              aria,
              title,
              className,
              hasSvg,
              x: rect.left + rect.width / 2,
              y: rect.top + rect.height / 2,
              width: rect.width,
              height: rect.height
            };
          });

          const viable = candidates
            .filter((item) => item.score > 0)
            .sort((a, b) => {
              if (b.score !== a.score) {
                return b.score - a.score;
              }

              return b.x - a.x;
            });

          if (viable.length === 0) {
            return {
              clicked: false,
              reason: "no_viable_pagination_candidate",
              candidates: candidates.map((item) => ({
                score: item.score,
                text: item.text,
                aria: item.aria,
                title: item.title,
                className: item.className,
                hasSvg: item.hasSvg,
                x: item.x,
                y: item.y,
                width: item.width,
                height: item.height
              }))
            };
          }

          const chosen = viable[0];

          chosen.element.scrollIntoView({
            block: "center",
            inline: "center"
          });

          chosen.element.click();

          return {
            clicked: true,
            reason: "clicked_pagination_candidate",
            candidate: {
              score: chosen.score,
              text: chosen.text,
              aria: chosen.aria,
              title: chosen.title,
              className: chosen.className,
              hasSvg: chosen.hasSvg,
              x: chosen.x,
              y: chosen.y,
              width: chosen.width,
              height: chosen.height
            },
            candidates: viable.slice(0, 8).map((item) => ({
              score: item.score,
              text: item.text,
              aria: item.aria,
              title: item.title,
              className: item.className,
              hasSvg: item.hasSvg,
              x: item.x,
              y: item.y,
              width: item.width,
              height: item.height
            }))
          };
        }
        """
    )

    if not clicked_info.get("clicked"):
        print(f"Next click failed on page {page_number}: {clicked_info}")
        save_debug_page(page, page_number, "next_button_not_found")
        return False

    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass

    try:
        page.wait_for_function(
            """
            ([previousFirstProductUrl, previousVisiblePageNumber]) => {
              const first = document.querySelector("a.listinline[href]");
              const currentFirstProductUrl = first
                ? new URL(first.getAttribute("href"), "https://c2ccertified.org").href
                : "";

              const pagination = document.querySelector(".certified-products__pagination");
              let currentVisiblePageNumber = null;

              if (pagination) {
                const candidates = Array.from(
                  pagination.querySelectorAll("button, a, span, div")
                );

                for (const element of candidates) {
                  const text = (element.innerText || element.textContent || "")
                    .replace(/\\s+/g, " ")
                    .trim();

                  const className = (element.className || "").toString().toLowerCase();
                  const ariaCurrent = element.getAttribute("aria-current");

                  if (/^\\d+$/.test(text)) {
                    const isActive =
                      ariaCurrent === "page" ||
                      className.includes("active") ||
                      className.includes("current") ||
                      className.includes("selected");

                    if (isActive) {
                      currentVisiblePageNumber = Number(text);
                      break;
                    }
                  }
                }
              }

              if (previousFirstProductUrl && currentFirstProductUrl && currentFirstProductUrl !== previousFirstProductUrl) {
                return true;
              }

              if (
                previousVisiblePageNumber !== null &&
                currentVisiblePageNumber !== null &&
                currentVisiblePageNumber !== previousVisiblePageNumber
              ) {
                return true;
              }

              return false;
            }
            """,
            arg=[previous_first_product_url, previous_visible_page_number],
            timeout=timeout_ms,
        )

        return True

    except Exception:
        new_first_product_url = get_first_product_url(page)

        if new_first_product_url and new_first_product_url != previous_first_product_url:
            return True

        print(f"Warning: page did not appear to change after clicking next on page {page_number}.")
        print(f"Clicked info: {clicked_info}")
        save_debug_page(page, page_number, "page_did_not_change_after_next")
        return False


def extract_section_after_heading(
    lines: List[str],
    heading: str,
    stop_headings: List[str],
    max_lines: int,
) -> str:
    heading_lower = heading.lower()
    stop_headings_lower = [stop.lower() for stop in stop_headings]

    start_index = None

    for index, line in enumerate(lines):
        if clean_text(line).lower() == heading_lower:
            start_index = index + 1
            break

    if start_index is None:
        return ""

    collected = []

    for line in lines[start_index : start_index + max_lines]:
        line_clean = clean_text(line)

        if not line_clean:
            continue

        line_lower = line_clean.lower()

        if any(stop in line_lower for stop in stop_headings_lower):
            break

        collected.append(line_clean)

    return " ".join(collected)


def scrape_product_detail(page: Page, product_url: str, timeout_ms: int) -> Dict[str, object]:
    detail_row = {
        "product_url": product_url,
        "detail_product_name": "",
        "detail_supplier_name": "",
        "detail_certification_number": "",
        "detail_valid_until": "",
        "detail_category_text": "",
        "detail_about_product": "",
        "detail_certificate_covers": "",
        "detail_full_text_excerpt": "",
        "detail_error": "",
    }

    try:
        page.goto(product_url, wait_until="domcontentloaded", timeout=timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass

        body_text = clean_multiline_text(page.locator("body").inner_text(timeout=timeout_ms))
        lines = [clean_text(line) for line in body_text.splitlines()]
        lines = [line for line in lines if line]

        if lines:
            detail_row["detail_full_text_excerpt"] = " | ".join(lines[:80])

        try:
            h1 = clean_text(page.locator("h1").first.inner_text(timeout=3000))
        except Exception:
            h1 = ""

        detail_row["detail_product_name"] = h1

        full_text_single_line = clean_text(body_text)

        certificate_match = CERTIFICATE_NUMBER_RE.search(full_text_single_line)
        valid_match = VALID_UNTIL_RE.search(full_text_single_line)

        if certificate_match:
            detail_row["detail_certification_number"] = certificate_match.group(1)

        if valid_match:
            detail_row["detail_valid_until"] = valid_match.group(1)

        if h1 and h1 in lines:
            h1_index = lines.index(h1)

            if h1_index + 1 < len(lines):
                detail_row["detail_supplier_name"] = lines[h1_index + 1]

        detail_row["detail_category_text"] = extract_section_after_heading(
            lines=lines,
            heading="Category",
            stop_headings=[
                "Company Contact",
                "Share this page",
                "product variants",
                "DISCLAIMER",
            ],
            max_lines=8,
        )

        detail_row["detail_about_product"] = extract_section_after_heading(
            lines=lines,
            heading="Product description",
            stop_headings=[
                "This certificate covers",
                "Category",
                "Company Contact",
                "Share this page",
            ],
            max_lines=10,
        )

        detail_row["detail_certificate_covers"] = extract_section_after_heading(
            lines=lines,
            heading="This certificate covers",
            stop_headings=[
                "Category",
                "Company Contact",
                "Share this page",
            ],
            max_lines=10,
        )

    except Exception as error:
        detail_row["detail_error"] = str(error)

    return detail_row


def build_metadata(
    products: List[Dict[str, object]],
    raw_pages: List[Dict[str, object]],
    args: argparse.Namespace,
) -> Dict[str, object]:
    products_df = pd.DataFrame(products)

    unique_products = products_df["product_url"].nunique() if not products_df.empty else 0

    unique_suppliers = (
        products_df["supplier_name_normalized"].nunique()
        if not products_df.empty and "supplier_name_normalized" in products_df.columns
        else 0
    )

    result_count_values = [
        row["result_count_reported"]
        for row in raw_pages
        if row.get("result_count_reported") is not None
    ]

    reported_result_count = result_count_values[0] if result_count_values else None

    return {
        "certification": CERTIFICATION_NAME,
        "registry_section": REGISTRY_SECTION,
        "source_url": START_URL,
        "source_type": "Dynamic website scraped with Playwright",
        "pages_requested": args.max_pages,
        "pages_scraped": len(raw_pages),
        "reported_result_count": reported_result_count,
        "product_rows_extracted": len(products),
        "unique_product_urls": unique_products,
        "unique_suppliers": unique_suppliers,
        "include_details": args.include_details,
        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Registry built from visible Cradle to Cradle Certified product listing pages. "
            "Optional detail enrichment can add certificate number, validity and product descriptions."
        ),
    }


def save_checkpoint(
    products: List[Dict[str, object]],
    raw_pages: List[Dict[str, object]],
    metadata: Dict[str, object],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    products_df = pd.DataFrame(products)
    raw_pages_df = pd.DataFrame(raw_pages)
    metadata_df = pd.DataFrame([metadata])

    checkpoint_path = output_dir / "cradle_to_cradle_registry_CHECKPOINT.xlsx"

    with pd.ExcelWriter(checkpoint_path, engine="openpyxl") as writer:
        products_df.to_excel(writer, sheet_name="products", index=False)
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        raw_pages_df.to_excel(writer, sheet_name="raw_pages", index=False)

    print(f"Checkpoint saved: {checkpoint_path}")


def save_outputs(
    products_df: pd.DataFrame,
    raw_pages_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    products_csv = output_dir / "cradle_to_cradle_products.csv"
    raw_pages_csv = output_dir / "cradle_to_cradle_raw_pages.csv"
    metadata_csv = output_dir / "cradle_to_cradle_metadata.csv"
    excel_path = output_dir / "cradle_to_cradle_registry.xlsx"

    products_df.to_csv(products_csv, index=False, encoding="utf-8-sig")
    raw_pages_df.to_csv(raw_pages_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        products_df.to_excel(writer, sheet_name="products", index=False)
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        raw_pages_df.to_excel(writer, sheet_name="raw_pages", index=False)

    print("")
    print("Saved files:")
    print(f"- {products_csv}")
    print(f"- {metadata_csv}")
    print(f"- {raw_pages_csv}")
    print(f"- {excel_path}")


def build_cradle_to_cradle_registry(args: argparse.Namespace) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    all_products: List[Dict[str, object]] = []
    raw_pages: List[Dict[str, object]] = []

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

        print("Opening Cradle to Cradle Certified product registry...")
        print(f"Start URL: {START_URL}")
        print(f"Max pages: {args.max_pages}")
        print(f"Headless: {args.headless}")
        print("")

        page.goto(START_URL, wait_until="domcontentloaded", timeout=args.timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        accept_cookies_if_present(page)

        for page_number in tqdm(range(1, args.max_pages + 1), desc="Scraping C2C pages"):
            try:
                wait_for_products(
                    page=page,
                    page_number=page_number,
                    timeout_ms=args.timeout_ms,
                )

                body_text = page.locator("body").inner_text(timeout=args.timeout_ms)
                result_count = extract_result_count(body_text)

                product_rows = extract_product_cards_from_dom(
                    page=page,
                    page_number=page_number,
                )

                current_first_product_url = get_first_product_url(page)
                current_visible_page_number = get_current_visible_page_number(page)

                raw_pages.append(
                    {
                        "certification": CERTIFICATION_NAME,
                        "registry_section": REGISTRY_SECTION,
                        "page_number_loop": page_number,
                        "page_number_visible": current_visible_page_number,
                        "page_url": page.url,
                        "first_product_url": current_first_product_url,
                        "result_count_reported": result_count,
                        "products_extracted": len(product_rows),
                        "page_text_excerpt": clean_text(body_text)[:3000],
                        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                )

                if not product_rows:
                    save_debug_page(page, page_number, "no_products_extracted")

                all_products.extend(product_rows)

                print(
                    f"Page {page_number}: extracted {len(product_rows)} products "
                    f"(reported results: {result_count}, first product: {current_first_product_url})"
                )

                if args.checkpoint_every > 0 and page_number % args.checkpoint_every == 0:
                    metadata = build_metadata(
                        products=all_products,
                        raw_pages=raw_pages,
                        args=args,
                    )
                    save_checkpoint(
                        products=all_products,
                        raw_pages=raw_pages,
                        metadata=metadata,
                        output_dir=OUTPUT_DIR,
                    )

                if page_number < args.max_pages:
                    clicked = click_next_page(
                        page=page,
                        page_number=page_number,
                        timeout_ms=args.timeout_ms,
                    )

                    if not clicked:
                        print(f"Could not move to next page after page {page_number}. Stopping.")
                        break

                    time.sleep(args.page_delay)

            except Exception as error:
                print(f"Error on page {page_number}: {error}")
                save_debug_page(page, page_number, "page_error")

                raw_pages.append(
                    {
                        "certification": CERTIFICATION_NAME,
                        "registry_section": REGISTRY_SECTION,
                        "page_number_loop": page_number,
                        "page_number_visible": get_current_visible_page_number(page),
                        "page_url": page.url,
                        "first_product_url": get_first_product_url(page),
                        "result_count_reported": None,
                        "products_extracted": 0,
                        "page_text_excerpt": "",
                        "error": str(error),
                        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                )

                if args.stop_on_error:
                    raise

                break

        if all_products:
            products_df = pd.DataFrame(all_products)

            products_df = products_df.drop_duplicates(
                subset=["product_url"],
                keep="first",
            ).sort_values(
                [
                    "supplier_name_normalized",
                    "product_name_normalized",
                    "product_url",
                ]
            )

            products_df = products_df.reset_index(drop=True)
        else:
            products_df = pd.DataFrame()

        if args.include_details and not products_df.empty:
            print("")
            print("Starting optional product detail enrichment...")

            detail_page: Page = context.new_page()
            product_urls = products_df["product_url"].dropna().drop_duplicates().tolist()

            if args.max_details is not None:
                product_urls = product_urls[: args.max_details]

            detail_rows = []

            for product_url in tqdm(product_urls, desc="Scraping C2C product details"):
                detail_rows.append(
                    scrape_product_detail(
                        page=detail_page,
                        product_url=product_url,
                        timeout_ms=args.timeout_ms,
                    )
                )

                time.sleep(args.detail_delay)

            details_df = pd.DataFrame(detail_rows)

            products_df = products_df.merge(
                details_df,
                on="product_url",
                how="left",
            )

        raw_pages_df = pd.DataFrame(raw_pages)

        metadata = build_metadata(
            products=products_df.to_dict("records") if not products_df.empty else [],
            raw_pages=raw_pages,
            args=args,
        )

        metadata_df = pd.DataFrame([metadata])

        save_outputs(
            products_df=products_df,
            raw_pages_df=raw_pages_df,
            metadata_df=metadata_df,
            output_dir=OUTPUT_DIR,
        )

        context.close()
        browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local Cradle to Cradle Certified product registry by scraping "
            "the official Certified Products listing with Playwright."
        )
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Maximum number of listing pages to scrape. Default: {DEFAULT_MAX_PAGES}",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode. Default is visible browser for easier debugging.",
    )

    parser.add_argument(
        "--slow-mo",
        type=int,
        default=0,
        help="Playwright slow motion in milliseconds. Useful for debugging. Default: 0",
    )

    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Timeout in milliseconds. Default: 30000",
    )

    parser.add_argument(
        "--page-delay",
        type=float,
        default=1.0,
        help="Delay after clicking next page, in seconds. Default: 1.0",
    )

    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=5,
        help="Save checkpoint every N pages. Default: 5",
    )

    parser.add_argument(
        "--include-details",
        action="store_true",
        help="Also visit each product detail page to enrich the registry. Slower.",
    )

    parser.add_argument(
        "--max-details",
        type=int,
        default=None,
        help="Optional maximum number of product detail pages to visit.",
    )

    parser.add_argument(
        "--detail-delay",
        type=float,
        default=0.5,
        help="Delay between product detail page visits, in seconds. Default: 0.5",
    )

    parser.add_argument(
        "--viewport-width",
        type=int,
        default=1600,
        help="Browser viewport width. Default: 1600",
    )

    parser.add_argument(
        "--viewport-height",
        type=int,
        default=1000,
        help="Browser viewport height. Default: 1000",
    )

    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop immediately if a page fails.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_cradle_to_cradle_registry(args)


if __name__ == "__main__":
    main()