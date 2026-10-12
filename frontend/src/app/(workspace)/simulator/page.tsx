"use client";

import { ExternalLink, Loader2, SendHorizontal, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Avatar, ChannelIcon } from "@/components/badges";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Channel, SimulatorContact, SimulatorThreadMessage } from "@/lib/api/client";
import { CHANNEL_LABEL, formatTime } from "@/lib/format";
import { useSimulatorContacts, useSimulatorSend, useSimulatorThread } from "@/lib/queries";
import { cn } from "@/lib/utils";

const CHANNELS: Channel[] = ["whatsapp", "sms", "email"];
const CUSTOM = "custom";

export default function SimulatorPage() {
  const contacts = useSimulatorContacts();
  const [persona, setPersona] = useState<number | typeof CUSTOM | null>(null);
  const [channel, setChannel] = useState<Channel>("whatsapp");
  const [customPhone, setCustomPhone] = useState("");
  const [customEmail, setCustomEmail] = useState("");
  const [customName, setCustomName] = useState("");

  // Until the user picks someone, the first seeded customer is selected.
  const activePersona = persona ?? contacts.data?.[0]?.customer_id ?? null;
  const selected =
    typeof activePersona === "number"
      ? contacts.data?.find((c) => c.customer_id === activePersona)
      : undefined;
  const customAddress = channel === "email" ? customEmail : customPhone;
  const address =
    activePersona === CUSTOM ? customAddress.trim() : (selected?.addresses[channel] ?? "");
  const known = contacts.data?.filter((c) => c.verified) ?? [];
  const recent = contacts.data?.filter((c) => !c.verified) ?? [];
  const name = activePersona === CUSTOM ? customName.trim() : (selected?.display_name ?? "");

  return (
    <div className="flex h-full overflow-hidden bg-muted/40">
      <aside className="flex w-80 shrink-0 flex-col gap-5 overflow-y-auto border-r bg-card p-5">
        <div>
          <h1 className="text-base font-semibold">Customer simulator</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Write as a customer. Messages enter through the same pipeline as real WhatsApp, SMS
            and email.
          </p>
          <Button
            variant="link"
            size="sm"
            className="mt-1 h-auto px-0"
            onClick={() => window.open("/simulator", "unifycomm-simulator", "width=560,height=900")}
          >
            Open in a separate window <ExternalLink />
          </Button>
        </div>

        <fieldset className="space-y-2">
          <legend className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Customer
          </legend>
          <p className="text-[11px] text-muted-foreground">Known to the bank (verified)</p>
          {known.map((c) => (
            <PersonaButton
              key={c.customer_id}
              contact={c}
              active={activePersona === c.customer_id}
              onClick={() => setPersona(c.customer_id)}
            />
          ))}
          {recent.length > 0 && (
            <>
              <p className="pt-2 text-[11px] text-muted-foreground">Recent new senders (unverified)</p>
              <div className="max-h-48 space-y-2 overflow-y-auto" data-testid="recent-senders">
                {recent.map((c) => (
                  <PersonaButton
                    key={c.customer_id}
                    contact={c}
                    active={activePersona === c.customer_id}
                    onClick={() => setPersona(c.customer_id)}
                  />
                ))}
              </div>
            </>
          )}
          <button
            type="button"
            onClick={() => setPersona(CUSTOM)}
            aria-pressed={activePersona === CUSTOM}
            className={cn(
              "flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left text-sm transition-colors hover:bg-muted/60",
              activePersona === CUSTOM && "border-primary/40 bg-accent hover:bg-accent",
            )}
          >
            <span className="flex size-8 items-center justify-center rounded-full border border-dashed">
              <UserRound className="size-4 text-muted-foreground" />
            </span>
            <span>
              <span className="block font-medium">New sender</span>
              <span className="text-xs text-muted-foreground">A phone number, an email, or both</span>
            </span>
          </button>
          {activePersona === CUSTOM && (
            <div className="space-y-2 rounded-lg border border-dashed p-3">
              <div className="space-y-1">
                <Label htmlFor="sim-phone" className="text-xs">
                  Phone number
                </Label>
                <Input
                  id="sim-phone"
                  value={customPhone}
                  onChange={(e) => setCustomPhone(e.target.value)}
                  placeholder="+91 90000 00000 (WhatsApp and SMS)"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="sim-email" className="text-xs">
                  Email address
                </Label>
                <Input
                  id="sim-email"
                  value={customEmail}
                  onChange={(e) => setCustomEmail(e.target.value)}
                  placeholder="someone@example.com (email)"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="sim-name" className="text-xs">
                  Display name (optional)
                </Label>
                <Input id="sim-name" value={customName} onChange={(e) => setCustomName(e.target.value)} />
              </div>
              <p className="text-[11px] leading-snug text-muted-foreground">
                An unknown phone number and an unknown email become two separate unverified
                customers: the bank never guesses that they are one person. Register the
                customer under Customers → New customer, or let an agent link the two senders.
              </p>
            </div>
          )}
        </fieldset>

        <fieldset>
          <legend className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Channel
          </legend>
          <div role="radiogroup" className="grid grid-cols-3 gap-1.5">
            {CHANNELS.map((ch) => {
              const available = activePersona === CUSTOM || !!selected?.addresses[ch];
              return (
                <button
                  key={ch}
                  type="button"
                  role="radio"
                  aria-checked={channel === ch}
                  disabled={!available}
                  onClick={() => setChannel(ch)}
                  className={cn(
                    "flex flex-col items-center gap-1 rounded-lg border py-2 text-xs transition-colors hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-40",
                    channel === ch && "border-primary/40 bg-accent font-medium hover:bg-accent",
                  )}
                >
                  <ChannelIcon channel={ch} className="size-4" />
                  {CHANNEL_LABEL[ch]}
                </button>
              );
            })}
          </div>
        </fieldset>
      </aside>

      <section className="flex min-w-0 flex-1 items-center justify-center p-6">
        <Phone
          channel={channel}
          address={address}
          name={name}
          onSent={(customerId) => {
            // The new sender is now saved: select it, as the customer list will show it.
            if (activePersona === CUSTOM) setPersona(customerId);
          }}
        />
      </section>
    </div>
  );
}

