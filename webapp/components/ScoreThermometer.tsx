type ScoreThermometerProps = {
  value: number | null;
  variant?: "dark" | "light";
};

function formatValue(value: number | null) {
  if (value === null) return "N/A";
  return Number.isInteger(value) ? `${value}/5` : `${value.toFixed(2)}/5`;
}

function getColorClasses(value: number | null, variant: "dark" | "light") {
  const isLight = variant === "light";

  if (value == null) {
    return {
      fill: "bg-slate-400",
      badge: isLight
        ? "border-slate-200 bg-slate-100 text-slate-600"
        : "border-slate-700 bg-slate-800 text-slate-300",
      track: isLight ? "bg-slate-200" : "bg-slate-800",
    };
  }

  if (value <= 2) {
    return {
      fill: "bg-red-500",
      badge: isLight
        ? "border-red-200 bg-red-50 text-red-700"
        : "border-red-500/20 bg-red-500/15 text-red-300",
      track: isLight ? "bg-red-100" : "bg-slate-800",
    };
  }

  if (value < 4) {
    return {
      fill: "bg-yellow-400",
      badge: isLight
        ? "border-yellow-200 bg-yellow-50 text-yellow-700"
        : "border-yellow-400/20 bg-yellow-400/15 text-yellow-300",
      track: isLight ? "bg-yellow-100" : "bg-slate-800",
    };
  }

  return {
    fill: "bg-emerald-500",
    badge: isLight
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : "border-emerald-400/20 bg-emerald-400/15 text-emerald-300",
    track: isLight ? "bg-emerald-100" : "bg-slate-800",
  };
}

export default function ScoreThermometer({
  value,
  variant = "dark",
}: ScoreThermometerProps) {
  const numericValue =
    typeof value === "number" ? Math.max(0, Math.min(5, value)) : 0;

  const percentage = (numericValue / 5) * 100;
  const colors = getColorClasses(value, variant);

  return (
    <div className="flex shrink-0 items-center gap-2 sm:gap-3">
      <div
        className={`whitespace-nowrap rounded-xl border px-2.5 py-1.5 text-xs font-black sm:px-3 sm:py-2 sm:text-sm ${colors.badge}`}
      >
        {formatValue(value)}
      </div>

      <div className="flex items-end gap-1.5 sm:gap-2">
        <div
          className={`relative h-10 w-3 overflow-hidden rounded-full border border-black/5 sm:h-14 sm:w-4 ${colors.track}`}
        >
          <div
            className={`absolute bottom-0 left-0 w-full ${colors.fill} transition-all duration-500`}
            style={{ height: `${percentage}%` }}
          />
        </div>

        <div
          className={`h-3 w-3 rounded-full shadow-lg sm:h-4 sm:w-4 ${colors.fill}`}
        />
      </div>
    </div>
  );
}