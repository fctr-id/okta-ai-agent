# Tako AI v3.0: Harness the Vibe

Tako evolved quickly over the last few releases, but by v2.2 the foundation was finally in place.

v3.0 builds on that base with smarter routing, stronger follow-up conversations, and a cleaner experience for longer investigations.

It is the biggest step forward since v2.0, moving Tako from a one-shot query tool toward a true investigation partner.

If you want a quick look at v3.0 before diving into the details, here is a short demo:

https://youtu.be/QZ13W6P04uQ

---

## What's New in v3.0?

### 1. Smarter Routing from Question to Answer

Earlier versions followed a more fixed path from question to answer. In v3.0, Tako does a better job deciding how to answer each question based on what it already knows and what it still needs to check.

That means it can:

- use synced tenant data when that is enough
- bring in live information when a fresh check is needed
- use specialized workflows for more targeted questions
- build on earlier results before moving forward
- bring everything together into a clear final answer

Instead of treating every request the same way, Tako can now take the most sensible path for the situation. The result is a smoother experience, fewer unnecessary steps, and better performance as questions become more complex.

### 2. Multi-Turn Conversation That Actually Remembers

This is one of the most important changes in the release. Tako can now hold onto the right context from earlier turns, so follow-up questions feel like part of the same investigation instead of a fresh start every time.

So you can do this:

```text
Show me all active admins with no MFA enrolled.
Of those, which ones also have Slack assigned?
Now narrow that to users who have not logged in for 30 days.
```

Tako can stay focused on the earlier result instead of making you restate the whole problem.

That is a much more natural way to work. Real identity investigations are iterative. You start broad, see something interesting, then narrow, compare, and ask the next question. v3.0 is built for that workflow.

### 3. Better Reasoning on Follow-Ups

We also improved how Tako handles the next question after an answer.

Follow-up questions are not always about finding more information. Often the real job is to interpret what was already found, compare it, narrow it down, and decide what matters next.

That makes Tako more useful once an investigation is already underway.

### 4. A Better Experience for Longer Investigations

We also reworked the chat experience to better support longer, more detailed investigations.

The interface is cleaner, tables and formatted answers are easier to read, and progress is easier to follow during longer-running tasks.

If you spend time investigating app assignments, admin access, MFA gaps, or stale identities, this release should feel clearer, easier to follow, and less cramped.

---

## What Changed Behind the Scenes

v3.0 is not just a UI release, and it is not just better memory in a chat box.

We made substantial improvements to how Tako chooses its path, carries context forward, and turns intermediate work into a clear final answer. We also improved reliability around follow-up behavior, session handling, and sync-related cleanup.

The result is a system that stays more consistent when a simple question turns into a longer investigation.

---

## Why This Release Matters

From a product perspective, v3.0 matters because it is the first release built on top of a foundation that already felt stable.

By the end of the v2.2 cycle, we were no longer reworking the core flow. That gave us room to invest in bigger improvements on top of it:

- smarter routing from question to answer
- better continuity across follow-up questions
- stronger reasoning over earlier results
- a better interface for longer investigations

Most Okta work is not one question followed by one answer. It is more like this:

You start with a broad query. You spot something unexpected. You ask a follow-up. Then another. You compare groups, app assignments, recent activity, or policy impact. Somewhere in the middle, context becomes the whole challenge.

That is exactly where we wanted Tako to improve. v3.0 is about making the product more useful once a real investigation is underway, not just better at answering a single prompt.

v2.0 gave us the Swarm. v2.1 expanded where people could use Tako. v2.2 settled the base. v3.0 starts the next phase.

---

## What This Sets Up Next

We have been careful not to rush write operations, and that has not changed.

But v3.0 gives us a stronger base for deeper analysis, safer approval-driven workflows, and more reliable human-in-the-loop actions in future releases. Before a product can take action safely, it has to keep context, intent, and evidence straight across a longer workflow. This release is a major step in that direction.

---

## Get Started

If you are already running Tako, pull the latest release and restart with v3.0-beta. Setup still takes about 10 minutes if you are starting fresh.

You will need:

- Docker or Python 3.11+
- Okta authentication via OAuth 2.0 or API token
- an LLM provider key

Want to try a good v3-style workflow right away? Start with a broad identity question, then keep drilling in with follow-ups instead of rewriting the whole prompt each time.

- GitHub: https://github.com/fctr-id/okta-ai-agent
- Full setup docs and changelog are in the GitHub repo

Questions or ideas? Open an issue on GitHub or email us at support@fctr.io.

Thanks to everyone testing Tako, pushing it into real workflows, and showing us where the rough edges were. That feedback shaped this release.

Dan & the Fctr team