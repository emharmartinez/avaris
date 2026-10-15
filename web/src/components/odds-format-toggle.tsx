import { Button } from "@/components/ui/button";
import type { OddsFormat } from "@/lib/edge";

const LABELS: Record<OddsFormat, string> = { decimal: "Decimal", american: "American" };

// Decimal or American prices, for the Edge and Traditional tabs
export function OddsFormatToggle({ value, onChange }: {
  value: OddsFormat;
  onChange: (f: OddsFormat) => void;
}) {
  return (
    <div role="group" aria-label="Odds format" className="flex gap-1">
      {(["decimal", "american"] as const).map((f) => (
        <Button
          key={f} size="sm" variant={f === value ? "secondary" : "ghost"}
          aria-pressed={f === value} onClick={() => onChange(f)}
        >
          {LABELS[f]}
        </Button>
      ))}
    </div>
  );
}
