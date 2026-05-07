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


CERTIFICATION_NAME = "Environmental Product Declaration"
CERTIFICATION_SHORT_NAME = "EPD"
REGISTRY_SECTION = "EPD International Library"

START_URL = "https://www.environdec.com/library"

OUTPUT_DIR = Path("data") / "certifications" / "epd"
DEBUG_DIR = OUTPUT_DIR / "debug"

DEFAULT_RESULTS_PER_PAGE = 10

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
        return "https://www.environdec.com" + url

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


def wait_for_epd_results(page: Page, timeout_ms: int) -> None:
    try:
        page.wait_for_function(
            """
            () => {
              const text = document.body.innerText || "";
              const cards = Array.from(document.querySelectorAll("a[href*='/library/epd']"));
              const hasEpdNumber = /EPD-[A-Z]+-[0-9]+:[0-9]+/i.test(text);
              const hasLibrary = /EPD\\s+Library/i.test(text);

              return hasLibrary && hasEpdNumber && cards.length > 0;
            }
            """,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        save_debug_page(page, "wait_for_epd_results_timeout")
        raise


def get_current_page_number(page: Page) -> Optional[int]:
    try:
        current_page = page.evaluate(
            """
            () => {
              const selectors = [
                "[aria-current='page']",
                ".active",
                "[class*='active']"
              ];

              for (const selector of selectors) {
                const elements = Array.from(document.querySelectorAll(selector));

                for (const element of elements) {
                  const text = (element.innerText || element.textContent || "")
                    .replace(/\\s+/g, " ")
                    .trim();

                  if (/^\\d+$/.test(text)) {
                    return Number(text);
                  }
                }
              }

              const buttons = Array.from(document.querySelectorAll("button, a, li, span"));

              for (const element of buttons) {
                const text = (element.innerText || element.textContent || "")
                  .replace(/\\s+/g, " ")
                  .trim();

                const className = (element.className || "").toString();

                if (/^\\d+$/.test(text) && /active|selected|current/i.test(className)) {
                  return Number(text);
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
              const text = document.body.innerText || "";
              const numbers = [];

              const paginationAreaCandidates = Array.from(
                document.querySelectorAll("nav, ul, div, section")
              );

              for (const area of paginationAreaCandidates) {
                const areaText = (area.innerText || area.textContent || "")
                  .replace(/\\s+/g, " ")
                  .trim();

                if (!areaText) {
                  continue;
                }

                if (!/Show:\\s*\\d+\\s*items/i.test(areaText) && !/\\.\\.\\./.test(areaText)) {
                  continue;
                }

                const matches = areaText.match(/\\b\\d+\\b/g) || [];

                for (const match of matches) {
                  const value = Number(match);

                  if (value > 0) {
                    numbers.push(value);
                  }
                }
              }

              const elements = Array.from(document.querySelectorAll("button, a, li, span"));

              for (const element of elements) {
                const text = (element.innerText || element.textContent || "")
                  .replace(/\\s+/g, " ")
                  .trim();

                const aria = element.getAttribute("aria-label") || "";
                const title = element.getAttribute("title") || "";

                if (/^\\d+$/.test(text)) {
                  numbers.push(Number(text));
                }

                if (/^\\d+$/.test(title.trim())) {
                  numbers.push(Number(title.trim()));
                }

                const labelMatch = `${aria} ${title}`.match(/page\\s+(\\d+)/i);

                if (labelMatch) {
                  numbers.push(Number(labelMatch[1]));
                }
              }

              const realistic = numbers.filter((n) => n >= 1 && n <= 100000);

              if (realistic.length === 0) {
                return null;
              }

              return Math.max(...realistic);
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
                  const title = document.querySelector("a[href*='/library/epd']");
                  const epdNumber = document.querySelector("[class*='fullIdentificationNumber']");

                  return `${title ? title.innerText || title.textContent || "" : ""} | ${epdNumber ? epdNumber.innerText || epdNumber.textContent || "" : ""}`;
                }
                """
            )
        )
    except Exception:
        return ""


