import { v } from "convex/values";
import { internal } from "./_generated/api";
import type { Doc, Id } from "./_generated/dataModel";
import { internalMutation, mutation, query } from "./_generated/server";
import type { MutationCtx } from "./_generated/server";

const BASE_POINTS = 500;
const BONUS_POINTS = 500;
const MAX_NAME = 16;

type Phase = "lobby" | "question" | "reveal" | "scores" | "final";

function pointsFor(correct: boolean, remainingMs: number, questionMs: number): number {
  if (!correct) return 0;
  const frac = Math.max(0, Math.min(1, remainingMs / questionMs));
  return Math.floor(BASE_POINTS + BONUS_POINTS * frac);
}

function randomCode(): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let out = "";
  for (let i = 0; i < 4; i++) out += alphabet[Math.floor(Math.random() * alphabet.length)];
  return out;
}

/** Cancel the pending scheduled transition, if any. */
async function cancelJob(ctx: MutationCtx, game: Doc<"games">): Promise<void> {
  if (!game.advanceJobId) return;
  try {
    await ctx.scheduler.cancel(game.advanceJobId);
  } catch {
    // already ran / already cancelled
  }
}

async function startQuestion(
  ctx: MutationCtx,
  game: Doc<"games">,
  index: number,
  now: number,
): Promise<void> {
  const jobId = await ctx.scheduler.runAfter(
    game.questionSeconds * 1000,
    internal.games.advance,
    { gameId: game._id, questionIndex: index, from: "question" },
  );
  await ctx.db.patch(game._id, {
    phase: "question",
    questionIndex: index,
    phaseEndsAt: now + game.questionSeconds * 1000,
    advanceJobId: jobId,
  });
}

async function enterReveal(
  ctx: MutationCtx,
  game: Doc<"games">,
  now: number,
): Promise<void> {
  const jobId = await ctx.scheduler.runAfter(
    game.revealSeconds * 1000,
    internal.games.advance,
    { gameId: game._id, questionIndex: game.questionIndex, from: "reveal" },
  );
  await ctx.db.patch(game._id, {
    phase: "reveal",
    phaseEndsAt: now + game.revealSeconds * 1000,
    advanceJobId: jobId,
  });
}

async function enterScores(
  ctx: MutationCtx,
  game: Doc<"games">,
  now: number,
): Promise<void> {
  const jobId = await ctx.scheduler.runAfter(
    game.scoresSeconds * 1000,
    internal.games.advance,
    { gameId: game._id, questionIndex: game.questionIndex, from: "scores" },
  );
  await ctx.db.patch(game._id, {
    phase: "scores",
    phaseEndsAt: now + game.scoresSeconds * 1000,
    advanceJobId: jobId,
  });
}

/**
 * The scheduled transition. It carries the phase it expects to be leaving, so
 * a stale timer (after a manual "next" or "restart") simply no-ops.
 */
export const advance = internalMutation({
  args: {
    gameId: v.id("games"),
    questionIndex: v.number(),
    from: v.union(v.literal("question"), v.literal("reveal"), v.literal("scores")),
  },
  handler: async (ctx, { gameId, questionIndex, from }) => {
    const game = await ctx.db.get(gameId);
    if (!game) return;
    if (game.phase !== from || game.questionIndex !== questionIndex) return;

    const now = Date.now();
    if (from === "question") {
      await enterReveal(ctx, game, now);
    } else if (from === "reveal") {
      await enterScores(ctx, game, now);
    } else {
      const next = questionIndex + 1;
      if (next >= game.questionIds.length) {
        await ctx.db.patch(gameId, {
          phase: "final",
          phaseEndsAt: undefined,
          advanceJobId: undefined,
        });
      } else {
        await startQuestion(ctx, game, next, now);
      }
    }
  },
});

