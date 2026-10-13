import { Badge } from "@/components/ui/badge";
import { seasonTypeLabel } from "@/lib/format";
import type { PredictionStatus, SeasonType } from "@/lib/types";

export function StatusBadge({ status }: { status: PredictionStatus | null }) {
  if (status === "final") return <Badge>Final</Badge>;
  if (status === "provisional") return <Badge variant="secondary">Provisional</Badge>;
  return <Badge variant="outline">No prediction</Badge>;
}

export function SeasonTypeBadge({ type }: { type: SeasonType }) {
  // The regular season is the default; everything else is flagged
  if (type === "regular") return null;
  return <Badge variant="outline">{seasonTypeLabel(type)}</Badge>;
}