function PersonaButton({
  contact,
  active,
  onClick,
}: {
  contact: SimulatorContact;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left text-sm transition-colors hover:bg-muted/60",
        active && "border-primary/40 bg-accent hover:bg-accent",
      )}
    >
      <Avatar name={contact.display_name} className="size-8" />
      <span className="min-w-0">
        <span className="block font-medium">{contact.display_name}</span>
        <span className="tabular block truncate text-xs text-muted-foreground">
          {[contact.addresses.whatsapp, contact.addresses.email].filter(Boolean).join(" · ")}
        </span>
      </span>
    </button>
  );
}

function Phone({
  channel,
  address,
  name,
  onSent,
}: {
  channel: Channel;
  address: string;
  name: string;
  onSent: (customerId: number) => void;
}) {
  const thread = useSimulatorThread(channel, address);
  const sendMessage = useSimulatorSend();
  const [body, setBody] = useState("");
  const [subject, setSubject] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const messages = thread.data ?? [];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!address || !body.trim()) return;
    sendMessage.mutate(
      {
        channel,
        from: address,
        body: body.trim(),
        sender_name: name || undefined,
        subject: channel === "email" && subject.trim() ? subject.trim() : undefined,
      },
      {
        onSuccess: (result) => {
          setBody("");
          onSent(result.customer_id);
        },
        onError: (err) => toast.error("Message not sent", { description: err.message }),
      },
    );
  }

  return (
    <div className="flex h-full max-h-[52rem] w-full max-w-sm flex-col overflow-hidden rounded-[2rem] border-8 border-foreground/90 bg-card shadow-2xl">
      <header className="flex items-center gap-2.5 border-b bg-secondary px-4 py-3">
        <ChannelIcon channel={channel} className="size-5" />
        <div className="min-w-0">
          <p className="text-sm font-semibold">UnifyBank Support</p>
          <p className="tabular truncate text-[11px] text-muted-foreground">
            {CHANNEL_LABEL[channel]} · you are {address || "…"}
          </p>
        </div>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-background p-4" data-testid="sim-thread">
        {!address ? (
          <p className="pt-10 text-center text-sm text-muted-foreground">Choose who is writing.</p>
        ) : thread.isLoading ? (
          <Loader2 className="mx-auto mt-10 size-5 animate-spin text-muted-foreground" />
        ) : messages.length === 0 ? (
          <p className="pt-10 text-center text-sm text-muted-foreground">
            No messages yet. Say hello to the bank.
          </p>
        ) : (
          messages.map((m) => <PhoneBubble key={m.id} message={m} />)
        )}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={submit} className="space-y-2 border-t bg-card p-3">
        {channel === "email" && (
          <Input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Subject"
            aria-label="Subject"
            className="h-8 text-sm"
          />
        )}
        <div className="flex items-end gap-2">
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Type a message"
            aria-label="Customer message"
            rows={1}
            className="max-h-32 min-h-9 resize-none rounded-2xl text-sm"
          />
          <Button
            type="submit"
            size="icon"
            className="shrink-0 rounded-full"
            aria-label="Send as customer"
            disabled={!address || !body.trim() || sendMessage.isPending}
          >
            {sendMessage.isPending ? <Loader2 className="animate-spin" /> : <SendHorizontal />}
          </Button>
        </div>
      </form>
    </div>
  );
}

function PhoneBubble({ message: m }: { message: SimulatorThreadMessage }) {
  const mine = m.direction === "inbound"; // the customer's own message
  if (!mine && m.delivery_status !== "delivered" && m.delivery_status !== "sent") return null;
  return (
    <div
      data-testid="sim-message"
      data-direction={m.direction}
      className={cn("flex flex-col", mine ? "items-end" : "items-start")}
    >
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3 py-2 text-sm shadow-xs",
          mine ? "rounded-br-sm bg-whatsapp/15" : "rounded-bl-sm border bg-card",
        )}
      >
        {m.subject && <p className="mb-0.5 text-xs font-semibold">{m.subject}</p>}
        <p className="break-words whitespace-pre-wrap">{m.body}</p>
      </div>
      <time dateTime={m.created_at} className="tabular mt-0.5 px-1 text-[10px] text-muted-foreground">
        {formatTime(m.created_at)}
      </time>
    </div>
  );
}
