"use client";

import { Loader2, SendHorizontal } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ChannelIcon } from "@/components/badges";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { Channel } from "@/lib/api/client";
import { CHANNEL_LABEL } from "@/lib/format";
import { useSendReply } from "@/lib/queries";

function newKey(): string {
  return crypto.randomUUID();
}

export function Composer({
  conversationId,
  channels,
  defaultChannel,
}: {
  conversationId: number;
  channels: Channel[];
  /** The channel of the customer's latest inbound message. */
  defaultChannel: Channel;
}) {
  const [chosen, setChosen] = useState<Channel | null>(null);
  const [body, setBody] = useState("");
  // One key per compose action, not per click: a retried request after a network error
  // reuses it, so the server stores the reply once (ARCHITECTURE §6.3).
  const [idempotencyKey, setIdempotencyKey] = useState(newKey);
  const send = useSendReply(conversationId);

  const channel = chosen ?? defaultChannel;
  const canSend = body.trim().length > 0 && !send.isPending;

  function submit() {
    if (!canSend) return;
    send.mutate(
      { channel, body, idempotencyKey },
      {
        onSuccess: (result) => {
          setBody("");
          setIdempotencyKey(newKey());
          if (!result.compliance.allowed) {
            toast.warning("Reply blocked by compliance", {
              description: result.compliance.results
                .filter((r) => !r.passed)
                .map((r) => r.reason ?? r.rule_id)
                .join(" "),
            });
          }
        },
        onError: (error) => toast.error("Reply not sent", { description: error.message }),
      },
    );
  }

  return (
    <form
      className="border-t bg-card p-3"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="rounded-lg border bg-background focus-within:ring-2 focus-within:ring-ring/30">
        <Textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={`Reply on ${CHANNEL_LABEL[channel]}…`}
          aria-label="Reply"
          rows={3}
          className="min-h-20 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
        />
        <div className="flex items-center gap-2 border-t px-2 py-1.5">
          <Select value={channel} onValueChange={(v) => setChosen(v as Channel)}>
            <SelectTrigger size="sm" aria-label="Channel" className="h-7 w-36 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {channels.map((c) => (
                <SelectItem key={c} value={c}>
                  <ChannelIcon channel={c} />
                  {CHANNEL_LABEL[c]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="hidden text-[11px] text-muted-foreground sm:inline">
            Ctrl + Enter to send · checked for compliance before delivery
          </span>
          <Button type="submit" size="sm" className="ml-auto" disabled={!canSend}>
            {send.isPending ? <Loader2 className="animate-spin" /> : <SendHorizontal />}
            Send
          </Button>
        </div>
      </div>
    </form>
  );
}