export const createGame = mutation({
  args: {},
  handler: async (ctx) => {
    const all = await ctx.db.query("questions").collect();
    if (all.length === 0) {
      throw new Error("No questions in the database. Run questions:seed first.");
    }
    all.sort((a, b) => a._creationTime - b._creationTime);

    let code = randomCode();
    for (let i = 0; i < 12; i++) {
      const clash = await ctx.db
        .query("games")
        .withIndex("by_code", (q) => q.eq("code", code))
        .first();
      if (!clash) break;
      code = randomCode();
    }

    const gameId = await ctx.db.insert("games", {
      code,
      phase: "lobby",
      questionIndex: -1,
      questionSeconds: 20,
      revealSeconds: 8,
      scoresSeconds: 7,
      questionIds: all.map((q) => q._id),
    });
    return { gameId, code };
  },
});

export const joinGame = mutation({
  args: { gameId: v.id("games"), name: v.string() },
  handler: async (ctx, { gameId, name }) => {
    const game = await ctx.db.get(gameId);
    if (!game) throw new Error("Game not found");
    const players = await ctx.db
      .query("players")
      .withIndex("by_game", (q) => q.eq("gameId", gameId))
      .collect();

    let display = name.trim().slice(0, MAX_NAME) || "Player";
    const base = display;
    let n = 2;
    while (players.some((p) => p.name === display)) display = `${base} (${n++})`;

    const playerId = await ctx.db.insert("players", { gameId, name: display });
    return { playerId, name: display };
  },
});

export const startGame = mutation({
  args: { gameId: v.id("games") },
  handler: async (ctx, { gameId }) => {
    const game = await ctx.db.get(gameId);
    if (!game) throw new Error("Game not found");
    if (game.phase !== "lobby") return;
    await startQuestion(ctx, game, 0, Date.now());
  },
});

export const submitAnswer = mutation({
  args: {
    gameId: v.id("games"),
    playerId: v.id("players"),
    choice: v.number(),
  },
  handler: async (ctx, { gameId, playerId, choice }) => {
    const game = await ctx.db.get(gameId);
    if (!game) throw new Error("Game not found");

    // Idempotent first: a re-submit (double tap, retry after the reveal) for the
    // question we are already on must be silently ignored, not an error.
    const existing = await ctx.db
      .query("answers")
      .withIndex("by_player_q", (q) =>
        q.eq("playerId", playerId).eq("questionIndex", game.questionIndex),
      )
      .first();
    if (existing) return;

    if (game.phase !== "question" || game.questionIndex < 0) {
      throw new Error("Not accepting answers right now");
    }
    if (!Number.isInteger(choice) || choice < 0 || choice > 3) {
      throw new Error("Invalid choice");
    }

    const question = await ctx.db.get(game.questionIds[game.questionIndex]);
    if (!question) throw new Error("Question missing");

    const now = Date.now();
    const questionMs = game.questionSeconds * 1000;
    const remaining = (game.phaseEndsAt ?? now) - now;
    const correct = choice === question.answer;

    await ctx.db.insert("answers", {
      gameId,
      playerId,
      questionIndex: game.questionIndex,
      choice,
      answeredAt: now,
      correct,
      points: pointsFor(correct, remaining, questionMs),
    });

    // Everyone in? Reveal immediately instead of waiting out the clock.
    const players = await ctx.db
      .query("players")
      .withIndex("by_game", (q) => q.eq("gameId", gameId))
      .collect();
    const answers = await ctx.db
      .query("answers")
      .withIndex("by_game_q", (q) =>
        q.eq("gameId", gameId).eq("questionIndex", game.questionIndex),
      )
      .collect();
    if (players.length > 0 && answers.length >= players.length) {
      await cancelJob(ctx, game);
      await enterReveal(ctx, game, now);
    }
  },
});

