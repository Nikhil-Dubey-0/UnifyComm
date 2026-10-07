"use client";

import { CheckCircle2, Loader2, Megaphone, ShieldX } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { ChannelIcon } from "@/components/badges";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { Channel, SendResponse } from "@/lib/api/client";
import { CHANNEL_LABEL } from "@/lib/format";
import { useOutreach } from "@/lib/queries";

/** Proactive message from the customer page (ARCHITECTURE §7.6.1: always `proactive`). */
export function OutreachDialog({
  customerId,
  customerName,
  channels,
}: {
  customerId: number;
  customerName: string;
  channels: Channel[];
}) {
  const [open, setOpen] = useState(false);
  const [channel, setChannel] = useState<Channel>(channels[0] ?? "sms");
  const [body, setBody] = useState("");
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [result, setResult] = useState<SendResponse | null>(null);
  const outreach = useOutreach(customerId);

  function reset(nextOpen: boolean) {
    setOpen(nextOpen);
    if (nextOpen) {
      setBody("");
      setResult(null);
      setKey(crypto.randomUUID());
    }
  }

  function send() {
    outreach.mutate(
      { channel, body, idempotencyKey: key },
      {
        onSuccess: (r) => {
          setResult(r);
          if (r.compliance.allowed) toast.success(`Message to ${customerName} queued for delivery`);
        },
        onError: (e) => toast.error("Message not sent", { description: e.message }),
      },
    );
  }

  const failed = result?.compliance.results.filter((c) => !c.passed) ?? [];

  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogTrigger asChild>
        <Button variant="outline" disabled={channels.length === 0}>
          <Megaphone /> Send proactive message
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Message {customerName}</DialogTitle>
          <DialogDescription>
            A business-initiated message. It needs the customer&apos;s opt-in, respects DND and
            is allowed only between 09:00 and 21:00 IST.
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div data-testid="outreach-result" data-allowed={result.compliance.allowed}>
            {result.compliance.allowed ? (
              <p className="flex items-center gap-2 text-sm text-ok">
                <CheckCircle2 className="size-4" /> Passed compliance and queued for delivery.
              </p>
            ) : (
              <div className="space-y-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
                <p className="flex items-center gap-2 font-medium text-destructive">
                  <ShieldX className="size-4" /> Blocked by compliance
                </p>
                <ul className="list-disc space-y-0.5 pl-5 text-destructive" data-testid="compliance-reasons">
                  {failed.map((c) => (
                    <li key={c.rule_id} data-rule={c.rule_id}>
                      {c.reason ?? c.rule_id}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <Link
              href={`/inbox/${result.message.conversation_id}`}
              className="mt-3 inline-block text-sm text-primary underline-offset-2 hover:underline"
            >
              Open conversation #{result.message.conversation_id}
            </Link>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="outreach-channel">Channel</Label>
              <Select value={channel} onValueChange={(v) => setChannel(v as Channel)}>
                <SelectTrigger id="outreach-channel" className="w-40">
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
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="outreach-body">Message</Label>
              <Textarea
                id="outreach-body"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={4}
                placeholder="e.g. Your new fixed deposit rates are now available in the app."
              />
            </div>
          </div>
        )}

        <DialogFooter>
          {result ? (
            <Button onClick={() => reset(false)}>Done</Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => reset(false)}>
                Cancel
              </Button>
              <Button onClick={send} disabled={!body.trim() || outreach.isPending}>
                {outreach.isPending && <Loader2 className="animate-spin" />}
                Send
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
