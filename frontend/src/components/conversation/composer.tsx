"use client";

import {
  AlertTriangle,
  Loader2,
  MessageSquarePlus,
  RotateCw,
  SendHorizontal,
  Sparkles,
  X,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ChannelIcon } from "@/components/badges";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, type Channel, type Draft } from "@/lib/api/client";
import { CHANNEL_LABEL } from "@/lib/format";
import { useGenerateDraft, useSendReply } from "@/lib/queries";
import { cn } from "@/lib/utils";

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
  const [draft, setDraft] = useState<Draft | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const [showInstructions, setShowInstructions] = useState(false);
  const [instructions, setInstructions] = useState("");
  const send = useSendReply(conversationId);
  const generate = useGenerateDraft(conversationId);

  const channel = chosen ?? defaultChannel;
  const canSend = body.trim().length > 0 && !send.isPending;
  const edited = draft != null && draft.body.trim() !== body.trim();

  function requestDraft() {
    setAiError(null);
    generate.mutate(
      { channel, instructions: instructions.trim() || undefined },
      {
        onSuccess: (result) => {
          setDraft(result);
          setBody(result.body);
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 503) {
            setAiError(error.message);
          } else {
            toast.error("Could not generate a draft", { description: error.message });
          }
        },
      },
    );
  }

  function discardDraft() {
    setDraft(null);
    setBody("");
  }

  function submit() {
    if (!canSend) return;
    send.mutate(
      { channel, body, idempotencyKey, draftId: draft?.id },
      {
        onSuccess: (result) => {
          setBody("");
          setDraft(null);
          setInstructions("");
          setShowInstructions(false);
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
      className="space-y-2 border-t bg-card p-3"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {aiError && (
        <div
          role="alert"
          data-testid="ai-unavailable"
          className="flex items-start gap-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-[oklch(0.42_0.1_70)]"
        >
          <AlertTriangle className="mt-px size-3.5 shrink-0" />
          <p className="flex-1">
            <span className="font-semibold">AI unavailable.</span> {aiError} You can still type
            and send a reply.
          </p>
          <button type="button" aria-label="Dismiss" onClick={() => setAiError(null)}>
            <X className="size-3.5" />
          </button>
        </div>
      )}

      {draft && (
        <section
          aria-label="AI draft"
          data-testid="draft-panel"
          className="rounded-md border border-ai/25 bg-ai/5 px-3 py-2 text-xs"
        >
          <div className="flex items-center gap-2">
            <Sparkles className="size-3.5 text-ai" />
            <span className="font-semibold text-ai">AI draft</span>
            <span className="text-muted-foreground">
              {edited ? "edited by you" : "not edited"} · review before sending
            </span>
            <div className="ml-auto flex gap-1">
              <Button
                type="button"
                size="xs"
                variant="ghost"
                onClick={requestDraft}
                disabled={generate.isPending}
              >
                <RotateCw className={cn(generate.isPending && "animate-spin")} />
                Regenerate
              </Button>
              <Button type="button" size="xs" variant="ghost" onClick={discardDraft}>
                <X />
                Discard
              </Button>
            </div>
          </div>
          {draft.verify_hints.length > 0 && (
            <div className="mt-1.5">
              <p className="font-medium">Check before sending:</p>
              <ul className="mt-0.5 list-disc space-y-0.5 pl-4" data-testid="verify-hints">
                {draft.verify_hints.map((hint) => (
                  <li key={hint}>{hint}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

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
          placeholder={
            generate.isPending ? "Drafting a reply…" : `Reply on ${CHANNEL_LABEL[channel]}…`
          }
          aria-label="Reply"
          rows={draft ? 5 : 3}
          disabled={generate.isPending}
          className="min-h-20 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
        />
        {showInstructions && (
          <div className="border-t px-2 py-1.5">
            <Input
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              maxLength={1000}
              aria-label="Instructions for the AI"
              placeholder="Optional instructions for the AI, e.g. apologise and ask for the transaction date"
              className="h-7 border-0 bg-transparent text-xs shadow-none focus-visible:ring-0"
            />
          </div>
        )}
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
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 border-ai/30 text-xs text-ai hover:bg-ai/10 hover:text-ai"
            onClick={requestDraft}
            disabled={generate.isPending}
          >
            {generate.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />}
            {generate.isPending ? "Drafting…" : draft ? "New draft" : "Draft reply"}
          </Button>
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            aria-label="Instructions for the AI"
            aria-pressed={showInstructions}
            onClick={() => setShowInstructions((v) => !v)}
          >
            <MessageSquarePlus className="size-3.5" />
          </Button>
          <span className="hidden text-[11px] text-muted-foreground lg:inline">
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
