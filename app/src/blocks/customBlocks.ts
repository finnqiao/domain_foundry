import { registerBlock } from "./registry";

// Side-loaded custom blocks (plan §9.3). At startup the shell tries to import
// an ESM bundle the user dropped into ~/.domain_expert/blocks/, served by the
// FastAPI app at /custom-blocks/index.js. The module may either default-export
// a register(fn) function, or export `register`. Custom blocks are TRUSTED code
// (documented in docs/custom-blocks.md) — nothing is loaded unless the user
// deliberately places a build there.
export async function loadCustomBlocks(): Promise<string[]> {
  try {
    const res = await fetch("/custom-blocks/index.js", { method: "HEAD" });
    if (!res.ok) return [];
  } catch {
    return [];
  }
  try {
    // Built with a variable path so the bundler/TS don't try to resolve it at
    // build time — this module only exists at runtime in the user's workspace.
    const modPath = "/custom-blocks/index.js";
    const mod = (await import(/* @vite-ignore */ modPath)) as {
      register?: (r: typeof registerBlock) => void | string[];
      default?: (r: typeof registerBlock) => void | string[];
    };
    const fn = mod.register ?? mod.default;
    if (typeof fn === "function") {
      const ids = fn(registerBlock);
      return Array.isArray(ids) ? ids : [];
    }
  } catch (e) {
    console.warn("[domain_expert] failed to load custom blocks:", e);
  }
  return [];
}