export const hostAction = mutation({
  args: {
    gameId: v.id("games"),
    action: v.union(
      v.literal("reveal"),
      v.literal("scores"),
      v.literal("next"),
      v.literal("addTime"),
      v.literal("restart"),
    ),
  },
  handler: async (ctx, { gameId, action }) => {
    const game = await ctx.db.get(gameId);
    if (!game) throw new Error("Game not found");
    const now = Date.now();
    await cancelJob(ctx, game);

    if (action === "reveal") {
      if (game.phase === "question") await enterReveal(ctx, game, now);
    } else if (action === "scores") {
      if (game.phase === "reveal") await enterScores(ctx, game, now);
    } else if (action === "next") {
      const next = game.questionIndex + 1;
      if (next >= game.questionIds.length) {
        await ctx.db.patch(gameId, {
          phase: "final",
          phaseEndsAt: undefined,
          advanceJobId: undefined,
        });
      } else {
        await startQuestion(ctx, game, next, now);
      }
    } else if (action === "addTime") {
      if (game.phase === "question") {
        const phaseEndsAt = (game.phaseEndsAt ?? now) + 10_000;
        const jobId = await ctx.scheduler.runAfter(
          Math.max(0, phaseEndsAt - now),
          internal.games.advance,
          { gameId, questionIndex: game.questionIndex, from: "question" },
        );
        await ctx.db.patch(gameId, { phaseEndsAt, advanceJobId: jobId });
      }
    } else if (action === "restart") {
      const answers = await ctx.db
        .query("answers")
        .withIndex("by_game_q", (q) => q.eq("gameId", gameId))
        .collect();
      for (const a of answers) await ctx.db.delete(a._id);
      await ctx.db.patch(gameId, {
        phase: "lobby",
        questionIndex: -1,
        phaseEndsAt: undefined,
        advanceJobId: undefined,
      });
    }
  },
});

/**
 * The single reactive query every client subscribes to. Countdowns are derived
 * client-side from `phaseEndsAt`, so nothing has to poll to keep time moving.
 */
export const gameState = query({
  args: {
    gameId: v.id("games"),
    playerId: v.optional(v.id("players")),
  },
  handler: async (ctx, { gameId, playerId }) => {
    const game = await ctx.db.get(gameId);
    if (!game) return null;

    const players = await ctx.db
      .query("players")
      .withIndex("by_game", (q) => q.eq("gameId", gameId))
      .collect();
    const answers = await ctx.db
      .query("answers")
      .withIndex("by_game_q", (q) => q.eq("gameId", gameId))
      .collect();

    const idx = game.questionIndex;
    const question =
      idx >= 0 && idx < game.questionIds.length
        ? await ctx.db.get(game.questionIds[idx])
        : null;

    const revealed =
      game.phase === "reveal" || game.phase === "scores" || game.phase === "final";

    const counts = [0, 0, 0, 0];
    for (const a of answers) if (a.questionIndex === idx) counts[a.choice]++;

    // Scores exclude the in-flight question until it is revealed, so a player
    // cannot infer correctness from their own total early.
    const totals = new Map<Id<"players">, number>();
    for (const p of players) totals.set(p._id, 0);
    for (const a of answers) {
      if (a.questionIndex === idx && !revealed) continue;
      totals.set(a.playerId, (totals.get(a.playerId) ?? 0) + a.points);
    }

    const ranking = players
      .map((p) => ({ playerId: p._id, name: p.name, score: totals.get(p._id) ?? 0 }))
      .sort(
        (x, y) => y.score - x.score || x.name.toLowerCase().localeCompare(y.name.toLowerCase()),
      )
      .map((r, i) => ({ ...r, rank: i + 1 }));

    const mine = playerId
      ? (answers.find((a) => a.playerId === playerId && a.questionIndex === idx) ?? null)
      : null;

    return {
      gameId,
      code: game.code,
      phase: game.phase as Phase,
      questionIndex: idx,
      questionCount: game.questionIds.length,
      questionSeconds: game.questionSeconds,
      phaseEndsAt: game.phaseEndsAt ?? null,
      cat: question?.cat ?? null,
      question: question?.text ?? null,
      options: question?.options ?? [],
      answer: revealed && question ? question.answer : null,
      counts,
      answered: answers.filter((a) => a.questionIndex === idx).length,
      playerCount: players.length,
      players: players.map((p) => ({ playerId: p._id, name: p.name })),
      ranking,
      you: playerId
        ? {
            playerId,
            name: players.find((p) => p._id === playerId)?.name ?? null,
            score: totals.get(playerId) ?? 0,
            rank: ranking.find((r) => r.playerId === playerId)?.rank ?? null,
            choice: mine?.choice ?? null,
            correct: revealed && mine ? mine.correct : null,
            points: revealed && mine ? mine.points : null,
          }
        : null,
    };
  },
});
