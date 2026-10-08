"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";

import {
  BarList,
  Card,
  DailyColumns,
  SentimentBar,
  StatTile,
} from "@/components/metrics/charts";
import { humanize } from "@/lib/format";
import { useMetrics } from "@/lib/queries";
import { cn } from "@/lib/utils";

const RANGES = [7, 30, 90];

const OUTCOME_LABEL: Record<string, string> = {
  sent_as_is: "Sent as drafted",
  edited: "Edited, then sent",
  discarded: "Discarded",
  pending: "Not used yet",
};

function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "–";
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

/** Report metrics (ARCHITECTURE §15). */
export default function MetricsPage() {
  const [days, setDays] = useState(7);
  const query = useMetrics(days);
  const m = query.data;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 p-8">
        <header className="flex flex-wrap items-end gap-4">
          <div className="flex-1">
            <h1 className="text-xl font-semibold">Metrics</h1>
            <p className="text-sm text-muted-foreground">
              Measured from the live data. Use these numbers in the report instead of estimates.
            </p>
          </div>
          <div role="radiogroup" aria-label="Period" className="flex rounded-md border bg-card p-0.5">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                role="radio"
                aria-checked={days === r}
                onClick={() => setDays(r)}
                className={cn(
                  "rounded px-3 py-1 text-xs",
                  days === r ? "bg-primary text-primary-foreground" : "hover:bg-muted",
                )}
              >
                {r} days
              </button>
            ))}
          </div>
        </header>

        {!m ? (
          <div className="flex h-60 items-center justify-center text-muted-foreground">
            {query.isError ? "Could not load metrics." : <Loader2 className="size-5 animate-spin" />}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-5" data-testid="kpis">
              <StatTile
                label="Conversations"
                value={m.conversations.toLocaleString("en-IN")}
                detail={`${Object.values(m.inbound_by_channel).reduce((a, b) => a + b, 0)} customer messages`}
              />
              <StatTile
                label="Median first response"
                value={duration(m.first_response.median_seconds)}
                detail={
                  m.first_response.count
                    ? `p90 ${duration(m.first_response.p90_seconds)} · ${m.first_response.count} answered`
                    : "No replies yet"
                }
              />
              <StatTile
                label="AI drafts used"
                value={draftUse(m.drafts)}
                detail={`${m.drafts.sent_as_is + m.drafts.edited} of ${m.drafts.sent_as_is + m.drafts.edited + m.drafts.discarded} decided`}
              />
              <StatTile
                label="Blocked by compliance"
                value={m.compliance.blocked_messages.toLocaleString("en-IN")}
                detail={`of ${m.compliance.checked_messages} outbound messages checked`}
              />
              <StatTile
                label="Needs review"
                value={m.needs_review.toLocaleString("en-IN")}
                detail="low-confidence or out-of-scope intents"
              />
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
              <Card title="Messages per day" subtitle="IST dates" className="lg:col-span-2">
                <DailyColumns days={m.daily} />
              </Card>
              <Card title="Customer sentiment" subtitle="Latest model result per inbound message">
                <SentimentBar mix={m.sentiment} />
                <div className="mt-5">
                  <p className="mb-2 text-xs font-medium">Messages by channel</p>
                  <BarList
                    rows={Object.entries(m.inbound_by_channel)
                      .sort(([, a], [, b]) => b - a)
                      .map(([k, v]) => ({
                        key: k,
                        label: { whatsapp: "WhatsApp", sms: "SMS", email: "Email" }[k] ?? k,
                        value: v,
                      }))}
                  />
                </div>
              </Card>
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
              <Card title="Conversations by queue">
                <BarList
                  rows={m.categories.map((c) => ({
                    key: c.category ?? "none",
                    label: c.queue,
                    value: c.count,
                  }))}
                />
              </Card>
              <Card title="AI draft outcomes">
                <BarList
                  rows={(["sent_as_is", "edited", "discarded", "pending"] as const).map((k) => ({
                    key: k,
                    label: OUTCOME_LABEL[k],
                    value: m.drafts[k],
                  }))}
                />
              </Card>
              <Card title="Compliance blocks by rule">
                <BarList
                  rows={m.compliance.blocks_by_rule.map((r) => ({
                    key: r.rule_id,
                    label: r.rule_id,
                    value: r.count,
                  }))}
                  empty="Nothing was blocked in this period."
                />
              </Card>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card title="Top intents" subtitle="Raw model labels; queues above group them">
                <BarList
                  rows={m.top_intents.map((i) => ({ key: i.label, label: humanize(i.label), value: i.count }))}
                />
              </Card>
              <Card title="AI model latency" subtitle="Inference time per message">
                {m.ai_latency.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No analysed messages yet.</p>
                ) : (
                  <table className="w-full text-xs" data-testid="latency-table">
                    <thead className="text-left text-muted-foreground">
                      <tr>
                        <th className="py-1 font-medium">Task</th>
                        <th className="py-1 font-medium">Model</th>
                        <th className="py-1 text-right font-medium">Messages</th>
                        <th className="py-1 text-right font-medium">Median</th>
                        <th className="py-1 text-right font-medium">p90</th>
                      </tr>
                    </thead>
                    <tbody className="tabular divide-y">
                      {m.ai_latency.map((l) => (
                        <tr key={`${l.task}-${l.model_name}`}>
                          <td className="py-1.5">{humanize(l.task)}</td>
                          <td className="max-w-48 truncate py-1.5" title={l.model_name}>
                            {l.model_name}
                          </td>
                          <td className="py-1.5 text-right">{l.count}</td>
                          <td className="py-1.5 text-right">{ms(l.median_ms)}</td>
                          <td className="py-1.5 text-right">{ms(l.p90_ms)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Card>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ms(value: number | null | undefined): string {
  return value == null ? "–" : `${Math.round(value)} ms`;
}

function draftUse(d: { sent_as_is: number; edited: number; discarded: number }): string {
  const decided = d.sent_as_is + d.edited + d.discarded;
  return decided ? `${Math.round(((d.sent_as_is + d.edited) / decided) * 100)}%` : "–";
}
