import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export type PunchState = "executed" | "scheduled" | "pending" | "future";

export interface PunchRowProps {
  label: string;
  scheduled?: string;
  executed?: string;
  state: PunchState;
  editable?: boolean;
  punchable?: boolean;
  isLast?: boolean;
}

const dotStyles: Record<PunchState, string> = {
  executed:
    "bg-success border-success shadow-[0_0_12px_var(--success-glow)]",
  scheduled: "bg-pending border-pending/70",
  pending: "bg-warning border-warning/70 animate-pulse",
  future: "bg-muted border-border-strong",
};

const timeStyles: Record<PunchState, string> = {
  executed: "text-success",
  scheduled: "text-pending",
  pending: "text-warning",
  future: "text-muted-foreground",
};

export function PunchRow({
  label,
  scheduled,
  executed,
  state,
  editable,
  punchable,
  isLast,
}: PunchRowProps) {
  return (
    <div className="relative flex items-start gap-3">
      {/* Timeline rail */}
      <div className="relative flex flex-col items-center pt-1.5">
        <div
          className={cn(
            "h-2.5 w-2.5 rounded-full border-2 transition-all",
            dotStyles[state],
          )}
        />
        {!isLast && (
          <div className="mt-1 h-full w-px flex-1 bg-gradient-to-b from-border-strong/60 to-transparent" />
        )}
      </div>

      <div className="flex-1 pb-3.5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            {label}
          </span>
          {(editable || punchable) && (
            <div className="flex items-center gap-1">
              {editable && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-[10px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  Editar
                </Button>
              )}
              {punchable && (
                <Button
                  size="sm"
                  className="h-6 bg-primary px-2 text-[10px] font-semibold text-primary-foreground hover:bg-primary/90"
                >
                  Bater
                </Button>
              )}
            </div>
          )}
        </div>

        <div className="mt-1 flex items-baseline gap-3 font-mono text-sm">
          <span className={cn("font-semibold tabular-nums", timeStyles[state])}>
            {scheduled ?? "—:—"}
          </span>
          {executed ? (
            <span className="text-xs text-success/90 tabular-nums">
              ✓ {executed}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground/50">aguardando</span>
          )}
        </div>
      </div>
    </div>
  );
}
