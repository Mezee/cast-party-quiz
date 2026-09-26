# Convex spike

A parallel implementation of the quiz backend on [Convex](https://convex.dev), with
the box reduced to a **display adapter**. This exists to compare against the
original single-process Python version on `main`.

## Architecture

```
phones ──convex-js (reactive onUpdate)──►  Convex deployment
                                            schema: games, players, answers, questions
                                            mutations + scheduler.runAfter transitions
                                                  │
                                     convex_subscriber.py  (separate process)
                                                  │  mirrors latest state to JSON
                                                  ▼
                     convex_adapter.py ──► render.py ──► ffmpeg ──► HLS ──► TV
```

All game logic lives in `convex/`. The box only renders and streams.

## What Convex replaces

| Original (`main`) | Here |
|---|---|
| In-memory `dict` state, lost on restart | `games` / `players` / `answers` tables |
| Lazy `tick()` that advanced the state machine on whoever polled next | `scheduler.runAfter` with a stored, cancellable job id |
| 700 ms HTTP polling from every client | one reactive `onUpdate` subscription per client |
| Server computes `seconds_left` on each read | clients derive it from `phaseEndsAt` (no server "time" work) |
| Hand-rolled `/api/*` JSON endpoints | mutations + a single `gameState` query |
| One game at a time | any number of games, addressed by id + join code |

## Findings from building it

These cost real debugging time and are worth knowing:

1. **A local Convex deployment works without Docker.**
   `convex dev --configure new --dev-deployment local` downloads a backend binary
   and runs it on `127.0.0.1:3210` (SQLite under `.convex/`). That made it possible
   to build and test the whole thing offline.

2. **The Python client returns every number as a float** (JSON has no ints).
   `questionIndex` arrives as `1.0`. The adapter coerces with `int(round(...))`.

3. **The Python client's blocking `next()` starves other Python threads.**
   With a subscription running, `threading.Thread.start()` hung indefinitely, and
   later the render loop stopped producing frames. Symptom: the adapter listened
   on its port but never rendered. Diagnosed with `python -X faulthandler` +
   `SIGABRT` stack dump, which showed the main thread stuck in `Thread.start()`
   waiting on the GIL. **Fix: run the subscription in its own process**
   (`convex_subscriber.py`) and mirror state to a JSON file.

4. **`ThreadingHTTPServer` can hang on `socket.getfqdn()`** during bind. It did
   here once the Convex runtime was up. Fixed by overriding `server_bind` to skip
   the reverse lookup (`FastHTTPServer` in `convex_adapter.py`).

5. **The JS client API is `onUpdate`, not `subscribe`.** And it takes a
   `FunctionReference`, not a string. A reference is just
   `{ [Symbol.for("functionName")]: "games:gameState" }`, so the frontend builds
   them inline and needs no generated code or bundler.

6. **Answer submission must be idempotent.** Checking the phase before the
   duplicate-answer check meant a re-submit (double tap, retry after reveal)
   threw `Not accepting answers right now`. Reordered so an existing answer is
   returned early.

## Running it

```bash
npm install
convex dev --configure new --dev-deployment local --project <name>   # or just: convex dev
convex run questions:seed
GID=$(convex run games:createGame | python3 -c "import json,sys;print(json.load(sys.stdin)['gameId'])")

./venv/bin/python convex_subscriber.py --game-id "$GID" --convex-url http://127.0.0.1:3210 &
./venv/bin/python convex_adapter.py --game-id "$GID" --port 8080 &
./venv/bin/python cast_tv.py --ip <tv-ip> --url http://<box-ip>:8080/stream/out.m3u8
```

Phones open `http://<box-ip>:8080/join`; host console is `?as=host`.

To use Convex Cloud instead, deploy (`convex deploy`) and point
`--convex-url` at the cloud URL; the local binary is not needed.

## Verified

Tested end-to-end against the local deployment:

* 24 questions seeded; game created; 2–3 players joined; duplicate names
  disambiguated as `Ada (2)`.
* Answer hidden until reveal; fastest correct answer scored **991** (of 1000),
  wrong answer scored 0, counts `[1, 1, 0, 0]`.
* Re-submits silently ignored.
* Scheduled transitions fired at **8.1 s** (reveal → scores) and **15.0 s**
  (scores → next question) with no polling.
* Reactive subscription pushed `lobby → question → answered=1` to a separate
  process.
* A frame decoded back out of the live HLS stream showed exactly the Convex
  state (Q13/24, Art, correct 15 s countdown, 3 players).

## Verdict

Better at: real timers, persistence, history/leaderboards, multiple games,
remote/cellular players, and dropping all polling.

Worse at: it needs the internet and a third-party service, so the "works at a
party even if the WiFi uplink dies" property is gone — and the box is still
required for the TV.
