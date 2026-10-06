"use client";

import { BadgeCheck, Link2, Loader2, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Avatar } from "@/components/badges";
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
import { Input } from "@/components/ui/input";
import { useCustomers, useLinkCustomer } from "@/lib/queries";
import { cn } from "@/lib/utils";

/** Merge this unverified sender into a verified customer (ARCHITECTURE §6.6). */
export function LinkCustomerDialog({
  sourceId,
  sourceName,
}: {
  sourceId: number;
  sourceName: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [targetId, setTargetId] = useState<number | null>(null);
  const customers = useCustomers(q.trim());
  const link = useLinkCustomer();
  const candidates = customers.data?.items.filter((c) => c.verified && c.id !== sourceId) ?? [];
  const target = candidates.find((c) => c.id === targetId);

  function confirm() {
    if (targetId == null) return;
    link.mutate(
      { targetId, sourceId },
      {
        onSuccess: (customer) => {
          toast.success(`Linked to ${customer.display_name}`);
          setOpen(false);
          router.replace(`/customers/${customer.id}`);
        },
        onError: (e) => toast.error("Link failed", { description: e.message }),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Link2 /> Link to existing customer
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Link {sourceName} to a customer</DialogTitle>
          <DialogDescription>
            Their contacts and conversations move to the customer you pick, and this sender
            record is removed. Check identity first: a wrong link mixes two people&apos;s data.
          </DialogDescription>
        </DialogHeader>

        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search verified customers"
            aria-label="Search verified customers"
            className="pl-8"
            autoFocus
          />
        </div>
        <ul className="max-h-64 divide-y overflow-y-auto rounded-md border" role="listbox">
          {candidates.length === 0 && (
            <li className="p-4 text-center text-sm text-muted-foreground">
              {customers.isLoading ? "Searching…" : "No verified customers match."}
            </li>
          )}
          {candidates.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                role="option"
                aria-selected={c.id === targetId}
                onClick={() => setTargetId(c.id)}
                className={cn(
                  "flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/60",
                  c.id === targetId && "bg-accent hover:bg-accent",
                )}
              >
                <Avatar name={c.display_name} className="size-7" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1 text-sm font-medium">
                    {c.display_name} <BadgeCheck className="size-3.5 text-primary" />
                  </span>
                  <span className="tabular block truncate text-xs text-muted-foreground">
                    {c.contacts.map((ct) => ct.value_normalized).join(" · ")}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={confirm} disabled={!target || link.isPending}>
            {link.isPending && <Loader2 className="animate-spin" />}
            {target ? `Link to ${target.display_name}` : "Choose a customer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
