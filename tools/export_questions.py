#!/usr/bin/env python3
"""Regenerate convex/questions.ts from the Python question bank in server.py."""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import server  # noqa: E402

ts = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731
out = [
    "// AUTO-GENERATED from the original Python question bank.",
    "// Regenerate with: ./venv/bin/python tools/export_questions.py",
    'import { mutation, query } from "./_generated/server";',
    "",
    "export const BANK = [",
]
for q in server.QUESTIONS:
    out.append("  { cat: %s, text: %s," % (ts(q["cat"]), ts(q["q"])))
    out.append("    options: %s, answer: %d }," % (ts(q["options"]), q["a"]))
out.append("] as const;")
out.append("")
out.append("""export const seed = mutation({
  args: {},
  handler: async (ctx) => {
    const existing = await ctx.db.query("questions").first();
    if (existing) return { seeded: false, count: 0 };
    for (const q of BANK) {
      await ctx.db.insert("questions", {
        cat: q.cat,
        text: q.text,
        options: [...q.options],
        answer: q.answer,
      });
    }
    return { seeded: true, count: BANK.length };
  },
});

export const list = query({
  args: {},
  handler: async (ctx) => {
    const qs = await ctx.db.query("questions").collect();
    qs.sort((a, b) => a._creationTime - b._creationTime);
    return qs.map((q) => ({
      id: q._id,
      cat: q.cat,
      text: q.text,
      options: q.options,
      answer: q.answer,
    }));
  },
});""")
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "convex", "questions.ts")
open(path, "w").write("\n".join(out) + "\n")
print("wrote", path)
