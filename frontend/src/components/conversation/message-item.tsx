import {
  AlertCircle,
  Bot,
  Check,
  CheckCheck,
  Clock,
  RotateCw,
  ShieldX,
} from "lucide-react";

import { ChannelIcon } from "@/components/badges";
import { AiChips } from "@/components/conversation/ai-chips";
import { Button } from "@/components/ui/button";
import type { DeliveryStatus, Message } from "@/lib/api/client";
import { CHANNEL_LABEL, DELIVERY_LABEL, formatTime, PROVIDER_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";

const DELIVERY_ICON: Record<DeliveryStatus, typeof Check> = {
  checking: Clock,
  queued: Clock,
  sent: Check,
  delivered: CheckCheck,
  blocked: ShieldX,
  failed: AlertCircle,
};

export function MessageItem({
  message: m,
  agentName,
  onRetry,
  retrying,
}: {
  message: Message;
  agentName?: string;
  onRetry: (id: number) => void;
  retrying: boolean;
}) {
  const inbound = m.direction === "inbound";
  const subject = typeof m.metadata.subject === "string" ? m.metadata.subject : null;
  const blocked = m.delivery_status === "blocked";
  const failedChecks = m.compliance_checks.filter((c) => !c.passed);

  return (
    <article
      data-testid="message"
      data-direction={m.direction}
      data-message-id={m.id}
      className={cn("flex max-w-[78%] flex-col gap-1.5", inbound ? "self-start" : "self-end items-end")}
    >
      <div
        className={cn(
          "rounded-2xl px-3.5 py-2.5 text-sm shadow-xs",
          inbound && "rounded-tl-sm border bg-card",
          !inbound && !blocked && "rounded-tr-sm bg-primary text-primary-foreground",
          blocked && "rounded-tr-sm border border-dashed border-destructive/50 bg-destructive/5",
          m.is_template && !blocked && "bg-secondary text-secondary-foreground",
        )}
      >
        {subject && (
          <p className={cn("mb-1 text-xs font-semibold", inbound ? "text-foreground" : "opacity-90")}>
            {subject}
          </p>
        )}
        <p className="break-words whitespace-pre-wrap">{m.body}</p>
      </div>

      <div className="flex items-center gap-1.5 px-1 text-[11px] text-muted-foreground">
        {m.sender_type === "system" && (
          <>
            <Bot className="size-3" aria-hidden />
            <span>{m.is_template ? "Automatic acknowledgement" : "System"} ·</span>
          </>
        )}
        {!inbound && m.sender_type === "agent" && agentName && <span>{agentName} ·</span>}
        <ChannelIcon channel={m.channel} className="size-3" />
        <span>{CHANNEL_LABEL[m.channel]}</span>
        <span
          data-testid="provider"
          className={cn(
            "rounded px-1 text-[10px]",
            m.provider === "simulator" ? "bg-muted" : "bg-ok/12 font-medium text-ok",
          )}
          title={
            m.provider === "simulator"
              ? "Sent through the customer simulator"
              : "Sent through a real provider"
          }
        >
          {PROVIDER_LABEL[m.provider]}
        </span>
        <span>·</span>
        <time dateTime={m.created_at} className="tabular">
          {formatTime(m.created_at)}
        </time>
        {m.delivery_status && <DeliveryState status={m.delivery_status} />}
      </div>

      {inbound && <AiChips ai={m.ai} />}

      {blocked && failedChecks.length > 0 && (
        <ul
          data-testid="compliance-reasons"
          className="space-y-0.5 rounded-md bg-destructive/8 px-2.5 py-1.5 text-xs text-destructive"
        >
          {failedChecks.map((c) => (
            <li key={c.rule_id}>{c.reason ?? c.rule_id}</li>
          ))}
        </ul>
      )}

      {m.delivery_status === "failed" && (
        <div className="flex items-center gap-2 text-xs text-destructive">
          {m.delivery_error && <span className="max-w-72 truncate">{m.delivery_error}</span>}
          <Button size="xs" variant="outline" onClick={() => onRetry(m.id)} disabled={retrying}>
            <RotateCw className={cn(retrying && "animate-spin")} />
            Retry
          </Button>
        </div>
      )}
    </article>
  );
}

function DeliveryState({ status }: { status: DeliveryStatus }) {
  const Icon = DELIVERY_ICON[status];
  return (
    <span
      data-testid="delivery-status"
      data-status={status}
      className={cn(
        "inline-flex items-center gap-0.5",
        status === "delivered" && "text-ok",
        (status === "blocked" || status === "failed") && "font-medium text-destructive",
      )}
    >
      <span>·</span>
      <Icon className="size-3" />
      {DELIVERY_LABEL[status]}
    </span>
  );
}
