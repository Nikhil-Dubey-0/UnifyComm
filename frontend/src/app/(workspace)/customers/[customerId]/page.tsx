"use client";

import { ArrowLeft, BadgeCheck, Loader2, Mail, Phone } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Avatar, CategoryBadge, PriorityBadge, StatusBadge } from "@/components/badges";
import { LinkCustomerDialog } from "@/components/customers/link-customer-dialog";
import { OutreachDialog } from "@/components/customers/outreach-dialog";
import { CHANNELS, PreferenceControl } from "@/components/customers/preference-control";
import type { Channel } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";
import { useCustomer } from "@/lib/queries";

export default function CustomerPage() {
  const { customerId } = useParams<{ customerId: string }>();
  const query = useCustomer(Number(customerId));

  if (query.isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="size-5 animate-spin" aria-label="Loading customer" />
      </div>
    );
  }
  if (!query.data) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Customer not found.
      </div>
    );
  }
  const { customer, contacts, preferences, conversations } = query.data;
  const kinds = new Set(contacts.map((c) => c.kind));
  const channels: Channel[] = [
    ...(kinds.has("phone") ? (["whatsapp", "sms"] as const) : []),
    ...(kinds.has("email") ? (["email"] as const) : []),
  ];

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-6 p-8">
        <Link
          href="/customers"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Customers
        </Link>

        <header className="flex flex-wrap items-center gap-4">
          <Avatar name={customer.display_name} className="size-12 text-sm" />
          <div className="min-w-0 flex-1">
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              {customer.display_name}
              {customer.verified && <BadgeCheck className="size-5 text-primary" />}
            </h1>
            <p className="text-sm text-muted-foreground">
              {customer.verified ? "Verified customer" : "Unverified sender"} · customer #
              {customer.id} · since {formatDateTime(customer.created_at)}
            </p>
          </div>
          <OutreachDialog
            customerId={customer.id}
            customerName={customer.display_name}
            channels={channels}
          />
          {!customer.verified && (
            <LinkCustomerDialog sourceId={customer.id} sourceName={customer.display_name} />
          )}
        </header>

        <div className="grid gap-6 md:grid-cols-2">
          <Card title="Contacts">
            <ul className="space-y-2 text-sm">
              {contacts.map((c) => (
                <li key={c.id} className="flex items-center gap-2">
                  {c.kind === "phone" ? (
                    <Phone className="size-4 text-muted-foreground" />
                  ) : (
                    <Mail className="size-4 text-muted-foreground" />
                  )}
                  <span className="tabular">{c.value_normalized}</span>
                  {!c.verified && (
                    <span className="text-[11px] text-muted-foreground">(unverified)</span>
                  )}
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Channel preferences">
            <div className="space-y-2">
              {CHANNELS.map((channel) => (
                <PreferenceControl
                  key={channel}
                  customerId={customer.id}
                  channel={channel}
                  preference={preferences.find((p) => p.channel === channel)}
                />
              ))}
            </div>
            <p className="mt-3 text-[11px] text-muted-foreground">
              Opted out blocks every message on that channel. Proactive messages need an
              opt-in; DND allows service replies only.
            </p>
          </Card>
        </div>

        <Card title="Conversations">
          {conversations.length === 0 ? (
            <p className="text-sm text-muted-foreground">No conversations yet.</p>
          ) : (
            <ul className="-mx-4 divide-y">
              {conversations.map((c) => (
                <li key={c.id}>
                  <Link
                    href={`/inbox/${c.id}`}
                    className="flex flex-wrap items-center gap-2 px-4 py-2.5 hover:bg-muted/60"
                  >
                    <span className="tabular text-sm font-medium">#{c.id}</span>
                    <CategoryBadge queue={c.category_queue} />
                    <PriorityBadge priority={c.priority} />
                    <StatusBadge status={c.status} />
                    <span className="tabular ml-auto text-xs text-muted-foreground">
                      {formatDateTime(c.last_activity_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border bg-card p-4">
      <h2 className="mb-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {title}
      </h2>
      {children}
    </section>
  );
}
