import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Don't auto-generate frontend/AGENTS.md and frontend/CLAUDE.md on every
  // `next dev` — this repo already has its own CLAUDE.md at the root with
  // real project conventions; an auto-generated stub alongside it would
  // just be confusing.
  agentRules: false,
};

export default nextConfig;
