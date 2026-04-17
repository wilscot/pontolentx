import { cn } from "@/lib/utils";
import { StatusBadge } from "./StatusBadge";
import { PunchRow, type PunchRowProps } from "./PunchRow";

export type DayStatus = "completed" | "today" | "future" | "holiday";

export interface DayCardProps {
  weekday: string;
  date: string;
  status: DayStatus;
  punches?: PunchRowProps[];
  overtime?: string;
  holidayName?: string;
  index?: number;
}

export function DayCard({
  weekday,
  date,
  status,
  punches,
  overtime,
  holidayName,
  index = 0,
}: DayCardProps) {
  const isToday = status === "today";
  const isHoliday = status === "holiday";

  return (
    <article
      style={{ animationDelay: `${index * 40}ms` }}
      className={cn(
        "fade-up group relative flex flex-col rounded-2xl border bg-card p-5 transition-all duration-300",
        "hover:-translate-y-0.5 hover:shadow-[var(--shadow-card-hover)]",
        isToday
          ? "border-primary/50 ring-glow-primary"
          : "border-border shadow-[var(--shadow-card)] hover:border-border-strong",
        isHoliday && "border-[color:var(--holiday)]/30",
      )}
    >
      {/* Header */}
      <header className="mb-4 flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            {weekday}
          </p>
          <p
            className={cn(
              "mt-0.5 font-mono text-2xl font-bold tabular-nums",
              isToday ? "text-gradient-primary" : "text-foreground",
            )}
          >
            {date}
          </p>
        </div>
        <StatusBadge
          status={
            isToday
              ? "today"
              : isHoliday
                ? "holiday"
                : overtime
                  ? "overtime"
                  : "normal"
          }
        />
      </header>

      {/* Body */}
      {isHoliday ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 py-6">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[color:var(--holiday)]/15">
            <svg
              className="h-5 w-5 text-[color:var(--holiday)]"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
          <p className="text-sm font-medium text-foreground">{holidayName}</p>
          <p className="text-xs text-muted-foreground">Feriado nacional</p>
        </div>
      ) : (
        <div className="flex-1">
          {punches?.map((p, i) => (
            <PunchRow key={i} {...p} isLast={i === punches.length - 1} />
          ))}
        </div>
      )}

      {/* Overtime footer */}
      {overtime && !isHoliday && (
        <div className="mt-2 flex items-center justify-between rounded-xl border border-[color:var(--overtime)]/25 bg-[color:var(--overtime)]/8 px-3 py-2">
          <div className="flex items-center gap-2">
            <div className="h-1.5 w-1.5 rounded-full bg-[color:var(--overtime)]" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-[color:var(--overtime)]">
              Hora extra
            </span>
          </div>
          <span className="font-mono text-sm font-bold tabular-nums text-[color:var(--overtime)]">
            +{overtime}
          </span>
        </div>
      )}
    </article>
  );
}
