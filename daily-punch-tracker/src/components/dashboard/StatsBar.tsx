interface Stat {
  label: string;
  value: string;
  hint?: string;
  accent?: "success" | "primary" | "overtime" | "muted";
}

const accentClass: Record<NonNullable<Stat["accent"]>, string> = {
  success: "text-success",
  primary: "text-gradient-primary",
  overtime: "text-[color:var(--overtime)]",
  muted: "text-foreground",
};

export function StatsBar() {
  const stats: Stat[] = [
    {
      label: "Pontos batidos",
      value: "16/20",
      hint: "esta quinzena",
      accent: "success",
    },
    {
      label: "Horas trabalhadas",
      value: "67h 12m",
      hint: "de 80h previstas",
      accent: "muted",
    },
    {
      label: "Banco de horas",
      value: "+1h 31m",
      hint: "saldo positivo",
      accent: "overtime",
    },
    {
      label: "Próximo ponto",
      value: "11:32",
      hint: "pausa almoço · hoje",
      accent: "primary",
    },
  ];

  return (
    <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {stats.map((s, i) => (
        <div
          key={s.label}
          style={{ animationDelay: `${i * 60}ms` }}
          className="fade-up group relative overflow-hidden rounded-2xl border border-border bg-card p-4 transition-colors hover:border-border-strong"
        >
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-primary/30 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            {s.label}
          </p>
          <p
            className={`mt-2 font-mono text-2xl font-bold tabular-nums ${
              accentClass[s.accent ?? "muted"]
            }`}
          >
            {s.value}
          </p>
          {s.hint && (
            <p className="mt-0.5 text-[11px] text-muted-foreground">{s.hint}</p>
          )}
        </div>
      ))}
    </section>
  );
}
