"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, Search } from "lucide-react";
import type { CertificationOption } from "@/lib/certificationBadges";

// ── Multi-select dropdown ────────────────────────────────────────────────────

type MultiSelectDropdownProps = {
  label: string;
  options: string[];
  selected: string[];
  onChange: (values: string[]) => void;
  allLabel?: string;
};

function MultiSelectDropdown({
  label,
  options,
  selected,
  onChange,
  allLabel,
}: MultiSelectDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  function toggle(value: string) {
    onChange(
      selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value]
    );
  }

  const buttonLabel =
    selected.length === 0
      ? (allLabel ?? `All ${label.toLowerCase()}`)
      : selected.length === 1
      ? selected[0]
      : `${label} (${selected.length})`;

  return (
    <div ref={ref} className="relative">
      <label className="mb-2 block text-sm font-semibold text-slate-600">
        {label}
      </label>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between rounded-2xl border border-slate-200 bg-white px-4 py-3 text-left outline-none ring-blue-400 transition hover:border-blue-300 focus:ring-2"
      >
        <span
          className={`truncate text-sm ${
            selected.length === 0 ? "text-slate-400" : "text-slate-950"
          }`}
        >
          {buttonLabel}
        </span>
        <ChevronDown
          size={15}
          className={`ml-2 shrink-0 text-slate-400 transition-transform duration-150 ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1.5 max-h-64 w-full overflow-y-auto rounded-2xl border border-slate-200 bg-white p-2 shadow-2xl">
          {options.length === 0 && (
            <p className="px-3 py-2 text-sm text-slate-400">No options</p>
          )}
          {options.map((option) => (
            <label
              key={option}
              className="flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-700 transition hover:bg-blue-50"
            >
              <input
                type="checkbox"
                checked={selected.includes(option)}
                onChange={() => toggle(option)}
                className="h-4 w-4 rounded accent-blue-600"
              />
              <span className="truncate">{option}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Single-select dropdown (with radio bullets) ──────────────────────────────

type SelectOption = { label: string; value: string };

type SingleSelectDropdownProps = {
  label: string;
  options: SelectOption[];
  selected: string;
  onChange: (value: string) => void;
};

function SingleSelectDropdown({
  label,
  options,
  selected,
  onChange,
}: SingleSelectDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  const current = options.find((o) => o.value === selected) ?? options[0];

  return (
    <div ref={ref} className="relative">
      <label className="mb-2 block text-sm font-semibold text-slate-600">
        {label}
      </label>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between rounded-2xl border border-slate-200 bg-white px-4 py-3 text-left outline-none ring-blue-400 transition hover:border-blue-300 focus:ring-2"
      >
        <span className="truncate text-sm text-slate-950">{current?.label}</span>
        <ChevronDown
          size={15}
          className={`ml-2 shrink-0 text-slate-400 transition-transform duration-150 ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1.5 w-full overflow-hidden rounded-2xl border border-slate-200 bg-white p-2 shadow-2xl">
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
              className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition ${
                option.value === selected
                  ? "bg-blue-50 font-semibold text-blue-700"
                  : "text-slate-700 hover:bg-blue-50"
              }`}
            >
              <span
                className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border-2 transition ${
                  option.value === selected
                    ? "border-blue-600 bg-blue-600"
                    : "border-slate-300"
                }`}
              >
                {option.value === selected && (
                  <span className="h-1.5 w-1.5 rounded-full bg-white" />
                )}
              </span>
              {option.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Certification chip ───────────────────────────────────────────────────────

function CertChip({
  cert,
  selected,
  onClick,
}: {
  cert: CertificationOption;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold transition ${
        selected
          ? `border-transparent bg-gradient-to-r ${cert.gradientClassName} text-white shadow-md`
          : "border-slate-200 bg-white text-slate-700 hover:border-blue-200 hover:bg-blue-50"
      }`}
    >
      <span>{cert.emoji}</span>
      <span>{cert.shortLabel}</span>
    </button>
  );
}

// ── Main FilterPanel ─────────────────────────────────────────────────────────

export type FilterPanelProps = {
  industries: string[];
  countries: string[];
  visualizations: string[];
  certificationOptions: CertificationOption[];
  initQ: string;
  initIndustries: string[];
  initCountries: string[];
  initActive: string;
  initVisualizations: string[];
  initSort: string;
  initCertifications: string[];
};

const STATUS_OPTIONS: SelectOption[] = [
  { label: "All", value: "" },
  { label: "Active only", value: "active" },
  { label: "Inactive only", value: "inactive" },
];

const SORT_OPTIONS: SelectOption[] = [
  { label: "Company (A–Z)", value: "" },
  { label: "Overall score", value: "score" },
  { label: "Mobile score", value: "mobile" },
  { label: "Complexity", value: "complexity" },
  { label: "Compatibility", value: "compatibility" },
];

export default function FilterPanel({
  industries,
  countries,
  visualizations,
  certificationOptions,
  initQ,
  initIndustries,
  initCountries,
  initActive,
  initVisualizations,
  initSort,
  initCertifications,
}: FilterPanelProps) {
  const router = useRouter();

  const [q, setQ] = useState(initQ);
  const [selIndustries, setSelIndustries] = useState<string[]>(initIndustries);
  const [selCountries, setSelCountries] = useState<string[]>(initCountries);
  const [active, setActive] = useState(initActive);
  const [selVisualizations, setSelVisualizations] = useState<string[]>(initVisualizations);
  const [sort, setSort] = useState(initSort);
  const [selCerts, setSelCerts] = useState<string[]>(initCertifications);

  const hasFilters =
    Boolean(q) ||
    selIndustries.length > 0 ||
    selCountries.length > 0 ||
    Boolean(active) ||
    selVisualizations.length > 0 ||
    Boolean(sort) ||
    selCerts.length > 0;

  function buildParams() {
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    selIndustries.forEach((v) => params.append("industry", v));
    selCountries.forEach((v) => params.append("country", v));
    if (active) params.set("active", active);
    selVisualizations.forEach((v) => params.append("visualization", v));
    if (sort) params.set("sort", sort);
    selCerts.forEach((v) => params.append("cert", v));
    return params;
  }

  function apply() {
    router.push("/configurators?" + buildParams().toString());
  }

  function clearAll() {
    setQ("");
    setSelIndustries([]);
    setSelCountries([]);
    setActive("");
    setSelVisualizations([]);
    setSort("");
    setSelCerts([]);
    router.push("/configurators");
  }

  function toggleCert(name: string) {
    setSelCerts((prev) =>
      prev.includes(name) ? prev.filter((c) => c !== name) : [...prev, name]
    );
  }

  return (
    <div className="relative overflow-hidden rounded-[2rem] border border-slate-200 bg-white/80 p-5 shadow-xl backdrop-blur">
      <div className="absolute -right-12 -top-12 h-36 w-36 rounded-full bg-blue-300/25 blur-3xl" />

      {/* Header */}
      <div className="relative flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm font-black uppercase tracking-[0.3em] text-blue-600">
            Filters
          </p>
          <h2 className="mt-2 text-2xl font-black text-slate-950">
            Refine your search
          </h2>
        </div>

        {hasFilters && (
          <button
            type="button"
            onClick={clearAll}
            className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-bold text-slate-900 shadow-sm transition hover:bg-blue-50"
          >
            Clear all filters
          </button>
        )}
      </div>

      {/* Row 1: search + main filters */}
      <div className="relative mt-6 grid gap-4 md:grid-cols-3 lg:grid-cols-6">
        <div className="lg:col-span-2">
          <label className="mb-2 block text-sm font-semibold text-slate-600">
            Search
          </label>
          <div className="relative">
            <Search
              size={18}
              className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-400"
            />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && apply()}
              placeholder="Company, product, industry..."
              className="w-full rounded-2xl border border-slate-200 bg-white px-11 py-3 text-slate-950 outline-none ring-blue-400 transition placeholder:text-slate-400 focus:ring-2"
            />
          </div>
        </div>

        <MultiSelectDropdown
          label="Industry"
          options={industries}
          selected={selIndustries}
          onChange={setSelIndustries}
          allLabel="All industries"
        />

        <MultiSelectDropdown
          label="Country"
          options={countries}
          selected={selCountries}
          onChange={setSelCountries}
          allLabel="All countries"
        />

        <SingleSelectDropdown
          label="Status"
          options={STATUS_OPTIONS}
          selected={active}
          onChange={setActive}
        />

        <SingleSelectDropdown
          label="Sort by"
          options={SORT_OPTIONS}
          selected={sort}
          onChange={setSort}
        />

        <MultiSelectDropdown
          label="Visualization"
          options={visualizations}
          selected={selVisualizations}
          onChange={setSelVisualizations}
          allLabel="All types"
        />
      </div>

      {/* Certification filter */}
      <div className="relative mt-6 border-t border-slate-100 pt-5">
        <div className="flex items-baseline gap-3">
          <p className="text-sm font-semibold text-slate-600">Certifications</p>
          {selCerts.length > 0 && (
            <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-bold text-blue-700">
              {selCerts.length} selected
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-slate-400">
          Show only configurators that hold all selected certifications
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {certificationOptions.map((cert) => (
            <CertChip
              key={cert.name}
              cert={cert}
              selected={selCerts.includes(cert.name)}
              onClick={() => toggleCert(cert.name)}
            />
          ))}
        </div>
      </div>

      {/* Actions */}
      <div className="relative mt-5 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={apply}
          className="rounded-2xl bg-blue-600 px-5 py-3 font-bold text-white shadow-lg shadow-blue-500/20 transition hover:-translate-y-0.5 hover:bg-blue-500"
        >
          Apply filters
        </button>

        <button
          type="button"
          onClick={() => {
            setActive("active");
            setSort("score");
            setSelIndustries([]);
            setSelCountries([]);
            setSelVisualizations([]);
            setSelCerts([]);
            setQ("");
            const p = new URLSearchParams();
            p.set("active", "active");
            p.set("sort", "score");
            router.push("/configurators?" + p.toString());
          }}
          className="rounded-2xl border border-slate-200 bg-white px-5 py-3 font-bold text-slate-900 shadow-sm transition hover:-translate-y-0.5 hover:bg-blue-50"
        >
          Best active configurators
        </button>
      </div>
    </div>
  );
}
