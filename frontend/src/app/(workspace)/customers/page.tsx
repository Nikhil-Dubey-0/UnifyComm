"use client";

import { BadgeCheck, Mail, Phone, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Avatar } from "@/components/badges";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useCustomers } from "@/lib/queries";

export default function CustomersPage() {
  const [q, setQ] = useState("");
  const customers = useCustomers(q.trim());

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-5 p-8">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold">Customers</h1>
            <p className="text-sm text-muted-foreground">
              Known customers and senders who are not matched yet.
            </p>
          </div>
          <div className="relative w-72">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search name, phone or email"
              aria-label="Search customers"
              className="pl-8"
            />
          </div>
        </header>

        <div className="overflow-hidden rounded-lg border bg-card">
          {customers.isLoading ? (
            <div className="space-y-3 p-4">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : customers.data?.items.length ? (
            <ul className="divide-y">
              {customers.data.items.map((c) => (
                <li key={c.id}>
                  <Link
                    href={`/customers/${c.id}`}
                    className="flex items-center gap-3 px-4 py-3 hover:bg-muted/60"
                  >
                    <Avatar name={c.display_name} />
                    <div className="min-w-0 flex-1">
                      <p className="flex items-center gap-1.5 font-medium">
                        <span className="truncate">{c.display_name}</span>
                        {c.verified ? (
                          <BadgeCheck className="size-4 shrink-0 text-primary" aria-label="Verified" />
                        ) : (
                          <span className="rounded-full bg-warn/15 px-1.5 text-[10px] font-medium text-[oklch(0.45_0.1_70)]">
                            Unverified
                          </span>
                        )}
                      </p>
                      <p className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                        {c.contacts.map((ct) => (
                          <span key={ct.id} className="tabular inline-flex items-center gap-1">
                            {ct.kind === "phone" ? <Phone className="size-3" /> : <Mail className="size-3" />}
                            {ct.value_normalized}
                          </span>
                        ))}
                      </p>
                    </div>
                    <span className="tabular text-xs text-muted-foreground">#{c.id}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="p-6 text-center text-sm text-muted-foreground">No customers found.</p>
          )}
        </div>
      </div>
    </div>
  );
}
