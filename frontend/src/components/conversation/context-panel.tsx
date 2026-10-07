"use client";

import { BadgeCheck, ExternalLink, Mail, Phone } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { Avatar, PriorityBadge, StatusBadge } from "@/components/badges";
import { IntentChip, SentimentChip } from "@/components/conversation/ai-chips";
import { SummaryCard } from "@/components/conversation/summary-card";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AiResult, ConversationDetail, ConversationStatus, Message } from "@/lib/api/client";
import { formatDateTime, humanize, percent } from "@/lib/format";
import { useAgents, usePatchConversation } from "@/lib/queries";

const UNASSIGNED = "unassigned";

/** Agent-driven transitions, mirroring ARCHITECTURE §5.3. */
const ACTIONS: Record<ConversationStatus, { to: ConversationStatus; label: string }[]> = {
  open: [
    { to: "pending", label: "Mark pending" },
    { to: "resolved", label: "Resolve" },
  ],
  pending: [
    { to: "open", label: "Reopen" },
    { to: "resolved", label: "Resolve" },
  ],
  resolved: [{ to: "closed", label: "Close" }],
  closed: [],
};

export function ContextPanel({ detail }: { detail: ConversationDetail }) {
  const { conversation: c, customer } = detail;
  const agents = useAgents();
  const patch = usePatchConversation(c.id);
  const latestInbound = [...detail.messages].reverse().find((m) => m.direction === "inbound");

  function update(body: Parameters<typeof patch.mutate>[0]) {
    patch.mutate(body, {
      onError: (e) => toast.error("Update failed", { description: e.message }),
    });
  }

  return (
    <aside
      aria-label="Conversation details"
      className="hidden w-80 shrink-0 flex-col gap-0 overflow-y-auto border-l bg-card xl:flex"
    >
      <Section title="Customer">
        <div className="flex items-start gap-3">
          <Avatar name={customer.display_name} />
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1.5 font-medium">
              <span className="truncate">{customer.display_name}</span>
              {customer.verified && <BadgeCheck className="size-4 shrink-0 text-primary" />}
            </p>
            <p className="text-xs text-muted-foreground">
              {customer.verified ? "Verified customer" : "Unverified sender"}
            </p>
          </div>
        </div>
        <ul className="mt-3 space-y-1.5 text-sm">
          {customer.contacts.map((contact) => (
            <li key={contact.id} className="flex items-center gap-2 text-muted-foreground">
              {contact.kind === "phone" ? <Phone className="size-3.5" /> : <Mail className="size-3.5" />}
              <span className="tabular truncate text-foreground">{contact.value_normalized}</span>
            </li>
          ))}
        </ul>
        {!customer.verified && (
          <p className="mt-3 rounded-md bg-warn/10 px-2.5 py-2 text-xs text-[oklch(0.45_0.1_70)]">
            Not matched to a known customer. If this is an existing customer, link them from the
            customer page.
          </p>
        )}
        <Button asChild variant="outline" size="sm" className="mt-3 w-full">
          <Link href={`/customers/${customer.id}`}>
            Customer profile <ExternalLink />
          </Link>
        </Button>
      </Section>

      <Section title="Summary">
        <SummaryCard detail={detail} />
      </Section>

      <Section title="Conversation">
        <dl className="grid grid-cols-[6.5rem_1fr] gap-x-2 gap-y-2 text-sm">
          <dt className="text-muted-foreground">Status</dt>
          <dd>
            <StatusBadge status={c.status} />
          </dd>
          <dt className="text-muted-foreground">Priority</dt>
          <dd>
            <PriorityBadge priority={c.priority} />
          </dd>
          <dt className="text-muted-foreground">Queue</dt>
          <dd>{c.category_queue ?? <span className="text-muted-foreground">None yet</span>}</dd>
          <dt className="text-muted-foreground">Primary intent</dt>
          <dd>
            {c.primary_intent ? (
              <>
                {humanize(c.primary_intent)}{" "}
                <span className="tabular text-xs text-muted-foreground">
                  {percent(c.primary_intent_confidence)}
                </span>
              </>
            ) : (
              <span className="text-muted-foreground">None yet</span>
            )}
          </dd>
          <dt className="text-muted-foreground">Opened</dt>
          <dd className="tabular">{formatDateTime(c.created_at)}</dd>
          <dt className="text-muted-foreground">First reply</dt>
          <dd className="tabular">
            {c.first_response_at ? (
              formatDateTime(c.first_response_at)
            ) : (
              <span className="text-muted-foreground">Not yet</span>
            )}
          </dd>
        </dl>

        <div className="mt-4 space-y-1.5">
          <label className="text-xs text-muted-foreground" htmlFor="assignee">
            Assignee
          </label>
          <Select
            value={c.assignee_id == null ? UNASSIGNED : String(c.assignee_id)}
            onValueChange={(v) => update({ assignee_id: v === UNASSIGNED ? null : Number(v) })}
          >
            <SelectTrigger id="assignee" size="sm" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={UNASSIGNED}>Unassigned</SelectItem>
              {agents.data?.map((a) => (
                <SelectItem key={a.id} value={String(a.id)}>
                  {a.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {ACTIONS[c.status].length > 0 && (
          <div className="mt-3 flex gap-2">
            {ACTIONS[c.status].map((action) => (
              <Button
                key={action.to}
                size="sm"
                variant={action.to === "resolved" ? "default" : "outline"}
                className="flex-1"
                disabled={patch.isPending}
                onClick={() => update({ status: action.to })}
              >
                {action.label}
              </Button>
            ))}
          </div>
        )}
      </Section>

      <Section title="AI analysis">
        <LatestAnalysis message={latestInbound} />
      </Section>

    </aside>
  );
}

function LatestAnalysis({ message }: { message: Message | undefined }) {
  if (!message) {
    return <p className="text-sm text-muted-foreground">No customer messages yet.</p>;
  }
  const intent = message.ai.intent;
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted-foreground">Latest customer message</p>
      <div className="flex flex-wrap gap-1.5">
        <IntentChip result={intent} />
        <SentimentChip result={message.ai.sentiment} />
      </div>
      {intent?.status === "ok" && intent.top_k && (
        <ul className="space-y-1.5" aria-label="Top intents">
          {intent.top_k.map((s) => (
            <li key={s.label} className="space-y-0.5">
              <div className="flex justify-between gap-2 text-xs">
                <span className="truncate">{humanize(s.label)}</span>
                <span className="tabular text-muted-foreground">{percent(s.confidence)}</span>
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-ai/70"
                  style={{ width: `${Math.round(s.confidence * 100)}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
      <ModelInfo results={[intent, message.ai.sentiment]} />
    </div>
  );
}

function ModelInfo({ results }: { results: (AiResult | null | undefined)[] }) {
  const present = results.filter((r): r is AiResult => !!r);
  if (present.length === 0) return null;
  return (
    <ul className="space-y-0.5 border-t pt-2 text-[10px] text-muted-foreground" data-testid="model-info">
      {present.map((r) => (
        <li key={r.task} className="tabular flex justify-between gap-2">
          <span className="truncate" title={r.model_name}>
            {r.model_name}
          </span>
          <span className="shrink-0">
            {r.model_version}
            {r.latency_ms != null && ` · ${r.latency_ms} ms`}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b p-4">
      <h2 className="mb-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {title}
      </h2>
      {children}
    </section>
  );
}
