import { createFileRoute } from "@tanstack/react-router";
import { Header } from "@/components/dashboard/Header";
import { ControlBar } from "@/components/dashboard/ControlBar";
import { StatsBar } from "@/components/dashboard/StatsBar";
import { WeekSection } from "@/components/dashboard/WeekSection";
import type { DayCardProps } from "@/components/dashboard/DayCard";

export const Route = createFileRoute("/")({
  component: Dashboard,
});

const currentWeek: DayCardProps[] = [
  {
    weekday: "Segunda",
    date: "13/04",
    status: "completed",
    punches: [
      { label: "Entrada", scheduled: "07:22", executed: "07:22", state: "executed" },
      { label: "Pausa almoço", scheduled: "11:30", executed: "11:30", state: "executed" },
      { label: "Retorno", scheduled: "12:30", executed: "12:30", state: "executed" },
      { label: "Saída", scheduled: "16:28", executed: "16:28", state: "executed" },
    ],
  },
  {
    weekday: "Terça",
    date: "14/04",
    status: "completed",
    punches: [
      { label: "Entrada", scheduled: "07:39", executed: "07:39", state: "executed" },
      { label: "Pausa almoço", scheduled: "11:34", executed: "11:34", state: "executed" },
      { label: "Retorno", scheduled: "13:36", executed: "13:45", state: "executed" },
      { label: "Saída", scheduled: "17:32", executed: "17:32", state: "executed" },
    ],
  },
  {
    weekday: "Quarta",
    date: "15/04",
    status: "completed",
    overtime: "00:37",
    punches: [
      { label: "Entrada", scheduled: "07:46", executed: "07:46", state: "executed" },
      { label: "Pausa almoço", scheduled: "11:35", executed: "11:35", state: "executed" },
      { label: "Retorno", scheduled: "12:35", executed: "12:35", state: "executed" },
      { label: "Saída", scheduled: "17:23", executed: "17:23", state: "executed" },
    ],
  },
  {
    weekday: "Quinta",
    date: "16/04",
    status: "completed",
    overtime: "00:54",
    punches: [
      { label: "Entrada", scheduled: "07:55", executed: "07:55", state: "executed" },
      { label: "Pausa almoço", scheduled: "11:39", executed: "11:39", state: "executed" },
      { label: "Retorno", scheduled: "12:30", executed: "12:30", state: "executed" },
      { label: "Saída", scheduled: "17:40", executed: "17:40", state: "executed" },
    ],
  },
  {
    weekday: "Sexta",
    date: "17/04",
    status: "today",
    punches: [
      { label: "Entrada", scheduled: "07:48", executed: "07:48", state: "executed" },
      { label: "Pausa almoço", scheduled: "11:32", state: "pending", editable: true, punchable: true },
      { label: "Retorno", scheduled: "12:32", state: "scheduled", editable: true, punchable: true },
      { label: "Saída", scheduled: "17:39", state: "scheduled", editable: true, punchable: true },
    ],
  },
];

const nextWeek: DayCardProps[] = [
  {
    weekday: "Segunda",
    date: "20/04",
    status: "future",
    punches: [
      { label: "Entrada", scheduled: "07:32", state: "scheduled", editable: true },
      { label: "Pausa almoço", scheduled: "11:33", state: "scheduled", editable: true },
      { label: "Retorno", scheduled: "12:38", state: "scheduled", editable: true },
      { label: "Saída", scheduled: "17:32", state: "scheduled", editable: true },
    ],
  },
  {
    weekday: "Terça",
    date: "21/04",
    status: "holiday",
    holidayName: "Tiradentes",
  },
  {
    weekday: "Quarta",
    date: "22/04",
    status: "future",
    punches: [
      { label: "Entrada", scheduled: "07:37", state: "scheduled", editable: true },
      { label: "Pausa almoço", scheduled: "11:38", state: "scheduled", editable: true },
      { label: "Retorno", scheduled: "12:34", state: "scheduled", editable: true },
      { label: "Saída", scheduled: "17:28", state: "scheduled", editable: true },
    ],
  },
  {
    weekday: "Quinta",
    date: "23/04",
    status: "future",
    punches: [
      { label: "Entrada", scheduled: "07:42", state: "scheduled", editable: true },
      { label: "Pausa almoço", scheduled: "11:39", state: "scheduled", editable: true },
      { label: "Retorno", scheduled: "12:35", state: "scheduled", editable: true },
      { label: "Saída", scheduled: "17:44", state: "scheduled", editable: true },
    ],
  },
  {
    weekday: "Sexta",
    date: "24/04",
    status: "future",
    punches: [
      { label: "Entrada", scheduled: "07:40", state: "scheduled", editable: true },
      { label: "Pausa almoço", scheduled: "11:33", state: "scheduled", editable: true },
      { label: "Retorno", scheduled: "12:34", state: "scheduled", editable: true },
      { label: "Saída", scheduled: "17:36", state: "scheduled", editable: true },
    ],
  },
];

function Dashboard() {
  return (
    <div className="min-h-screen">
      <Header />

      <main className="mx-auto max-w-[1600px] space-y-6 px-6 py-6">
        <ControlBar />
        <StatsBar />

        <WeekSection
          title="Semana atual"
          range="13/04 — 17/04"
          days={currentWeek}
          baseIndex={0}
        />

        <WeekSection
          title="Próxima semana"
          range="20/04 — 24/04"
          days={nextWeek}
          baseIndex={5}
        />

        <footer className="pt-4 text-center text-[11px] text-muted-foreground/60">
          PonTolentx · agendador rodando · última sincronização há 2 minutos
        </footer>
      </main>
    </div>
  );
}
