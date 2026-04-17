import { Button } from "@/components/ui/button";

export function ControlBar() {
  return (
    <section className="grid gap-4 rounded-2xl border border-border bg-card/60 p-4 backdrop-blur-sm md:grid-cols-[1fr_auto] md:items-center">
      <div className="flex flex-wrap items-center gap-4">
        {/* Scheduler status */}
        <div className="flex items-center gap-3 rounded-xl border border-success/30 bg-success/8 px-3.5 py-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full rounded-full bg-success pulse-dot" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
          </span>
          <div className="flex flex-col leading-tight">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-success">
              Agendador
            </span>
            <span className="text-xs font-medium text-foreground">
              Ativo · sincronizado
            </span>
          </div>
          <Button
            size="sm"
            variant="ghost"
            className="ml-2 h-7 bg-destructive/15 px-2.5 text-[11px] font-semibold text-destructive hover:bg-destructive/25"
          >
            Pausar
          </Button>
        </div>

        {/* Week navigator */}
        <div className="flex items-center gap-2 rounded-xl border border-border bg-surface-muted/60 px-2.5 py-1.5">
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7 text-muted-foreground hover:text-foreground"
          >
            <svg
              className="h-3.5 w-3.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth="2.5"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M15 19l-7-7 7-7"
              />
            </svg>
          </Button>
          <div className="flex flex-col items-center px-1 leading-tight">
            <span className="font-mono text-xs font-semibold tabular-nums text-foreground">
              13 abr — 24 abr
            </span>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
              2 semanas · abril 2026
            </span>
          </div>
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7 text-muted-foreground hover:text-foreground"
          >
            <svg
              className="h-3.5 w-3.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth="2.5"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9 5l7 7-7 7"
              />
            </svg>
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          className="border-border bg-transparent text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <svg
            className="mr-1.5 h-3.5 w-3.5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 4v12m0 0l-4-4m4 4l4-4M4 20h16"
            />
          </svg>
          Importar feriados
        </Button>
        <Button
          size="sm"
          className="bg-gradient-to-r from-warning to-pending text-warning-foreground shadow-[0_0_20px_-6px_var(--warning)] hover:opacity-90"
        >
          <svg
            className="mr-1.5 h-3.5 w-3.5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth="2.5"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M13 10V3L4 14h7v7l9-11h-7z"
            />
          </svg>
          Testar agora
        </Button>
      </div>
    </section>
  );
}
