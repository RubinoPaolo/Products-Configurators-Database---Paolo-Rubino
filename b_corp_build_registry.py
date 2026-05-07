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


CERTIFICATION_NAME = "Certified B Corporation"
CERTIFICATION_SHORT_NAME = "B Corp"
REGISTRY_SECTION = "Find a B Corp Directory"

START_URL = "https://www.bcorporation.net/en-us/find-a-b-corp/"

OUTPUT_DIR = Path("data") / "certifications" / "b_corp"
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
        return "https://www.bcorporation.net" + url

    return url


def extract_reported_total_count(text: str) -> Optional[int]:
    patterns = [
        r"Showing\s+all\s+([0-9,]+)\s+B\s+Corps",
        r"Showing\s+[0-9,]+\s*-\s*[0-9,]+\s+of\s+([0-9,]+)",
        r"of\s+([0-9,]+)",
        r"([0-9,]+)\s+B\s+Corps",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)

        if match:
            return int(match.group(1).replace(",", ""))

    return None


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


def wait_for_bcorp_results(page: Page, timeout_ms: int) -> None:
    try:
        page.wait_for_function(
            """
            () => {
              const bodyText = document.body.innerText || "";
              const cards = document.querySelectorAll("li.ais-Hits-item a[data-testid='profile-link']");
              const hasCount =
                /Showing\\s+all\\s+[0-9,]+\\s+B\\s+Corps/i.test(bodyText) ||
                /Showing\\s+[0-9,]+\\s*-\\s*[0-9,]+\\s+of\\s+[0-9,]+/i.test(bodyText);

              return cards.length > 0 && hasCount;
            }
            """,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        save_debug_page(page, "wait_for_bcorp_results_timeout")
        raise


def get_page_signature(page: Page) -> str:
    try:
        return clean_text(
            page.evaluate(
                """
                () => {
                  const firstCard = document.querySelector("li.ais-Hits-item a[data-testid='profile-link']");
                  if (!firstCard) return "";

                  const nameNode = firstCard.querySelector("[data-testid='company-name-desktop']");
                  const name = nameNode ? nameNode.innerText : "";
                  const href = firstCard.getAttribute("href") || "";
                  return `${name} ${href}`;
                }
                """
            )
        )
    except Exception:
        return ""


def get_visible_card_count(page: Page) -> int:
    try:
        return int(
            page.evaluate(
                """
                () => {
                  return document.querySelectorAll("li.ais-Hits-item a[data-testid='profile-link']").length;
                }
                """
            )
        )
    except Exception:
        return 0


def extract_company_rows(page: Page, page_number: int) -> List[Dict[str, object]]:
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

          function getBestImageUrl(card) {
            const img = card.querySelector("img");

            if (!img) {
              return "";
            }

            const srcset = img.getAttribute("srcset") || "";

            if (srcset) {
              const firstPart = srcset.split(",")[0].trim();
              const firstUrl = firstPart.split(" ")[0].trim();

              if (firstUrl) {
                return absoluteUrl(firstUrl);
              }
            }

            return absoluteUrl(
              img.getAttribute("src") ||
              img.getAttribute("data-src") ||
              ""
            );
          }

          const links = Array.from(
            document.querySelectorAll("li.ais-Hits-item a[data-testid='profile-link']")
          );

          const rows = [];

          for (const link of links) {
            const card = link.closest("li.ais-Hits-item") || link;

            const nameNode = card.querySelector("[data-testid='company-name-desktop']");
            const descriptionNode = card.querySelector("p");

            const profileUrl = absoluteUrl(link.getAttribute("href") || "");
            const companyName = cleanText(nameNode ? nameNode.innerText : "");

            let description = "";
            if (descriptionNode) {
              description = cleanText(descriptionNode.innerText || descriptionNode.textContent || "");
            }

            const rawText = cleanText(card.innerText || card.textContent || "");

            let certifiedSince = "";
            const certifiedMatch = rawText.match(/Certified\\s+since\\s+([A-Za-z]+\\s+\\d{4})/i);

            if (certifiedMatch) {
              certifiedSince = cleanText(certifiedMatch[1]);
            } else {
              const lines = rawText
                .split("\\n")
                .map((line) => cleanText(line))
                .filter(Boolean);

              for (let i = 0; i < lines.length; i++) {
                if (/^Certified\\s+since$/i.test(lines[i]) && i + 1 < lines.length) {
                  certifiedSince = lines[i + 1];
                  break;
                }
              }
            }

            const imageUrl = getBestImageUrl(card);

            rows.push({
              company_name: companyName,
              profile_url: profileUrl,
              description: description,
              certified_since: certifiedSince,
              image_url: imageUrl,
              evidence_text: rawText
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

        profile_url = clean_text(raw.get("profile_url", ""))
        description = clean_text(raw.get("description", ""))
        certified_since = clean_text(raw.get("certified_since", ""))
        image_url = clean_text(raw.get("image_url", ""))
        evidence_text = clean_text(raw.get("evidence_text", ""))

        rows.append(
            {
                "certification": CERTIFICATION_SHORT_NAME,
                "certification_full_name": CERTIFICATION_NAME,
                "registry_section": REGISTRY_SECTION,
                "registry_source": "B Lab Find a B Corp directory",
                "registry_match_level": "company",
                "page_number": page_number,
                "company_key": make_hash_key(company_name, profile_url, certified_since),
                "company_name": company_name,
                "company_name_normalized": normalize_for_matching(company_name),
                "profile_url": profile_url,
                "profile_slug": profile_url.rstrip("/").split("/")[-1] if profile_url else "",
                "description": description,
                "description_normalized": normalize_for_matching(description),
                "certified_since": certified_since,
                "certified_since_normalized": normalize_for_matching(certified_since),
                "image_url": image_url,
                "source_url": START_URL,
                "evidence_text": evidence_text,
                "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

    return rows


def deduplicate_companies(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    deduped = []

    for row in rows:
        key = clean_text(row.get("company_key", ""))

        if not key:
            key = make_hash_key(
                row.get("company_name", ""),
                row.get("profile_url", ""),
                row.get("certified_since", ""),
            )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(row)

    return deduped


def click_next_page(page: Page, timeout_ms: int) -> bool:
    previous_signature = get_page_signature(page)

    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(0.5)
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
              element.getAttribute("aria-disabled") === "true" ||
              className.includes("disabled") ||
              element.getAttribute("disabled") !== null
            );
          }

          const elements = Array.from(
            document.querySelectorAll("button, a, [role='button']")
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

            if (/^Next$/i.test(text)) {
              score += 220;
            }

            if (/Next/i.test(`${aria} ${title} ${className}`)) {
              score += 140;
            }

            if (/→|›|»/.test(text)) {
              score += 120;
            }

            if (element.querySelector("svg")) {
              score += 20;
            }

            if (rect.left > window.innerWidth * 0.45) {
              score += 15;
            }

            if (/Previous|Donate|Sign in|More filters|Sort by|Location|Ownership|Search|Clear/i.test(text)) {
              score -= 200;
            }

            if (/^\\d+$/.test(text)) {
              score -= 100;
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
              reason: "next_candidate_not_found",
              candidates: []
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
            ([oldSignature]) => {
              const firstCard = document.querySelector("li.ais-Hits-item a[data-testid='profile-link']");

              if (!firstCard) {
                return false;
              }

              const nameNode = firstCard.querySelector("[data-testid='company-name-desktop']");
              const name = nameNode ? nameNode.innerText : "";
              const href = firstCard.getAttribute("href") || "";
              const current = `${name} ${href}`.replace(/\\s+/g, " ").trim();

              return current && current !== oldSignature;
            }
            """,
            arg=[previous_signature],
            timeout=timeout_ms,
        )

        return True

    except Exception:
        new_signature = get_page_signature(page)

        if new_signature and new_signature != previous_signature:
            return True

        print(
            "Warning: Next was clicked but page signature did not change. "
            f"Previous signature: {previous_signature}, new signature: {new_signature}"
        )
        return False


def save_checkpoint(
    company_rows: List[Dict[str, object]],
    scrape_log: List[Dict[str, object]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    companies_df = sanitize_dataframe_for_excel(
        pd.DataFrame(deduplicate_companies(company_rows))
    )
    scrape_log_df = sanitize_dataframe_for_excel(pd.DataFrame(scrape_log))

    checkpoint_path = output_dir / "b_corp_registry_CHECKPOINT.xlsx"

    with pd.ExcelWriter(checkpoint_path, engine="openpyxl") as writer:
        companies_df.to_excel(writer, sheet_name="companies", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print(f"Checkpoint saved: {checkpoint_path}")


def build_certified_since_summary(companies_df: pd.DataFrame) -> pd.DataFrame:
    if companies_df.empty:
        return pd.DataFrame()

    summary_df = (
        companies_df.groupby(
            ["certified_since", "certified_since_normalized"],
            dropna=False,
        )
        .agg(
            company_rows=("company_name", "count"),
            company_names=(
                "company_name",
                lambda values: " | ".join(
                    sorted(
                        set(clean_text(value) for value in values if clean_text(value))
                    )[:80]
                ),
            ),
            source_url=("source_url", "first"),
        )
        .reset_index()
    )

    summary_df["certification"] = CERTIFICATION_SHORT_NAME
    summary_df["certification_full_name"] = CERTIFICATION_NAME
    summary_df["registry_section"] = "Certified Since Summary"
    summary_df["registry_match_level"] = "certified_since_summary"

    summary_df["evidence_text"] = summary_df.apply(
        lambda row: (
            f"{row['company_rows']} B Corp company row(s) have certified_since='{row['certified_since']}'."
        ),
        axis=1,
    )

    summary_df = summary_df[
        [
            "certification",
            "certification_full_name",
            "registry_section",
            "registry_match_level",
            "certified_since",
            "certified_since_normalized",
            "company_rows",
            "company_names",
            "source_url",
            "evidence_text",
        ]
    ]

    return summary_df.sort_values(
        ["certified_since_normalized"]
    ).reset_index(drop=True)


def build_metadata(
    companies_df: pd.DataFrame,
    certified_since_summary_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    reported_total_count: Optional[int],
    args: argparse.Namespace,
) -> pd.DataFrame:
    metadata = [
        {
            "certification": CERTIFICATION_SHORT_NAME,
            "certification_full_name": CERTIFICATION_NAME,
            "registry_section": REGISTRY_SECTION,
            "source_type": "Dynamic website scraped with Playwright",
            "source_url": START_URL,
            "reported_total_count": reported_total_count,
            "company_rows_extracted": len(companies_df),
            "unique_company_names": companies_df["company_name_normalized"].nunique()
            if not companies_df.empty
            else 0,
            "certified_since_summary_rows": len(certified_since_summary_df),
            "pages_scraped": int(scrape_log_df["page_number"].max())
            if not scrape_log_df.empty and "page_number" in scrape_log_df.columns
            else 0,
            "max_pages_requested": args.max_pages,
            "headless": args.headless,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": (
                "This registry is company-level. The B Corp directory lists certified companies, "
                "not individual certified products. Text fields are sanitized to remove characters "
                "that Excel cannot store in .xlsx worksheets."
            ),
        }
    ]

    return pd.DataFrame(metadata)


def save_outputs(
    companies_df: pd.DataFrame,
    certified_since_summary_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    companies_df = sanitize_dataframe_for_excel(companies_df)
    certified_since_summary_df = sanitize_dataframe_for_excel(certified_since_summary_df)
    scrape_log_df = sanitize_dataframe_for_excel(scrape_log_df)
    metadata_df = sanitize_dataframe_for_excel(metadata_df)

    companies_csv = output_dir / "b_corp_companies.csv"
    certified_since_csv = output_dir / "b_corp_certified_since_summary.csv"
    scrape_log_csv = output_dir / "b_corp_scrape_log.csv"
    metadata_csv = output_dir / "b_corp_metadata.csv"
    excel_path = output_dir / "b_corp_registry.xlsx"

    companies_df.to_csv(companies_csv, index=False, encoding="utf-8-sig")
    certified_since_summary_df.to_csv(
        certified_since_csv,
        index=False,
        encoding="utf-8-sig",
    )
    scrape_log_df.to_csv(scrape_log_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        companies_df.to_excel(writer, sheet_name="companies", index=False)
        certified_since_summary_df.to_excel(
            writer,
            sheet_name="certified_since",
            index=False,
        )
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print("")
    print("Saved files:")
    print(f"- {companies_csv}")
    print(f"- {certified_since_csv}")
    print(f"- {metadata_csv}")
    print(f"- {scrape_log_csv}")
    print(f"- {excel_path}")


def build_b_corp_registry(args: argparse.Namespace) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    all_company_rows: List[Dict[str, object]] = []
    scrape_log: List[Dict[str, object]] = []

    reported_total_count: Optional[int] = None

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

        print("Opening B Corp directory...")
        print(f"Start URL: {START_URL}")
        print(f"Headless: {args.headless}")
        print("")

        page.goto(START_URL, wait_until="domcontentloaded", timeout=args.timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        accept_cookies_if_present(page)
        wait_for_bcorp_results(page, timeout_ms=args.timeout_ms)

        body_text = page.locator("body").inner_text(timeout=args.timeout_ms)
        reported_total_count = extract_reported_total_count(body_text)

        if args.max_pages is not None:
            max_pages = args.max_pages
        elif reported_total_count:
            max_pages = math.ceil(reported_total_count / DEFAULT_RESULTS_PER_PAGE)
        else:
            max_pages = 10000

        print(f"Reported total B Corps: {reported_total_count}")
        print(f"Pages to scrape: {max_pages}")
        print("")

        for page_number in tqdm(range(1, max_pages + 1), desc="Scraping B Corp pages"):
            try:
                wait_for_bcorp_results(page, timeout_ms=args.timeout_ms)

                rows = extract_company_rows(
                    page=page,
                    page_number=page_number,
                )

                all_company_rows.extend(rows)
                all_company_rows = deduplicate_companies(all_company_rows)

                visible_card_count = get_visible_card_count(page)

                scrape_log.append(
                    {
                        "certification": CERTIFICATION_SHORT_NAME,
                        "registry_section": REGISTRY_SECTION,
                        "page_number": page_number,
                        "visible_card_count": visible_card_count,
                        "rows_extracted_on_page": len(rows),
                        "unique_company_rows_collected": len(all_company_rows),
                        "reported_total_count": reported_total_count,
                        "page_url": page.url,
                        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                )

                print(
                    f"Page {page_number}: visible cards {visible_card_count}, "
                    f"rows {len(rows)}, unique collected {len(all_company_rows)}"
                )

                if args.checkpoint_every > 0 and page_number % args.checkpoint_every == 0:
                    try:
                        save_checkpoint(
                            company_rows=all_company_rows,
                            scrape_log=scrape_log,
                            output_dir=OUTPUT_DIR,
                        )
                    except Exception as checkpoint_error:
                        print(f"Checkpoint warning: {checkpoint_error}")

                if reported_total_count is not None and len(all_company_rows) >= reported_total_count:
                    print("Reported total reached. Stopping.")
                    break

                if page_number < max_pages:
                    clicked = click_next_page(page, timeout_ms=args.timeout_ms)

                    if not clicked:
                        print(f"Could not move to next B Corp page after page {page_number}.")
                        save_debug_page(page, f"next_failed_page_{page_number}")
                        break

                    time.sleep(args.page_delay)

            except Exception as error:
                print(f"Error on page {page_number}: {error}")
                save_debug_page(page, f"error_page_{page_number}")

                if args.stop_on_error:
                    raise

                break

        context.close()
        browser.close()

    companies_df = pd.DataFrame(deduplicate_companies(all_company_rows))

    if not companies_df.empty:
        companies_df = companies_df.sort_values(
            [
                "company_name_normalized",
                "profile_url",
            ]
        ).reset_index(drop=True)

    certified_since_summary_df = build_certified_since_summary(companies_df)
    scrape_log_df = pd.DataFrame(scrape_log)

    metadata_df = build_metadata(
        companies_df=companies_df,
        certified_since_summary_df=certified_since_summary_df,
        scrape_log_df=scrape_log_df,
        reported_total_count=reported_total_count,
        args=args,
    )

    print("")
    print("Registry summary:")
    print(f"  Company rows extracted: {len(companies_df)}")
    print(
        "  Unique company names: "
        f"{companies_df['company_name_normalized'].nunique() if not companies_df.empty else 0}"
    )
    print(f"  Reported total count: {reported_total_count}")

    save_outputs(
        companies_df=companies_df,
        certified_since_summary_df=certified_since_summary_df,
        scrape_log_df=scrape_log_df,
        metadata_df=metadata_df,
        output_dir=OUTPUT_DIR,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local B Corp company registry from the official Find a B Corp directory."
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
        help="Maximum pages to scrape. Default: all estimated pages.",
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

    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop immediately if a page fails.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_b_corp_registry(args)


if __name__ == "__main__":
    main()