def parse_version_validity_from_text(text: str) -> Dict[str, str]:
    text = clean_text(text)

    version_date = ""
    validity_date = ""

    version_match = re.search(
        r"Version\s+date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}/[0-9]{1,2}/[0-9]{4})",
        text,
        flags=re.IGNORECASE,
    )

    validity_match = re.search(
        r"Validity\s+date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}/[0-9]{1,2}/[0-9]{4})",
        text,
        flags=re.IGNORECASE,
    )

    if version_match:
        version_date = clean_text(version_match.group(1))

    if validity_match:
        validity_date = clean_text(validity_match.group(1))

    return {
        "version_date": version_date,
        "validity_date": validity_date,
    }


def infer_tag_fields(tags: List[str]) -> Dict[str, str]:
    cleaned_tags = [clean_text(tag) for tag in tags if clean_text(tag)]

    product_category = cleaned_tags[0] if len(cleaned_tags) >= 1 else ""
    organization_name = cleaned_tags[1] if len(cleaned_tags) >= 2 else ""
    geographical_scope = cleaned_tags[2] if len(cleaned_tags) >= 3 else ""
    epd_type = cleaned_tags[3] if len(cleaned_tags) >= 4 else ""

    return {
        "product_category": product_category,
        "organization_name": organization_name,
        "geographical_scope": geographical_scope,
        "epd_type": epd_type,
        "all_tags": " | ".join(cleaned_tags),
    }


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

          function findCardContainers() {
            const titleLinks = Array.from(document.querySelectorAll("a[href*='/library/epd']"))
              .filter((link) => {
                const text = cleanText(link.innerText || link.textContent || "");
                const href = link.getAttribute("href") || "";

                return text && /\\/library\\/epd/i.test(href);
              });

            const cards = [];

            for (const titleLink of titleLinks) {
              let current = titleLink;

              for (let depth = 0; depth < 8 && current; depth++) {
                const className = (current.className || "").toString();

                if (/EPDLibraryResultItem/i.test(className) && /container/i.test(className)) {
                  cards.push(current);
                  break;
                }

                current = current.parentElement;
              }
            }

            const uniqueCards = [];
            const seen = new Set();

            for (const card of cards) {
              if (seen.has(card)) {
                continue;
              }

              seen.add(card);
              uniqueCards.push(card);
            }

            return uniqueCards;
          }

          const cards = findCardContainers();

          return cards.map((card) => {
            const titleLink = Array.from(card.querySelectorAll("a[href*='/library/epd']"))
              .find((link) => cleanText(link.innerText || link.textContent || ""));

            const epdNumberNode =
              card.querySelector("[class*='fullIdentificationNumber']") ||
              Array.from(card.querySelectorAll("div, span")).find((node) => {
                const text = cleanText(node.innerText || node.textContent || "");
                return /^EPD-[A-Z]+-[0-9]+:[0-9]+$/i.test(text);
              });

            const downloadLink = Array.from(card.querySelectorAll("a[href]"))
              .find((link) => {
                const href = link.getAttribute("href") || "";
                const className = (link.className || "").toString();

                return /EPDLibrary\\/Files\\/EPDs/i.test(href) || /downloadLink/i.test(className);
              });

            const badgeNode = Array.from(card.querySelectorAll("div, span"))
              .find((node) => {
                const text = cleanText(node.innerText || node.textContent || "");
                const className = (node.className || "").toString();

                return /badge/i.test(className) && /^(New|Updated)$/i.test(text);
              });

            const tagNodes = Array.from(card.querySelectorAll("[class*='SearchTag']"));
            const tags = tagNodes
              .map((node) => cleanText(node.innerText || node.textContent || ""))
              .filter(Boolean);

            const image = card.querySelector("img");
            const rawText = cleanText(card.innerText || card.textContent || "");

            return {
              product_name: cleanText(titleLink ? titleLink.innerText || titleLink.textContent || "" : ""),
              product_url: absoluteUrl(titleLink ? titleLink.getAttribute("href") || "" : ""),
              epd_number: cleanText(epdNumberNode ? epdNumberNode.innerText || epdNumberNode.textContent || "" : ""),
              download_url: absoluteUrl(downloadLink ? downloadLink.getAttribute("href") || "" : ""),
              badge_status: cleanText(badgeNode ? badgeNode.innerText || badgeNode.textContent || "" : ""),
              image_url: absoluteUrl(image ? image.getAttribute("src") || image.getAttribute("data-src") || "" : ""),
              image_alt: cleanText(image ? image.getAttribute("alt") || "" : ""),
              tags,
              evidence_text: rawText
            };
          });
        }
        """
    )

    rows = []

    for raw in raw_rows:
        product_name = clean_text(raw.get("product_name", ""))
        epd_number = clean_text(raw.get("epd_number", ""))

        if not product_name and not epd_number:
            continue

        product_url = absolute_url(clean_text(raw.get("product_url", "")))
        download_url = absolute_url(clean_text(raw.get("download_url", "")))
        badge_status = clean_text(raw.get("badge_status", ""))
        image_url = absolute_url(clean_text(raw.get("image_url", "")))
        image_alt = clean_text(raw.get("image_alt", ""))
        evidence_text = clean_text(raw.get("evidence_text", ""))

        tags = raw.get("tags", [])

        if not isinstance(tags, list):
            tags = []

        tag_fields = infer_tag_fields(tags)
        date_fields = parse_version_validity_from_text(evidence_text)

        row = {
            "certification": CERTIFICATION_SHORT_NAME,
            "certification_full_name": CERTIFICATION_NAME,
            "registry_section": REGISTRY_SECTION,
            "registry_source": "EPD International Library",
            "registry_match_level": "product_declaration",
            "page_number": page_number,
            "product_name": product_name,
            "product_name_normalized": normalize_for_matching(product_name),
            "epd_number": epd_number,
            "epd_number_normalized": normalize_for_matching(epd_number),
            "product_url": product_url,
            "product_slug": product_url.rstrip("/").split("/")[-1] if product_url else "",
            "download_url": download_url,
            "badge_status": badge_status,
            "product_category": tag_fields["product_category"],
            "product_category_normalized": normalize_for_matching(tag_fields["product_category"]),
            "organization_name": tag_fields["organization_name"],
            "organization_name_normalized": normalize_for_matching(tag_fields["organization_name"]),
            "geographical_scope": tag_fields["geographical_scope"],
            "geographical_scope_normalized": normalize_for_matching(tag_fields["geographical_scope"]),
            "epd_type": tag_fields["epd_type"],
            "epd_type_normalized": normalize_for_matching(tag_fields["epd_type"]),
            "all_tags": tag_fields["all_tags"],
            "version_date": date_fields["version_date"],
            "validity_date": date_fields["validity_date"],
            "image_url": image_url,
            "image_alt": image_alt,
            "source_url": START_URL,
            "evidence_text": evidence_text,
            "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        row["record_key"] = make_hash_key(
            row["epd_number"],
            row["product_name"],
            row["organization_name"],
            row["product_url"],
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
                row.get("epd_number", ""),
                row.get("product_name", ""),
                row.get("organization_name", ""),
                row.get("product_url", ""),
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
          function cleanText(text) {
            return (text || "")
              .replace(/\\s+/g, " ")
              .trim();
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

          function isDisabled(element) {
            const className = (element.className || "").toString().toLowerCase();

            return (
              element.disabled === true ||
              element.getAttribute("disabled") !== null ||
              element.getAttribute("aria-disabled") === "true" ||
              className.includes("disabled")
            );
          }

          const directCandidates = Array.from(
            document.querySelectorAll("button, a, [role='button']")
          )
            .filter(isVisible)
            .filter((element) => !isDisabled(element))
            .map((element) => {
              const text = cleanText(element.innerText || element.textContent || "");
              const aria = element.getAttribute("aria-label") || "";
              const title = element.getAttribute("title") || "";
              const className = (element.className || "").toString();
              const rect = element.getBoundingClientRect();

              let score = 0;

              if (/^Next$/i.test(text)) score += 250;
              if (/next/i.test(`${aria} ${title} ${className}`)) score += 180;
              if (/→|›|»/.test(text)) score += 160;

              if (element.querySelector("svg, i")) score += 30;

              if (rect.left > window.innerWidth * 0.50) score += 25;
              if (rect.y > window.innerHeight * 0.50) score += 20;

              if (/previous|prev|search|filter|show|items|download|info|support|library|services/i.test(text)) {
                score -= 100;
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

          if (directCandidates.length === 0) {
            return {
              clicked: false,
              reason: "next_candidate_not_found"
            };
          }

          const chosen = directCandidates[0];

          chosen.element.scrollIntoView({
            block: "center",
            inline: "center"
          });

          chosen.element.click();

          return {
            clicked: true,
            reason: "clicked_next",
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
              const title = document.querySelector("a[href*='/library/epd']");
              const epdNumber = document.querySelector("[class*='fullIdentificationNumber']");
              const newSignature = `${title ? title.innerText || title.textContent || "" : ""} | ${epdNumber ? epdNumber.innerText || epdNumber.textContent || "" : ""}`
                .replace(/\\s+/g, " ")
                .trim();

              let currentPageNumber = null;

              const elements = Array.from(document.querySelectorAll("[aria-current='page'], .active, [class*='active']"));

              for (const element of elements) {
                const text = (element.innerText || element.textContent || "").replace(/\\s+/g, " ").trim();

                if (/^\\d+$/.test(text)) {
                  currentPageNumber = Number(text);
                  break;
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

    checkpoint_path = output_dir / "epd_registry_CHECKPOINT.xlsx"

    with pd.ExcelWriter(checkpoint_path, engine="openpyxl") as writer:
        rows_df.to_excel(writer, sheet_name="epds", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print(f"Checkpoint saved: {checkpoint_path}")


def build_organization_summary(rows_df: pd.DataFrame) -> pd.DataFrame:
    if rows_df.empty:
        return pd.DataFrame()

    summary_df = (
        rows_df.groupby(
            [
                "organization_name",
                "organization_name_normalized",
                "geographical_scope",
                "geographical_scope_normalized",
            ],
            dropna=False,
        )
        .agg(
            epd_rows=("record_key", "count"),
            unique_epd_numbers=("epd_number_normalized", "nunique"),
            products=(
                "product_name",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:120]
                ),
            ),
            product_categories=(
                "product_category",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:80]
                ),
            ),
            epd_types=(
                "epd_type",
                lambda values: " | ".join(
                    sorted(set(clean_text(value) for value in values if clean_text(value)))[:40]
                ),
            ),
            epd_numbers=(
                "epd_number",
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
    summary_df["registry_section"] = "Organization Summary"
    summary_df["registry_match_level"] = "organization"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['organization_name']} appears in {row['epd_rows']} EPD row(s), "
            f"with {row['unique_epd_numbers']} unique EPD number(s)."
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "organization_name",
            "organization_name_normalized",
            "geographical_scope",
            "geographical_scope_normalized",
            "epd_rows",
            "unique_epd_numbers",
            "epd_numbers",
            "products",
            "product_categories",
            "epd_types",
            "source_url",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        [
            "organization_name_normalized",
            "geographical_scope_normalized",
        ]
    ).reset_index(drop=True)


def build_product_category_summary(rows_df: pd.DataFrame) -> pd.DataFrame:
    if rows_df.empty:
        return pd.DataFrame()

    summary_df = (
        rows_df.groupby(
            [
                "product_category",
                "product_category_normalized",
            ],
            dropna=False,
        )
        .agg(
            epd_rows=("record_key", "count"),
            unique_organizations=("organization_name_normalized", "nunique"),
            unique_epd_numbers=("epd_number_normalized", "nunique"),
            organization_names=(
                "organization_name",
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
    summary_df["registry_section"] = "Product Category Summary"
    summary_df["registry_match_level"] = "product_category"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['product_category']} appears in {row['epd_rows']} EPD row(s), "
            f"with {row['unique_organizations']} unique organization(s)."
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "product_category",
            "product_category_normalized",
            "epd_rows",
            "unique_organizations",
            "unique_epd_numbers",
            "organization_names",
            "source_url",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        ["product_category_normalized"]
    ).reset_index(drop=True)


def build_epd_type_summary(rows_df: pd.DataFrame) -> pd.DataFrame:
    if rows_df.empty:
        return pd.DataFrame()

    summary_df = (
        rows_df.groupby(
            [
                "epd_type",
                "epd_type_normalized",
            ],
            dropna=False,
        )
        .agg(
            epd_rows=("record_key", "count"),
            unique_organizations=("organization_name_normalized", "nunique"),
            unique_epd_numbers=("epd_number_normalized", "nunique"),
            source_url=("source_url", "first"),
        )
        .reset_index()
    )

    summary_df["certification"] = CERTIFICATION_SHORT_NAME
    summary_df["certification_full_name"] = CERTIFICATION_NAME
    summary_df["registry_section"] = "EPD Type Summary"
    summary_df["registry_match_level"] = "epd_type"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['epd_type']} appears in {row['epd_rows']} EPD row(s), "
            f"with {row['unique_organizations']} unique organization(s)."
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "epd_type",
            "epd_type_normalized",
            "epd_rows",
            "unique_organizations",
            "unique_epd_numbers",
            "source_url",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        ["epd_type_normalized"]
    ).reset_index(drop=True)


def build_metadata(
    rows_df: pd.DataFrame,
    organizations_df: pd.DataFrame,
    category_summary_df: pd.DataFrame,
    epd_type_summary_df: pd.DataFrame,
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
            "epd_rows_extracted": len(rows_df),
            "organization_summary_rows": len(organizations_df),
            "product_category_summary_rows": len(category_summary_df),
            "epd_type_summary_rows": len(epd_type_summary_df),
            "detected_total_pages": detected_total_pages,
            "pages_scraped": int(scrape_log_df["page_number"].max())
            if not scrape_log_df.empty and "page_number" in scrape_log_df.columns
            else 0,
            "max_pages_requested": args.max_pages,
            "headless": args.headless,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": (
                "This registry is product/declaration-level and is built from the public "
                "EPD International Library. Tag order is interpreted as product category, "
                "organization, geographical scope and EPD type when four tags are available."
            ),
        }
    ]

    return pd.DataFrame(metadata)


def save_outputs(
    rows_df: pd.DataFrame,
    organizations_df: pd.DataFrame,
    category_summary_df: pd.DataFrame,
    epd_type_summary_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows_df = sanitize_dataframe_for_excel(rows_df)
    organizations_df = sanitize_dataframe_for_excel(organizations_df)
    category_summary_df = sanitize_dataframe_for_excel(category_summary_df)
    epd_type_summary_df = sanitize_dataframe_for_excel(epd_type_summary_df)
    scrape_log_df = sanitize_dataframe_for_excel(scrape_log_df)
    metadata_df = sanitize_dataframe_for_excel(metadata_df)

    epds_csv = output_dir / "epd_products.csv"
    organizations_csv = output_dir / "epd_organizations.csv"
    categories_csv = output_dir / "epd_product_categories.csv"
    types_csv = output_dir / "epd_types.csv"
    scrape_log_csv = output_dir / "epd_scrape_log.csv"
    metadata_csv = output_dir / "epd_metadata.csv"
    excel_path = output_dir / "epd_registry.xlsx"

    rows_df.to_csv(epds_csv, index=False, encoding="utf-8-sig")
    organizations_df.to_csv(organizations_csv, index=False, encoding="utf-8-sig")
    category_summary_df.to_csv(categories_csv, index=False, encoding="utf-8-sig")
    epd_type_summary_df.to_csv(types_csv, index=False, encoding="utf-8-sig")
    scrape_log_df.to_csv(scrape_log_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        rows_df.to_excel(writer, sheet_name="epds", index=False)
        organizations_df.to_excel(writer, sheet_name="organizations", index=False)
        category_summary_df.to_excel(writer, sheet_name="product_categories", index=False)
        epd_type_summary_df.to_excel(writer, sheet_name="epd_types", index=False)
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print("")
    print("Saved files:")
    print(f"- {epds_csv}")
    print(f"- {organizations_csv}")
    print(f"- {categories_csv}")
    print(f"- {types_csv}")
    print(f"- {metadata_csv}")
    print(f"- {scrape_log_csv}")
    print(f"- {excel_path}")


def build_epd_registry(args: argparse.Namespace) -> None:
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

        print("Opening EPD International Library...")
        print(f"Start URL: {START_URL}")
        print(f"Headless: {args.headless}")
        print("")

        page.goto(START_URL, wait_until="domcontentloaded", timeout=args.timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        accept_cookies_if_present(page)
        wait_for_epd_results(page, timeout_ms=args.timeout_ms)

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

        for page_index in tqdm(range(1, max_pages + 1), desc="Scraping EPD pages"):
            try:
                wait_for_epd_results(page, timeout_ms=args.timeout_ms)

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
                        print(f"Could not move to next EPD page after page {current_page_number}.")
                        save_debug_page(page, f"next_failed_page_{current_page_number}")
                        break

                    time.sleep(args.page_delay)

            except Exception as error:
                print(f"Error on EPD page {page_index}: {error}")
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
                "organization_name_normalized",
                "product_name_normalized",
                "epd_number_normalized",
            ]
        ).reset_index(drop=True)

    organizations_df = build_organization_summary(rows_df)
    category_summary_df = build_product_category_summary(rows_df)
    epd_type_summary_df = build_epd_type_summary(rows_df)
    scrape_log_df = pd.DataFrame(scrape_log)

    metadata_df = build_metadata(
        rows_df=rows_df,
        organizations_df=organizations_df,
        category_summary_df=category_summary_df,
        epd_type_summary_df=epd_type_summary_df,
        scrape_log_df=scrape_log_df,
        detected_total_pages=detected_total_pages,
        args=args,
    )

    print("")
    print("Registry summary:")
    print(f"  EPD rows extracted: {len(rows_df)}")
    print(f"  Organization summary rows: {len(organizations_df)}")
    print(f"  Product category summary rows: {len(category_summary_df)}")
    print(f"  EPD type summary rows: {len(epd_type_summary_df)}")
    print(f"  Detected total pages: {detected_total_pages}")

    if rows_df.empty:
        print("")
        print("WARNING: No EPD rows were extracted.")
        print(f"Debug files are available in: {DEBUG_DIR}")

    save_outputs(
        rows_df=rows_df,
        organizations_df=organizations_df,
        category_summary_df=category_summary_df,
        epd_type_summary_df=epd_type_summary_df,
        scrape_log_df=scrape_log_df,
        metadata_df=metadata_df,
        output_dir=OUTPUT_DIR,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local EPD registry from the public EPD International Library."
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
        default=50,
        help="Save checkpoint every N pages. Default: 50.",
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
    build_epd_registry(args)


if __name__ == "__main__":
    main()