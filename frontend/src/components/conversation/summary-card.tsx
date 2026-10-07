"use client";

import { AlertTriangle, FileText, Loader2, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ApiError, type ConversationDetail } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";
import { useSummarize } from "@/lib/queries";

/**
 * Conversation summary (ARCHITECTURE §6.5) with the three AI states: summarizing
 * (job pending or running), ok (latest summary, with staleness), unavailable (no LLM or
 * the last job failed; the previous summary stays visible).
 */
export function SummaryCard({ detail }: { detail: ConversationDetail }) {
  const { latest_summary: summary, summary_job: job, messages } = detail;
  const summarize = useSummarize(detail.conversation.id);
  const [unavailable, setUnavailable] = useState<string | null>(null);

  const active = job != null && (job.status === "pending" || job.status === "running");
  const failed =
    job?.status === "failed" &&
    (summary == null || new Date(job.updated_at) > new Date(summary.created_at));
  const newSince = summary
    ? messages.filter(
        (m) =>
          m.id > summary.covers_until_message_id &&
          m.sender_type !== "system" &&
          m.delivery_status !== "blocked",
      ).length
    : 0;
  const busy = active || summarize.isPending;

  function run() {
    setUnavailable(null);
    summarize.mutate(undefined, {
      onError: (error) => {
        if (error instanceof ApiError && error.status === 503) setUnavailable(error.message);
        else toast.error("Could not request a summary", { description: error.message });
      },
    });
  }

  return (
    <div className="space-y-3 text-sm" data-testid="summary">
      {busy ? (
        <p className="flex items-center gap-2 text-ai" data-testid="summary-pending">
          <Loader2 className="size-4 animate-spin" />
          Summarizing the conversation…
        </p>
      ) : null}

      {(unavailable || failed) && (
        <p
          role="alert"
          data-testid="summary-unavailable"
          className="flex items-start gap-2 rounded-md bg-warn/10 px-2.5 py-2 text-xs text-[oklch(0.42_0.1_70)]"
        >
          <AlertTriangle className="mt-px size-3.5 shrink-0" />
          <span>
            <span className="font-semibold">AI unavailable.</span>{" "}
            {unavailable ??
              "The summary could not be generated." + (summary ? " Showing the last one." : "")}
          </span>
        </p>
      )}

      {summary ? (
        <div className="space-y-2.5">
          <p className="leading-relaxed" data-testid="summary-body">
            {summary.body}
          </p>
          <KeyPoints points={summary.key_points} />
          <p className="text-[11px] text-muted-foreground">
            <Sparkles className="mr-1 inline size-3 text-ai" />
            AI summary · {formatDateTime(summary.created_at)}
            {newSince > 0 && (
              <span className="font-medium text-[oklch(0.48_0.11_70)]" data-testid="summary-stale">
                {" "}
                · {newSince} new message{newSince === 1 ? "" : "s"} since this summary
              </span>
            )}
          </p>
        </div>
      ) : (
        !busy && (
          <p className="flex items-start gap-2 text-muted-foreground">
            <FileText className="mt-0.5 size-4 shrink-0" />
            No summary yet.
          </p>
        )
      )}

      <Button size="sm" variant="outline" className="w-full" onClick={run} disabled={busy}>
        <Sparkles className="text-ai" />
        {summary ? "Update summary" : "Summarize"}
      </Button>
    </div>
  );
}

function KeyPoints({ points }: { points: Record<string, unknown> }) {
  const issue = typeof points.customer_issue === "string" ? points.customer_issue : null;
  const mood = typeof points.customer_mood === "string" ? points.customer_mood : null;
  const open = Array.isArray(points.open_items) ? (points.open_items as string[]) : [];
  const done = Array.isArray(points.actions_taken) ? (points.actions_taken as string[]) : [];
  return (
    <dl className="space-y-1.5 text-xs">
      {issue && <Point label="Issue">{issue}</Point>}
      {done.length > 0 && (
        <Point label="Done">
          <ul className="list-disc pl-4">
            {done.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </Point>
      )}
      {open.length > 0 && (
        <Point label="Open">
          <ul className="list-disc pl-4">
            {open.map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
        </Point>
      )}
      {mood && <Point label="Mood">{mood}</Point>}
    </dl>
  );
}

function Point({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[3.5rem_1fr] gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
