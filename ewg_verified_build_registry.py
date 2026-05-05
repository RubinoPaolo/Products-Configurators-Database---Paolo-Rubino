import argparse
import hashlib
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


CERTIFICATION_NAME = "EWG Verified"
REGISTRY_SECTION = "Verified Products"

START_URL = (
    "https://www.ewg.org/ewgverified/products.php?"
    "models=cosmetic%2Cdiaper&search=&minority_owned=&brand=&category=&sort=newest&type="
)

OUTPUT_DIR = Path("data") / "certifications" / "ewg_verified"
DEBUG_DIR = OUTPUT_DIR / "debug"

DEFAULT_MAX_LOAD_CLICKS = 400


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


def make_product_key(product_name: str, more_info_url: str) -> str:
    raw_key = f"{normalize_for_matching(product_name)}|{clean_text(more_info_url)}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def extract_total_count(text: str) -> Optional[int]:
    patterns = [
        r"We\s+found\s+([0-9,]+)\s+items",
        r"found\s+([0-9,]+)\s+items",
        r"([0-9,]+)\s+items\s+that\s+are\s+EWG\s+Verified",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)

        if match:
            return int(match.group(1).replace(",", ""))

    return None


def extract_brand_guess(product_name: str) -> str:
    product_name = clean_text(product_name)

    if not product_name:
        return ""

    separators = [
        " - ",
        " – ",
        " — ",
        ": ",
    ]

    for separator in separators:
        if separator in product_name:
            possible_brand = product_name.split(separator, 1)[0].strip()

            if 1 <= len(possible_brand.split()) <= 5:
                return possible_brand

    first_words = product_name.split()

    if len(first_words) >= 2:
        first_two = " ".join(first_words[:2])

        if first_two.lower() in {
            "dr bronner's",
            "the honest",
            "baby forest",
            "caboo bamboo",
            "thinkbaby clear",
        }:
            return first_two

    if first_words:
        return first_words[0]

    return ""


def absolute_url_from_page(page: Page, url: str) -> str:
    if not url:
        return ""

    try:
        return page.evaluate(
            """
            ([rawUrl]) => {
              try {
                return new URL(rawUrl, window.location.href).href;
              } catch {
                return "";
              }
            }
            """,
            [url],
        )
    except Exception:
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
        text_path.write_text(body_text, encoding="utf-8", errors="ignore")
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
        re.compile(r"reject", flags=re.IGNORECASE),
        re.compile(r"continue", flags=re.IGNORECASE),
    ]

    for pattern in cookie_patterns:
        try:
            button = page.get_by_role("button", name=pattern).first

            if button.is_visible(timeout=1000):
                button.click(timeout=3000)
                time.sleep(0.6)
                return
        except Exception:
            continue


