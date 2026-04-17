import { cn } from "@/lib/utils";

type Status = "normal" | "today" | "holiday" | "overtime";

const styles: Record<Status, string> = {
  normal:
    "bg-muted/60 text-muted-foreground border border-border-strong/40",
  today:
    "bg-primary/15 text-primary border border-primary/40 shadow-[0_0_20px_-6px_var(--primary)]",
  holiday:
    "bg-[color:var(--holiday)]/15 text-[color:var(--holiday)] border border-[color:var(--holiday)]/40",
  overtime:
    "bg-[color:var(--overtime)]/15 text-[color:var(--overtime)] border border-[color:var(--overtime)]/40",
};

const labels: Record<Status, string> = {
  normal: "Normal",
  today: "Hoje",
  holiday: "Feriado",
  overtime: "Extra",
};

export function StatusBadge({
  status,
  children,
}: {
  status: Status;
  children?: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
        styles[status],
      )}
    >
      {children ?? labels[status]}
    </span>
  );
}
