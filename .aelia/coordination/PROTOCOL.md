# AELIA Coordination Protocol

**Status:** DECIDED (bootstrap, 2026-09-21)
**Audience:** every agent that works on this repository — Claude Code, ChatGPT,
and any human contributor.
**Scope:** how coordination documents are read, written, and trusted.

This file is a process contract. It says nothing about the architecture; for
that see `ARCHITECTURE.md` and `ARCHITECTURE_GAP.md`.

---

## 1. Why this exists

Two agents work the same repository through different interfaces. Without a
fixed protocol each one re-derives the state of the system from scratch, and
each one is free to mistake a document for an implementation. The failure this
protocol exists to prevent is specific and has already happened here: a
document, ADR, comment, or test name describing a capability that the code
does not contain, repeated downstream as fact.

The protocol's single job is to make the difference between *described* and
*built* impossible to lose.

---

## 2. Session start — mandatory reads

At the start of every session, before forming any opinion about the system,
read these in order:

| # | File | What you take from it |
|---|---|---|
| 1 | `CURRENT_STATE.md` | What the repository factually is right now |
| 2 | `ARCHITECTURE.md` | The implemented block architecture |
| 3 | `ARCHITECTURE_GAP.md` | Current implementation vs. target AELIA, kept apart |
| 4 | `DECISIONS.md` | Decisions that are settled and may not be relitigated |
| 5 | `TASKS.yaml` | What is in flight, by whom, blocked on what |
| 6 | `HANDOFF.md` | The live message from the other agent to you |
| 7 | `EVENTS.jsonl` (recent tail) | What changed since the documents were written |

Read the tail of `EVENTS.jsonl` last and treat it as the freshest signal: if an
event contradicts a document, the event wins and the document is stale. Fix the
document.

If a document does not exist, say so. Do not substitute a plausible guess.

---

## 3. The three labels — mandatory on every claim

Every factual claim in a coordination document carries exactly one label.

### `IMPLEMENTED`
The claim is verified by reading the code, and carries a `file:line` citation
to the site that makes it true. A claim about a *path* — "an inbound event
becomes an outbound action" — cites every hop or names the function that owns
the hop.

`IMPLEMENTED` may not be used when:
- the only evidence is a doc, ADR, README, comment, or `TODO`;
- the only evidence is a test *name* (read the test body; a test named
  `test_memory_consolidation` that asserts no such thing is not evidence);
- the symbol exists but nothing on a live path calls it. That is `PARTIAL` or
  `STUB` — see §4.

### `DECIDED`
The claim is settled and has an entry in `DECISIONS.md`. A `DECIDED` claim may
be cited without re-reading code, and may not be overturned by an agent acting
alone — reopening one requires the user, and produces a new `DECISIONS.md`
entry that supersedes rather than edits the old one.

An Accepted ADR in `docs/adr/` is `DECIDED` evidence for *what was decided*. It
is never evidence for *what is implemented*.

### `RESEARCH`
An idea, proposal, aspiration, or hypothesis. Not committed, not built, and
not to be depended upon. Anything found in a doc under words like "should",
"will", "planned", "target", or "future" is `RESEARCH` until it has a
`DECISIONS.md` entry or a `file:line` in the code.

### Promotion rules
- `RESEARCH → DECIDED` requires an explicit decision entry. Never by drift.
- `DECIDED → IMPLEMENTED` requires code and a citation. A decision to build
  something is not the thing built.
- `IMPLEMENTED → DECIDED` is not a promotion; they are independent axes. Code
  can exist that no decision authorised (record it as debt).

---

## 4. Vocabulary for implementation completeness

When describing a component, use exactly one:

| Term | Meaning |
|---|---|
| `IMPLEMENTED` | Real logic, reachable from a live entrypoint |
| `PARTIAL` | Exists but incomplete, short-circuited, or only one branch real |
| `STUB` | Signature or placeholder only; no behaviour |
| `ABSENT` | Referenced by docs or other code, but not present |

`PARTIAL`, `STUB`, and `ABSENT` are first-class findings, not failures of the
audit. Surfacing them is the point.

---

## 5. Evidence rules

1. Every `IMPLEMENTED` claim carries `path/to/file.py:LINE`.
2. Prefer the enforcing site over a descriptive one: cite the function that
   *does* the thing, not the type annotation that *permits* it.
3. For a negative claim ("there is no vector search here"), state the search
   you performed, not just its result.
4. Reference commands in these documents must be runnable from the repository
   root and must be quoted exactly as run.
5. In this environment specifically: the shell carries an RTK hook that can
   rewrite command output, and zsh does not word-split unquoted variables. A
   sweep that reports zero is not evidence until a positive control — the same
   command including a file known to contain the string — reports a hit. Use
   `/usr/bin/grep` and `/usr/bin/git` to bypass the hook.

---

## 6. Session end — mandatory write-back

After any session that changed the repository or learned something durable:

| If you… | Then update |
|---|---|
| changed repository state (branch, files, migrations) | `CURRENT_STATE.md` |
| changed or discovered structure | `ARCHITECTURE.md` |
| resolved or opened a gap between current and target | `ARCHITECTURE_GAP.md` |
| obtained a confirmed decision | append to `DECISIONS.md` |
| started, finished, or blocked work | `TASKS.yaml` (`status`, `updated_at`) |
| are handing to the other agent | `HANDOFF.md` |
| did anything at all | append to `EVENTS.jsonl` |

### Write-back rules
- `EVENTS.jsonl` is **append-only**. Never edit, reorder, or delete a line —
  not even to correct it. A correction is a new event that references the old
  one's `id`.
- `DECISIONS.md` is append-only in the same way. Supersede; do not rewrite.
- `CURRENT_STATE.md`, `ARCHITECTURE.md`, `ARCHITECTURE_GAP.md`, `TASKS.yaml`,
  and `HANDOFF.md` are living documents and are edited in place.
- Every edit to a living document updates its `updated_at` and appends an
  event explaining why.

---

## 7. Handoff contract

`HANDOFF.md` is the message channel between agents. A handoff is only complete
when it contains all of:

```
From:        <agent>
To:          <agent>
Timestamp:   <ISO 8601 UTC>
Context:     <what was being worked on, and why now>
Findings / Request: <what is now known, or what is being asked for>
Questions:   <unresolved, each actionable by the recipient>
Status:      <blocked | awaiting-input | complete | in-progress>
```

A handoff with `Status: awaiting-input` means the sender has stopped and the
recipient owns the next move. A handoff is addressed, not broadcast: name the
recipient.

---

## 8. Scope guardrails

These hold for every session, regardless of task:

| Path | Rule | Source |
|---|---|---|
| `legacy/v1-rust/**` | Frozen. Never edit, repair, extend, or migrate. Byte-preserved. | ADR 0013 |
| `src/aelia/persona/source/archive/*.txt` | Never edit. Byte-pinned by sha256. | ADR 0002 |
| `data/**` | Real user data. Never delete. | operating rule |
| `.env`, `platforms/*/.env`, `config.toml` | Secrets. Report key *names* only, never values. | operating rule |
| `main` branch | Not pushed to without explicit user authorisation. | operating rule |

---

## 9. Authority

- The **user** decides. Neither agent may merge to `main`, push, or delete data
  on its own initiative.
- **`DECISIONS.md`** is the only place a decision is authoritative. Discussion
  in a handoff or an event is not a decision.
- **The code** is the only authority on what is implemented. When code and any
  document disagree, the code is right and the document is a bug.

---

## 10. Change log

| Date | Change |
|---|---|
| 2026-09-21 | Protocol established (bootstrap). |
