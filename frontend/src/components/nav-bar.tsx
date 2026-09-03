"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { TransactionLookupForm } from "./transaction-lookup-form";

const LINKS = [
  { href: "/", label: "AI Buyer" },
  { href: "/transactions", label: "Transactions" },
  { href: "/merchant", label: "Merchant" },
] as const;

export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-black/10 bg-white/80 px-4 py-2.5 backdrop-blur-sm sm:px-6 dark:border-white/10 dark:bg-black/80">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <Link href="/" className="flex shrink-0 items-center gap-2">
          <Image
            src="/logo-dark-brand-mark.png"
            alt=""
            width={240}
            height={240}
            priority
            className="h-5 w-5 shrink-0"
          />
          <span className="flex items-baseline gap-1.5">
            <span className="text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
              Commerce Gateway
            </span>
            <span className="hidden text-[11px] text-zinc-400 sm:inline dark:text-zinc-600">
              AI-native commerce
            </span>
          </span>
        </Link>
        <nav className="flex flex-wrap items-center gap-1">
          {LINKS.map((link) => {
            const active =
              link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`shrink-0 rounded-md px-2.5 py-1 text-sm font-medium transition-colors ${
                  active
                    ? "bg-zinc-900 text-white dark:bg-zinc-50 dark:text-black"
                    : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-900"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
      {/* Its own row once the brand+nav group no longer leaves room — a
          fixed-width search box has no sensible way to keep shrinking. */}
      <div className="w-full shrink-0 sm:w-auto">
        <TransactionLookupForm />
      </div>
    </header>
  );
}
