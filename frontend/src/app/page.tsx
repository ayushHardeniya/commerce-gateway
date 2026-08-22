"use client";

import { useEffect, useState } from "react";
import { fetchHealth } from "@/lib/api";

type ApiStatus = "checking" | "online" | "offline";

export default function Home() {
  const [status, setStatus] = useState<ApiStatus>("checking");

  useEffect(() => {
    fetchHealth()
      .then(() => setStatus("online"))
      .catch(() => setStatus("offline"));
  }, []);

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 bg-zinc-50 px-6 font-sans dark:bg-black">
      <div className="flex flex-col items-center gap-2 text-center">
        <h1 className="text-3xl font-semibold tracking-tight text-black dark:text-zinc-50">
          Commerce Gateway
        </h1>
        <p className="max-w-md text-zinc-600 dark:text-zinc-400">
          AI-native commerce infrastructure for policy-governed agentic checkout.
        </p>
      </div>
      <div className="flex items-center gap-2 rounded-full border border-black/10 px-4 py-2 text-sm dark:border-white/10">
        <span
          className={`h-2 w-2 rounded-full ${
            status === "online"
              ? "bg-green-500"
              : status === "offline"
                ? "bg-red-500"
                : "bg-yellow-500"
          }`}
        />
        <span className="text-zinc-700 dark:text-zinc-300">
          API status: {status}
        </span>
      </div>
    </div>
  );
}
