"use client";

import { BadgeCheck, Loader2 } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef } from "react";
import { toast } from "sonner";

import { CategoryBadge, PriorityBadge, StatusBadge } from "@/components/badges";
import { Composer } from "@/components/conversation/composer";
import { ContextPanel } from "@/components/conversation/context-panel";
import { MessageItem } from "@/components/conversation/message-item";
import { ApiError, type Channel, type ConversationDetail } from "@/lib/api/client";
import { dayKey, formatDay } from "@/lib/format";
import { useAgents, useConversation, useRetryDelivery } from "@/lib/queries";

export function ConversationView({ id }: { id: number }) {
  const query = useConversation(id);

  if (query.isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="size-5 animate-spin" aria-label="Loading conversation" />
      </div>
    );
  }
  if (query.isError || !query.data) {
    const notFound = query.error instanceof ApiError && query.error.status === 404;
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {notFound ? "This conversation does not exist." : "Could not load the conversation."}
      </div>
    );
  }
  return <Loaded detail={query.data} />;
}

function channelsFor(detail: ConversationDetail): Channel[] {
  const kinds = new Set(detail.customer.contacts.map((c) => c.kind));
  const channels: Channel[] = [];
  if (kinds.has("phone")) channels.push("whatsapp", "sms");
  if (kinds.has("email")) channels.push("email");
  return channels;
}

function Loaded({ detail }: { detail: ConversationDetail }) {
  const { conversation: c, customer, messages } = detail;
  const agents = useAgents();
  const retry = useRetryDelivery(c.id);
  const bottomRef = useRef<HTMLDivElement>(null);

  const agentNames = useMemo(
    () => new Map(agents.data?.map((a) => [a.id, a.name]) ?? []),
    [agents.data],
  );
  const lastInbound = [...messages].reverse().find((m) => m.direction === "inbound");
  const defaultChannel: Channel = lastInbound?.channel ?? messages.at(-1)?.channel ?? "whatsapp";
  const channels = channelsFor(detail);
  if (!channels.includes(defaultChannel)) channels.unshift(defaultChannel);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, c.id]);

  return (
    <div className="flex h-full">
      <section aria-label="Conversation" className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b bg-card px-5 py-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-1.5 font-semibold">
              <span className="truncate">{customer.display_name}</span>
              {customer.verified && <BadgeCheck className="size-4 shrink-0 text-primary" />}
            </h2>
            <p className="tabular text-xs text-muted-foreground">Conversation #{c.id}</p>
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            <CategoryBadge queue={c.category_queue} />
            <PriorityBadge priority={c.priority} />
            <StatusBadge status={c.status} />
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto bg-background px-5 py-4">
          <div className="mx-auto flex max-w-3xl flex-col gap-4" data-testid="thread">
            {messages.map((m, i) => {
              const newDay = i === 0 || dayKey(messages[i - 1].created_at) !== dayKey(m.created_at);
              return (
                <Fragment key={m.id}>
                  {newDay && (
                    <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                      <span className="h-px flex-1 bg-border" />
                      {formatDay(m.created_at)}
                      <span className="h-px flex-1 bg-border" />
                    </div>
                  )}
                  <MessageItem
                    message={m}
                    agentName={m.agent_id != null ? agentNames.get(m.agent_id) : undefined}
                    retrying={retry.isPending && retry.variables === m.id}
                    onRetry={(messageId) =>
                      retry.mutate(messageId, {
                        onError: (e) => toast.error("Retry failed", { description: e.message }),
                      })
                    }
                  />
                </Fragment>
              );
            })}
            <div ref={bottomRef} />
          </div>
        </div>

        <Composer
          key={c.id}
          conversationId={c.id}
          channels={channels}
          defaultChannel={defaultChannel}
        />
      </section>
      <ContextPanel detail={detail} />
    </div>
  );
}
