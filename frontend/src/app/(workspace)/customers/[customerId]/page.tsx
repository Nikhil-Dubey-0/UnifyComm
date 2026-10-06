"use client";

import { ArrowLeft, BadgeCheck, Loader2, Mail, Phone } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Avatar, CategoryBadge, ChannelIcon, PriorityBadge, StatusBadge } from "@/components/badges";
import { LinkCustomerDialog } from "@/components/customers/link-customer-dialog";
import type { Channel } from "@/lib/api/client";
import { CHANNEL_LABEL, formatDateTime } from "@/lib/format";
import { useCustomer } from "@/lib/queries";
import { cn } from "@/lib/utils";

const CONSENT_LABEL = { opted_in: "Opted in", opted_out: "Opted out", unknown: "Unknown" };

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
            {preferences.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No consent recorded. Proactive messages need an opt-in.
              </p>
            ) : (
              <ul className="space-y-2 text-sm">
                {preferences.map((p) => (
                  <li key={p.channel} className="flex items-center gap-2">
                    <ChannelIcon channel={p.channel as Channel} />
                    <span className="w-20">{CHANNEL_LABEL[p.channel as Channel]}</span>
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-[11px] font-medium",
                        p.consent === "opted_in" && "bg-ok/12 text-ok",
                        p.consent === "opted_out" && "bg-urgent/10 text-urgent",
                        p.consent === "unknown" && "bg-muted text-muted-foreground",
                      )}
                    >
                      {CONSENT_LABEL[p.consent]}
                    </span>
                    {p.dnd && (
                      <span className="rounded-full bg-high/15 px-2 py-0.5 text-[11px] font-medium text-[oklch(0.5_0.13_62)]">
                        DND
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
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
