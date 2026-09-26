import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

/**
 * Phase progression:
 *   lobby -> question -> reveal -> scores -> (question | final)
 */
export const PHASES = ["lobby", "question", "reveal", "scores", "final"] as const;
export const phaseValidator = v.union(
  v.literal("lobby"),
  v.literal("question"),
  v.literal("reveal"),
  v.literal("scores"),
  v.literal("final"),
);

export default defineSchema({
  games: defineTable({
    code: v.string(),
    phase: phaseValidator,
    questionIndex: v.number(),
    // Absolute deadline for the current phase (ms since epoch). Clients derive
    // their own countdown from this, so no server-side "tick" is needed.
    phaseEndsAt: v.optional(v.number()),
    questionSeconds: v.number(),
    revealSeconds: v.number(),
    scoresSeconds: v.number(),
    questionIds: v.array(v.id("questions")),
    // The pending scheduled transition, so we can cancel it on manual control.
    advanceJobId: v.optional(v.id("_scheduled_functions")),
  }).index("by_code", ["code"]),

  players: defineTable({
    gameId: v.id("games"),
    name: v.string(),
  }).index("by_game", ["gameId"]),

  answers: defineTable({
    gameId: v.id("games"),
    playerId: v.id("players"),
    questionIndex: v.number(),
    choice: v.number(),
    answeredAt: v.number(),
    // Computed when the answer lands; the query hides it until reveal so
    // nobody can infer correctness early.
    correct: v.boolean(),
    points: v.number(),
  })
    .index("by_game_q", ["gameId", "questionIndex"])
    .index("by_player_q", ["playerId", "questionIndex"]),

  questions: defineTable({
    cat: v.string(),
    text: v.string(),
    options: v.array(v.string()),
    answer: v.number(),
  }),
});
