from pathlib import Path
import re


PAGE_PATH = Path("webapp") / "app" / "configurators" / "[slug]" / "page.tsx"

IMPORT_LINE = 'import ConfiguratorCertificationSection from "@/components/ConfiguratorCertificationSection";'

COMPONENT_LINES = [
    "",
    "          <ConfiguratorCertificationSection",
    "            company={configurator.company}",
    "            product={configurator.product}",
    "          />",
    "",
]


def patch_import(content: str) -> str:
    if IMPORT_LINE in content:
        return content

    lines = content.splitlines()
    last_import_index = -1

    for index, line in enumerate(lines):
        if line.startswith("import "):
            last_import_index = index

    if last_import_index == -1:
        raise RuntimeError("Could not find import section in page.tsx")

    lines.insert(last_import_index + 1, IMPORT_LINE)

    return "\n".join(lines) + "\n"


def component_already_inserted(content: str) -> bool:
    return (
        "ConfiguratorCertificationSection" in content
        and "company={configurator.company}" in content
        and "product={configurator.product}" in content
    )


def patch_component_before_aside(content: str) -> str:
    if component_already_inserted(content):
        return content

    lines = content.splitlines()

    aside_index = None

    for index, line in enumerate(lines):
        if re.search(r"<aside\b", line):
            aside_index = index
            break

    if aside_index is None:
        return content

    closing_index = None

    for index in range(aside_index - 1, -1, -1):
        stripped = lines[index].strip()

        if not stripped:
            continue

        if stripped in {"</div>", "</motion.div>", "</AnimatedSection>"}:
            closing_index = index
            break

        if index < aside_index - 40:
            break

    if closing_index is None:
        return content

    patched_lines = (
        lines[:closing_index]
        + COMPONENT_LINES
        + lines[closing_index:]
    )

    return "\n".join(patched_lines) + "\n"


def patch_component_before_links_section(content: str) -> str:
    if component_already_inserted(content):
        return content

    patterns = [
        r'(\n\s*<div\s+className="[^"]*mt-6[^"]*rounded-3xl[^"]*"[^>]*>\s*\n\s*<h2[^>]*>\s*Links\s*</h2>)',
        r'(\n\s*<section\s+className="[^"]*mt-6[^"]*"[^>]*>\s*\n\s*<h2[^>]*>\s*Links\s*</h2>)',
    ]

    component_block = "\n".join(COMPONENT_LINES)

    for pattern in patterns:
        match = re.search(pattern, content, flags=re.DOTALL)

        if match:
            return content[: match.start()] + component_block + content[match.start():]

    return content


def patch_component_before_left_column_close_regex(content: str) -> str:
    if component_already_inserted(content):
        return content

    component_block = "\n".join(COMPONENT_LINES)

    patterns = [
        r"(\n\s*</div>\s*\n\s*<aside\b)",
        r"(\n\s*</motion\.div>\s*\n\s*<aside\b)",
        r"(\n\s*</AnimatedSection>\s*\n\s*<aside\b)",
    ]

    for pattern in patterns:
        match = re.search(pattern, content)

        if match:
            return content[: match.start()] + component_block + content[match.start():]

    return content


def patch_component_fallback_before_aside(content: str) -> str:
    if component_already_inserted(content):
        return content

    component_block = "\n".join(COMPONENT_LINES)

    match = re.search(r"\n\s*<aside\b", content)

    if not match:
        return content

    return content[: match.start()] + component_block + content[match.start():]


def patch_component(content: str) -> str:
    if component_already_inserted(content):
        return content

    original = content

    content = patch_component_before_aside(content)

    if component_already_inserted(content):
        return content

    content = patch_component_before_links_section(original)

    if component_already_inserted(content):
        return content

    content = patch_component_before_left_column_close_regex(original)

    if component_already_inserted(content):
        return content

    content = patch_component_fallback_before_aside(original)

    if component_already_inserted(content):
        return content

    raise RuntimeError(
        "Could not find a safe insertion point. Please paste ConfiguratorCertificationSection manually inside the detail page."
    )


def main() -> None:
    if not PAGE_PATH.exists():
        raise FileNotFoundError(f"Page file not found: {PAGE_PATH}")

    original = PAGE_PATH.read_text(encoding="utf-8")

    backup_path = PAGE_PATH.with_suffix(".tsx.bak")
    backup_path.write_text(original, encoding="utf-8")

    content = patch_import(original)
    content = patch_component(content)

    if content == original:
        print("No changes needed. Page already patched.")
        return

    PAGE_PATH.write_text(content, encoding="utf-8")

    print(f"Patched successfully: {PAGE_PATH}")
    print(f"Backup created: {backup_path}")


if __name__ == "__main__":
    main()