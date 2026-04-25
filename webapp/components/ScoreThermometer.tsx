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
        : "bg-slate-700 text-slate-300",
      track: isLight ? "bg-slate-200" : "bg-slate-800",
    };
  }

  if (value <= 2) {
    return {
      fill: "bg-red-500",
      badge: isLight
        ? "border-red-200 bg-red-50 text-red-700"
        : "bg-red-500/15 text-red-300",
      track: isLight ? "bg-red-100" : "bg-slate-800",
    };
  }

  if (value < 4) {
    return {
      fill: "bg-yellow-400",
      badge: isLight
        ? "border-yellow-200 bg-yellow-50 text-yellow-700"
        : "bg-yellow-400/15 text-yellow-300",
      track: isLight ? "bg-yellow-100" : "bg-slate-800",
    };
  }

  return {
    fill: "bg-emerald-500",
    badge: isLight
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : "bg-emerald-400/15 text-emerald-300",
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
    <div className="flex items-center gap-3">
      <div
        className={`rounded-xl border px-3 py-2 text-sm font-black ${colors.badge}`}
      >
        {formatValue(value)}
      </div>

      <div className="flex items-end gap-2">
        <div
          className={`relative h-14 w-4 overflow-hidden rounded-full border border-black/5 ${colors.track}`}
        >
          <div
            className={`absolute bottom-0 left-0 w-full ${colors.fill} transition-all duration-500`}
            style={{ height: `${percentage}%` }}
          />
        </div>

        <div className={`h-4 w-4 rounded-full ${colors.fill} shadow-lg`} />
      </div>
    </div>
  );
}