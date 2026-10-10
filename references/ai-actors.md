# Bots and AI agents as equal participants

Use this when an app has AI actors: game bots, or agents that act through the app's own interface. The goal is that human and AI behaviour can be compared one to one, so the recorded human data can make the AI more human. Rat Detective's version is in its `docs/bot-overhaul.md` and `docs/bot-learning-plan.md`.

## The contract

- **One action path.** An AI produces exactly the commands a human's client sends, through the same validation, rate limits, cooldowns and simulation step. No AI-only movement rules, copied constants, clamps, speed caps or shortcuts. If one is unavoidable, list it as a known difference and record it as a fact each time it happens (Rat Detective's stuck-bot teleport is a `rescue` fact).
- **Only the mind and skill differ.** Skill is a small set of dials: reaction delay, aim or click error, turn or cursor speed, command interval. Personalities multiply goal scores; they never add abilities. Every personality is equal to or worse than the base on every dial, enforced by a test.
- **Perception is what a human could know:** line of sight, fog of war, hearing within range, last-seen memory with an age, and for screen-based games the camera view and minimap. Never the server's full state. Information leaks are the second most common AI bug, so test that an AI cannot react to something it could not see.
- **The same recording.** AI inputs, aim and decisions are recorded in the same format as human inputs, with `who: bot`.

## Minds

- **Layers:** perception → mind (a goal and a stance, decided rarely) → plan → motor (each tick, plan → commands) → the shared action path. Constant responses, such as firing back, belong to the motor, not the mind.
- **Decide rarely, like humans.** Decide at moments (spawn, goal ended or failed, objective changed hands, new option available) and at most every 10 s otherwise. Being hit is not a decision moment. Asking once a second made Rat Detective's goals last 2.2 s and get replaced 89% of the time.
- **Reflexes come from data.** A "missed" fact, such as an item walked past, shows what humans never skip. Make that a reflex, then measure it the same way for humans and AI.
- **An LLM mind, if used:**
  - Ask once per decision moment, with a separate score for each offered goal (a single "which goal?" choice always picked the objective).
  - Describe the situation in words, not coordinates or raw distances; numbers made the scores go the wrong way.
  - Never send player-chosen names. Use a short timeout, and drop answers that are stale or whose target has left view.
  - Switch it on only while a real human has given input in the last minute.
  - A daily budget ledger fails closed.
- **Control sessions:** about one session in five, chosen by hashing the session id, runs the free code mind even with humans present, so the paid mind can be compared with it on the same build.

## Learning from the data

1. Record decisions with their inputs, then copy the LLM mind into the code mind. Fit goal and stance scores per personality, validate on held-out sessions, and finish when they agree at least 80% and score within noise.
2. Tune to humans. Infer each human's goal from what they do in the next few seconds, fit the code mind to it, and then switch the LLM mind off.
3. Change one thing per measurement. Two runs of the same build differ by about as much as most single changes do.

## Comparing humans and AI fairly

- Compare **outcomes**: hit rates by distance, damage per encounter, objective time. A human's aim measured on the server looks worse than it is, because their client shows others about 0.25 s in the past.
- Measure input "feel" with the same window data for both: input changes per minute, aim turn speed, flicks, time with no input, actions per minute by phase.
- The target is humanlike and fun, not stronger. Keep AI below the median human on hit rate and kills per death.