def wait_for_product_listing(page: Page, timeout_ms: int) -> None:
    try:
        page.wait_for_function(
            """
            () => {
              const text = document.body.innerText || "";
              const hasCount = /We\\s+found\\s+[0-9,]+\\s+items/i.test(text);
              const productCards = document.querySelectorAll(
                ".product-wrapper .product-tile .just-verified-carousel-item-name p"
              );

              return hasCount && productCards.length > 0;
            }
            """,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        save_debug_page(page, "wait_for_product_listing_timeout")
        raise


def get_visible_product_count(page: Page) -> int:
    try:
        return int(
            page.evaluate(
                """
                () => {
                  const wrappers = Array.from(document.querySelectorAll(".product-wrapper"));

                  return wrappers.filter((wrapper) => {
                    const nameNode = wrapper.querySelector(".just-verified-carousel-item-name p");
                    const tileNode = wrapper.querySelector(".product-tile");
                    const style = window.getComputedStyle(wrapper);
                    const rect = wrapper.getBoundingClientRect();

                    return (
                      nameNode &&
                      tileNode &&
                      style.display !== "none" &&
                      style.visibility !== "hidden" &&
                      rect.width > 0 &&
                      rect.height > 0
                    );
                  }).length;
                }
                """
            )
        )
    except Exception:
        return 0


def extract_visible_products(page: Page) -> List[Dict[str, object]]:
    raw_products = page.evaluate(
        """
        () => {
          function cleanText(text) {
            return (text || "")
              .replace(/\\u00a0/g, " ")
              .replace(/[ \\t]+/g, " ")
              .replace(/\\n\\s+/g, "\\n")
              .trim();
          }

          function absoluteUrl(url) {
            if (!url) return "";

            try {
              return new URL(url, window.location.href).href;
            } catch {
              return "";
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

          function getBestImageUrl(img) {
            if (!img) return "";

            const srcset = img.getAttribute("srcset") || "";

            if (srcset) {
              const first = srcset.split(",")[0].trim();
              const firstUrl = first.split(" ")[0].trim();

              if (firstUrl) {
                return absoluteUrl(firstUrl);
              }
            }

            return absoluteUrl(
              img.getAttribute("data-src") ||
              img.getAttribute("src") ||
              ""
            );
          }

          const wrappers = Array.from(document.querySelectorAll(".product-wrapper"));
          const rows = [];

          for (const wrapper of wrappers) {
            if (!isVisible(wrapper)) {
              continue;
            }

            const nameNode = wrapper.querySelector(".just-verified-carousel-item-name p");
            const productLinkNode =
              wrapper.querySelector("a.product-more-info-a[href]") ||
              wrapper.querySelector("a.just-verified-carousel-item-link[href]");

            const tileNode = wrapper.querySelector(".product-tile");

            if (!nameNode || !tileNode) {
              continue;
            }

            const productName = cleanText(nameNode.innerText || nameNode.textContent || "");

            if (!productName) {
              continue;
            }

            const productUrl = productLinkNode
              ? absoluteUrl(productLinkNode.getAttribute("href") || "")
              : "";

            const imageNode = wrapper.querySelector(".just-verified-carousel-item-image img");
            const imageUrl = getBestImageUrl(imageNode);
            const imageAlt = imageNode ? cleanText(imageNode.getAttribute("alt") || "") : "";

            const whereToFindLinks = Array.from(
              wrapper.querySelectorAll(".product-where-to-find-popup a[href]")
            ).map((link) => {
              return {
                label: cleanText(link.innerText || link.textContent || ""),
                url: absoluteUrl(link.getAttribute("href") || "")
              };
            });

            const whereToFindUrls = whereToFindLinks
              .map((item) => item.url)
              .filter(Boolean)
              .join(" | ");

            const whereToFindLabels = whereToFindLinks
              .map((item) => item.label)
              .filter(Boolean)
              .join(" | ");

            const hasNewBadge = Boolean(wrapper.querySelector(".just-verified-new"));

            const rect = wrapper.getBoundingClientRect();

            rows.push({
              product_name: productName,
              product_url: productUrl,
              image_url: imageUrl,
              image_alt: imageAlt,
              where_to_find_urls: whereToFindUrls,
              where_to_find_labels: whereToFindLabels,
              has_new_badge: hasNewBadge,
              evidence_text: cleanText(wrapper.innerText || wrapper.textContent || ""),
              card_x: rect.x,
              card_y: rect.y,
              card_width: rect.width,
              card_height: rect.height
            });
          }

          return rows;
        }
        """
    )

    products = []

    for raw_product in raw_products:
        product_name = clean_text(raw_product.get("product_name", ""))
        product_url = clean_text(raw_product.get("product_url", ""))

        if not product_name:
            continue

        product_key = make_product_key(
            product_name=product_name,
            more_info_url=product_url,
        )

        brand_guess = extract_brand_guess(product_name)

        products.append(
            {
                "certification": CERTIFICATION_NAME,
                "registry_section": REGISTRY_SECTION,
                "registry_source": "EWG Verified product listing",
                "product_key": product_key,
                "product_name": product_name,
                "product_name_normalized": normalize_for_matching(product_name),
                "brand_guess": brand_guess,
                "brand_guess_normalized": normalize_for_matching(brand_guess),
                "product_url": product_url,
                "image_url": clean_text(raw_product.get("image_url", "")),
                "image_alt": clean_text(raw_product.get("image_alt", "")),
                "where_to_find_urls": clean_text(raw_product.get("where_to_find_urls", "")),
                "where_to_find_labels": clean_text(raw_product.get("where_to_find_labels", "")),
                "has_new_badge": bool(raw_product.get("has_new_badge")),
                "evidence_text": clean_text(raw_product.get("evidence_text", "")),
                "card_x": raw_product.get("card_x"),
                "card_y": raw_product.get("card_y"),
                "card_width": raw_product.get("card_width"),
                "card_height": raw_product.get("card_height"),
                "source_url": START_URL,
                "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

    return products


def click_load_more(page: Page, timeout_ms: int) -> bool:
    previous_count = get_visible_product_count(page)

    try:
        page.locator("#pcps-products-load-more").scroll_into_view_if_needed(timeout=5000)
    except Exception:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(0.6)

    try:
        load_more_button = page.locator("#pcps-products-load-more")

        if load_more_button.count() == 0:
            print("Load More button not found with selector #pcps-products-load-more.")
            return False

        if not load_more_button.first.is_visible(timeout=3000):
            print("Load More button exists but is not visible.")
            return False

        button_text = clean_text(load_more_button.first.inner_text(timeout=3000))

        if not re.search(r"LOAD\s+MORE", button_text, flags=re.IGNORECASE):
            print(f"Load More selector found, but text is unexpected: {button_text}")
            return False

        load_more_button.first.click(timeout=8000)

    except Exception as error:
        print(f"Load More click failed: {error}")
        return False

    try:
        page.wait_for_function(
            """
            (previousCount) => {
              const wrappers = Array.from(document.querySelectorAll(".product-wrapper"));

              const count = wrappers.filter((wrapper) => {
                const nameNode = wrapper.querySelector(".just-verified-carousel-item-name p");
                const tileNode = wrapper.querySelector(".product-tile");
                const style = window.getComputedStyle(wrapper);
                const rect = wrapper.getBoundingClientRect();

                return (
                  nameNode &&
                  tileNode &&
                  style.display !== "none" &&
                  style.visibility !== "hidden" &&
                  rect.width > 0 &&
                  rect.height > 0
                );
              }).length;

              return count > previousCount;
            }
            """,
            arg=previous_count,
            timeout=timeout_ms,
        )

        return True

    except Exception:
        new_count = get_visible_product_count(page)

        if new_count > previous_count:
            return True

        print(
            "Warning: Load More was clicked but product count did not increase. "
            f"Previous count: {previous_count}, new count: {new_count}."
        )

        return False


def deduplicate_products(products: List[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    deduped = []

    for product in products:
        product_key = clean_text(product.get("product_key", ""))

        if not product_key:
            product_key = make_product_key(
                product_name=str(product.get("product_name", "")),
                more_info_url=str(product.get("product_url", "")),
            )

        if product_key in seen:
            continue

        seen.add(product_key)
        deduped.append(product)

    return deduped


def save_checkpoint(
    products: List[Dict[str, object]],
    scrape_log: List[Dict[str, object]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    products_df = pd.DataFrame(deduplicate_products(products))
    scrape_log_df = pd.DataFrame(scrape_log)

    checkpoint_path = output_dir / "ewg_verified_registry_CHECKPOINT.xlsx"

    with pd.ExcelWriter(checkpoint_path, engine="openpyxl") as writer:
        products_df.to_excel(writer, sheet_name="products", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print(f"Checkpoint saved: {checkpoint_path}")


def build_brands_registry(products_df: pd.DataFrame) -> pd.DataFrame:
    if products_df.empty or "brand_guess_normalized" not in products_df.columns:
        return pd.DataFrame()

    brands_df = (
        products_df[products_df["brand_guess_normalized"].str.len() > 0]
        .groupby(["brand_guess", "brand_guess_normalized"], dropna=False)
        .agg(
            certified_product_rows=("product_name", "count"),
            product_names=("product_name", lambda values: " | ".join(sorted(set(values))[:30])),
            product_urls=("product_url", lambda values: " | ".join(sorted(set(values))[:30])),
            source_url=("source_url", "first"),
        )
        .reset_index()
    )

    brands_df["certification"] = CERTIFICATION_NAME
    brands_df["registry_section"] = "Brand guesses from product names"
    brands_df["registry_match_level"] = "brand_guess"

    brands_df["evidence_text"] = brands_df.apply(
        lambda row: (
            f"{row['brand_guess']} appears in {row['certified_product_rows']} "
            f"EWG Verified product row(s)."
        ),
        axis=1,
    )

    brands_df = brands_df[
        [
            "certification",
            "registry_section",
            "registry_match_level",
            "brand_guess",
            "brand_guess_normalized",
            "certified_product_rows",
            "product_names",
            "product_urls",
            "source_url",
            "evidence_text",
        ]
    ]

    brands_df = brands_df.sort_values(
        ["brand_guess_normalized"]
    ).reset_index(drop=True)

    return brands_df


def build_metadata(
    products_df: pd.DataFrame,
    brands_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    reported_total_count: Optional[int],
    args: argparse.Namespace,
) -> pd.DataFrame:
    metadata = [
        {
            "certification": CERTIFICATION_NAME,
            "registry_section": REGISTRY_SECTION,
            "source_url": START_URL,
            "source_type": "Dynamic website scraped with Playwright",
            "reported_total_count": reported_total_count,
            "product_rows_extracted": len(products_df),
            "unique_product_names": products_df["product_name_normalized"].nunique()
            if not products_df.empty
            else 0,
            "brand_guess_rows": len(brands_df),
            "load_more_clicks_executed": int(scrape_log_df["load_click_number"].max())
            if not scrape_log_df.empty and "load_click_number" in scrape_log_df.columns
            else 0,
            "max_load_clicks_requested": args.max_load_clicks,
            "headless": args.headless,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": (
                "Registry built from the EWG Verified public product listing. "
                "Product cards are parsed from .product-wrapper elements and additional rows "
                "are loaded through #pcps-products-load-more."
            ),
        }
    ]

    return pd.DataFrame(metadata)


def save_outputs(
    products_df: pd.DataFrame,
    brands_df: pd.DataFrame,
    scrape_log_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    products_csv = output_dir / "ewg_verified_products.csv"
    brands_csv = output_dir / "ewg_verified_brand_guesses.csv"
    scrape_log_csv = output_dir / "ewg_verified_scrape_log.csv"
    metadata_csv = output_dir / "ewg_verified_metadata.csv"
    excel_path = output_dir / "ewg_verified_registry.xlsx"

    products_df.to_csv(products_csv, index=False, encoding="utf-8-sig")
    brands_df.to_csv(brands_csv, index=False, encoding="utf-8-sig")
    scrape_log_df.to_csv(scrape_log_csv, index=False, encoding="utf-8-sig")
    metadata_df.to_csv(metadata_csv, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        products_df.to_excel(writer, sheet_name="products", index=False)
        brands_df.to_excel(writer, sheet_name="brand_guesses", index=False)
        metadata_df.to_excel(writer, sheet_name="metadata", index=False)
        scrape_log_df.to_excel(writer, sheet_name="scrape_log", index=False)

    print("")
    print("Saved files:")
    print(f"- {products_csv}")
    print(f"- {brands_csv}")
    print(f"- {metadata_csv}")
    print(f"- {scrape_log_csv}")
    print(f"- {excel_path}")


def build_ewg_verified_registry(args: argparse.Namespace) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    all_products: List[Dict[str, object]] = []
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

        print("Opening EWG Verified product listing...")
        print(f"Start URL: {START_URL}")
        print(f"Max Load More clicks: {args.max_load_clicks}")
        print(f"Headless: {args.headless}")
        print("")

        page.goto(START_URL, wait_until="domcontentloaded", timeout=args.timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        accept_cookies_if_present(page)
        wait_for_product_listing(page, timeout_ms=args.timeout_ms)

        body_text = page.locator("body").inner_text(timeout=args.timeout_ms)
        reported_total_count = extract_total_count(body_text)

        initial_products = extract_visible_products(page)
        all_products.extend(initial_products)
        all_products = deduplicate_products(all_products)

        visible_count = get_visible_product_count(page)

        scrape_log.append(
            {
                "certification": CERTIFICATION_NAME,
                "event": "initial_page",
                "load_click_number": 0,
                "visible_product_count": visible_count,
                "unique_products_collected": len(all_products),
                "reported_total_count": reported_total_count,
                "page_url": page.url,
                "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

        print(
            f"Initial page: visible cards {visible_count}, "
            f"unique products collected {len(all_products)}, "
            f"reported total {reported_total_count}"
        )

        if len(all_products) == 0:
            save_debug_page(page, "no_products_initial")
            print("No products were extracted from the initial page. Stopping.")

        else:
            for load_click_number in tqdm(
                range(1, args.max_load_clicks + 1),
                desc="Clicking Load More",
            ):
                if reported_total_count is not None and len(all_products) >= reported_total_count:
                    print("Reported total reached. Stopping.")
                    break

                clicked = click_load_more(page, timeout_ms=args.timeout_ms)

                if not clicked:
                    print(f"Could not click Load More at click {load_click_number}. Stopping.")
                    save_debug_page(page, f"load_more_failed_click_{load_click_number}")
                    break

                time.sleep(args.load_delay)

                visible_products = extract_visible_products(page)
                all_products.extend(visible_products)
                all_products = deduplicate_products(all_products)

                visible_count = get_visible_product_count(page)

                scrape_log.append(
                    {
                        "certification": CERTIFICATION_NAME,
                        "event": "load_more",
                        "load_click_number": load_click_number,
                        "visible_product_count": visible_count,
                        "unique_products_collected": len(all_products),
                        "reported_total_count": reported_total_count,
                        "page_url": page.url,
                        "scraped_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                )

                print(
                    f"Load More {load_click_number}: visible cards {visible_count}, "
                    f"unique products collected {len(all_products)}"
                )

                if args.checkpoint_every > 0 and load_click_number % args.checkpoint_every == 0:
                    save_checkpoint(
                        products=all_products,
                        scrape_log=scrape_log,
                        output_dir=OUTPUT_DIR,
                    )

        products_df = pd.DataFrame(deduplicate_products(all_products))

        if not products_df.empty:
            products_df = products_df.sort_values(
                ["product_name_normalized", "product_url"]
            ).reset_index(drop=True)

        brands_df = build_brands_registry(products_df)
        scrape_log_df = pd.DataFrame(scrape_log)

        metadata_df = build_metadata(
            products_df=products_df,
            brands_df=brands_df,
            scrape_log_df=scrape_log_df,
            reported_total_count=reported_total_count,
            args=args,
        )

        save_outputs(
            products_df=products_df,
            brands_df=brands_df,
            scrape_log_df=scrape_log_df,
            metadata_df=metadata_df,
            output_dir=OUTPUT_DIR,
        )

        context.close()
        browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a local EWG Verified product registry by scraping the public EWG Verified "
            "product listing and clicking Load More until products are collected."
        )
    )

    parser.add_argument(
        "--max-load-clicks",
        type=int,
        default=DEFAULT_MAX_LOAD_CLICKS,
        help=f"Maximum number of Load More clicks. Default: {DEFAULT_MAX_LOAD_CLICKS}",
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
        "--load-delay",
        type=float,
        default=0.8,
        help="Delay after each Load More click, in seconds. Default: 0.8",
    )

    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=20,
        help="Save checkpoint every N Load More clicks. Default: 20",
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
        default=1100,
        help="Browser viewport height. Default: 1100",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_ewg_verified_registry(args)


if __name__ == "__main__":
    main()