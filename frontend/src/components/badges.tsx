import { Mail, MessageCircle, MessageSquareText } from "lucide-react";

import type { Channel, ConversationStatus, Priority } from "@/lib/api/client";
import { CHANNEL_LABEL, initials, PRIORITY_LABEL, STATUS_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";

const CHANNEL_ICON = { whatsapp: MessageCircle, sms: MessageSquareText, email: Mail };
const CHANNEL_COLOR = { whatsapp: "text-whatsapp", sms: "text-sms", email: "text-email" };

export function ChannelIcon({ channel, className }: { channel: Channel; className?: string }) {
  const Icon = CHANNEL_ICON[channel];
  return (
    <Icon
      aria-label={CHANNEL_LABEL[channel]}
      className={cn("size-3.5 shrink-0", CHANNEL_COLOR[channel], className)}
    />
  );
}

export function ChannelTag({ channel }: { channel: Channel }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <ChannelIcon channel={channel} />
      {CHANNEL_LABEL[channel]}
    </span>
  );
}

export const PRIORITY_STRIPE: Record<Priority, string> = {
  urgent: "bg-urgent",
  high: "bg-high",
  normal: "bg-normal/50",
  low: "bg-transparent",
};

const PRIORITY_DOT: Record<Priority, string> = {
  urgent: "bg-urgent",
  high: "bg-high",
  normal: "bg-normal",
  low: "bg-low",
};

export function PriorityBadge({ priority }: { priority: Priority }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
        priority === "urgent" && "bg-urgent/10 text-urgent",
        priority === "high" && "bg-high/15 text-[oklch(0.5_0.13_62)]",
        priority === "normal" && "bg-muted text-muted-foreground",
        priority === "low" && "bg-muted text-muted-foreground/80",
      )}
    >
      <span className={cn("size-1.5 rounded-full", PRIORITY_DOT[priority])} />
      {PRIORITY_LABEL[priority]}
    </span>
  );
}

export function StatusBadge({ status }: { status: ConversationStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        status === "open" && "border-primary/30 text-primary",
        status === "pending" && "border-warn/40 text-[oklch(0.5_0.12_70)]",
        status === "resolved" && "border-ok/40 text-ok",
        status === "closed" && "border-border text-muted-foreground",
      )}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

export function CategoryBadge({ queue }: { queue: string | null | undefined }) {
  if (!queue) {
    return <span className="text-[11px] text-muted-foreground italic">Uncategorised</span>;
  }
  return (
    <span className="inline-flex items-center rounded-md bg-secondary px-1.5 py-0.5 text-[11px] font-medium text-secondary-foreground">
      {queue}
    </span>
  );
}

export function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-accent-foreground",
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}
