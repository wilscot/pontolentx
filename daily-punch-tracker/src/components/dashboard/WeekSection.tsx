import { DayCard, type DayCardProps } from "./DayCard";

interface WeekSectionProps {
  title: string;
  range: string;
  days: DayCardProps[];
  baseIndex?: number;
}

export function WeekSection({
  title,
  range,
  days,
  baseIndex = 0,
}: WeekSectionProps) {
  return (
    <section>
      <div className="mb-3 flex items-baseline justify-between">
        <div className="flex items-baseline gap-3">
          <h2 className="text-[11px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
            {title}
          </h2>
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground/70">
            {range}
          </span>
        </div>
        <div className="h-px flex-1 mx-4 bg-gradient-to-r from-border-strong/40 to-transparent" />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {days.map((d, i) => (
          <DayCard key={d.date} {...d} index={baseIndex + i} />
        ))}
      </div>
    </section>
  );
}
