"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Small chart pieces for the metrics page, built per the dataviz method: forms chosen by
 * the data's job, palette validated with validate_palette.js (light mode; the app has no
 * dark theme), bars <= 24px thick with 4px rounded data ends, 2px surface gaps, text in
 * text tokens (never series colours), hover tooltips and a table fallback.
 */

export const SERIES = {
  inbound: "#2a78d6", // categorical slot 1 (blue)
  outbound: "#eb6834", // categorical slot 2 (orange)
};
export const MAGNITUDE = "#2a78d6"; // sequential single hue
export const DIVERGING = { negative: "#e34948", neutral: "#d9d7d1", positive: "#2a78d6" };

export function StatTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-4" data-testid="stat-tile">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="tabular mt-1 text-2xl font-semibold tracking-tight">{value}</p>
      {detail && <p className="mt-0.5 text-xs text-muted-foreground">{detail}</p>}
    </div>
  );
}

export function Card({
  title,
  subtitle,
  children,
  className,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-lg border bg-card p-4", className)}>
      <h2 className="text-sm font-semibold">{title}</h2>
      {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** Ranked magnitudes: one hue, value printed beside each bar. */
export function BarList({
  rows,
  format = (n) => n.toLocaleString("en-IN"),
  empty = "No data in this period.",
}: {
  rows: { key: string; label: string; value: number; hint?: string }[];
  format?: (n: number) => string;
  empty?: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.key} className="group text-xs" title={r.hint ?? `${r.label}: ${format(r.value)}`}>
          <div className="mb-1 flex justify-between gap-3">
            <span className="truncate">{r.label}</span>
            <span className="tabular font-medium">{format(r.value)}</span>
          </div>
          <div className="h-3.5 w-full">
            <div
              className="h-full rounded-r-[4px] transition-opacity group-hover:opacity-80"
              style={{
                width: `${Math.max((r.value / max) * 100, r.value > 0 ? 1.5 : 0)}%`,
                background: MAGNITUDE,
              }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Clean axis ticks: the smallest 1/2/2.5/5 × 10^k step that covers `value` in at most
 * five intervals (215 → 0, 50, …, 250). */
function niceTicks(value: number): number[] {
  const max = Math.max(value, 1);
  const magnitude = 10 ** Math.floor(Math.log10(max / 5));
  const step =
    [1, 2, 2.5, 5, 10].map((s) => s * magnitude).find((s) => Math.ceil(max / s) <= 5) ??
    10 * magnitude;
  const count = Math.max(1, Math.ceil(max / step));
  return Array.from({ length: count + 1 }, (_, i) => Math.round(i * step * 100) / 100);
}

/** Inbound vs outbound per day: two-series columns with a per-day hover tooltip. */
export function DailyColumns({
  days,
}: {
  days: { date: string; inbound: number; outbound: number }[];
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const ticks = niceTicks(Math.max(0, ...days.flatMap((d) => [d.inbound, d.outbound])));
  const top = ticks[ticks.length - 1];
  const label = (iso: string) =>
    new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

  if (days.length === 0) return <p className="text-sm text-muted-foreground">No messages in this period.</p>;

  return (
    <div>
      <div className="mb-3 flex items-center gap-4 text-xs">
        <Legend color={SERIES.inbound} label="Inbound (customers)" />
        <Legend color={SERIES.outbound} label="Outbound (agents and acknowledgements)" />
        <button
          type="button"
          className="ml-auto text-muted-foreground underline-offset-2 hover:underline"
          onClick={() => setAsTable((v) => !v)}
        >
          {asTable ? "Show chart" : "Show table"}
        </button>
      </div>
      {asTable ? (
        <table className="w-full text-xs" data-testid="daily-table">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 font-medium">Day (IST)</th>
              <th className="py-1 text-right font-medium">Inbound</th>
              <th className="py-1 text-right font-medium">Outbound</th>
            </tr>
          </thead>
          <tbody className="tabular divide-y">
            {days.map((d) => (
              <tr key={d.date}>
                <td className="py-1">{label(d.date)}</td>
                <td className="py-1 text-right">{d.inbound}</td>
                <td className="py-1 text-right">{d.outbound}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="flex gap-2">
          <div className="tabular flex h-40 flex-col-reverse justify-between text-right text-[10px] text-muted-foreground">
            {ticks.map((t) => (
              <span key={t} className="leading-none">
                {t.toLocaleString("en-IN")}
              </span>
            ))}
          </div>
          <div className="relative flex-1">
            <div className="pointer-events-none absolute inset-x-0 top-0 flex h-40 flex-col justify-between">
              {ticks.map((t) => (
                <span key={t} className="border-t border-border/60" />
              ))}
            </div>
            <div className="relative flex h-40 items-end justify-around gap-1" role="img" aria-label="Messages per day">
              {days.map((d, i) => (
                <div
                  key={d.date}
                  className={cn(
                    "relative flex h-full flex-1 items-end justify-center gap-[2px] rounded-sm",
                    hover === i && "bg-muted/60",
                  )}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                >
                  {(["inbound", "outbound"] as const).map((series) => (
                    <div
                      key={series}
                      className="w-full max-w-6 rounded-t-[4px]"
                      style={{ height: `${(d[series] / top) * 100}%`, background: SERIES[series] }}
                    />
                  ))}
                  {hover === i && (
                    <div className="absolute bottom-full z-10 mb-1 rounded-md border bg-popover px-2 py-1.5 text-[11px] whitespace-nowrap shadow-md">
                      <p className="font-medium">{label(d.date)}</p>
                      <p className="tabular">
                        <Swatch color={SERIES.inbound} /> {d.inbound} inbound
                      </p>
                      <p className="tabular">
                        <Swatch color={SERIES.outbound} /> {d.outbound} outbound
                      </p>
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="mt-1 flex justify-around gap-1 text-[10px] text-muted-foreground">
              {days.map((d) => (
                <span key={d.date} className="flex-1 text-center">
                  {label(d.date)}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** Ordered sentiment share: diverging stacked bar centred on neutral. */
export function SentimentBar({
  mix,
}: {
  mix: { negative: number; neutral: number; positive: number };
}) {
  const total = mix.negative + mix.neutral + mix.positive;
  if (total === 0) return <p className="text-sm text-muted-foreground">No analysed messages yet.</p>;
  const parts = [
    { key: "negative", label: "Negative", value: mix.negative, color: DIVERGING.negative },
    { key: "neutral", label: "Neutral", value: mix.neutral, color: DIVERGING.neutral },
    { key: "positive", label: "Positive", value: mix.positive, color: DIVERGING.positive },
  ];
  const pct = (n: number) => `${Math.round((n / total) * 100)}%`;
  return (
    <div>
      <div className="flex h-5 w-full gap-[2px] overflow-hidden rounded-[4px]" role="img" aria-label="Sentiment mix">
        {parts
          .filter((p) => p.value > 0)
          .map((p) => (
            <div
              key={p.key}
              title={`${p.label}: ${p.value} (${pct(p.value)})`}
              className="h-full transition-opacity hover:opacity-80"
              style={{ width: `${(p.value / total) * 100}%`, background: p.color }}
            />
          ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {parts.map((p) => (
          <span key={p.key} className="tabular inline-flex items-center gap-1.5">
            <Swatch color={p.color} />
            {p.label} {p.value} <span className="text-muted-foreground">({pct(p.value)})</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function Swatch({ color }: { color: string }) {
  return <span className="inline-block size-2.5 rounded-[2px] align-middle" style={{ background: color }} />;
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <Swatch color={color} />
      {label}
    </span>
  );
}
