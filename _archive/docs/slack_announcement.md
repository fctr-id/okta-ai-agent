# Slack Announcement - ReAct Agent for Okta

## Post #1: Main Announcement (Thread Starter)

Hello All,

I know a couple of you have tried Tako AI (AI Agent for Okta) in the past and had multiple opinions. We completely rebuilt it with the "ReAct (reasoning and acting)" AI pattern.

Instead of multiple agents coordinating, you now have ONE agent that **acts like a person** probing your Okta APIs - reads docs, makes calls, sees results, debugs failures, and iterates until it gets it right.

Here are the major benefits:

- **One agent that thinks like an engineer**: Reads docs, writes code, tests it, sees results, and improves. When it fails, it debugs itself like you would. No coordination issues.
- **Works with smaller models**: gemini-2.0-flash, claude-3.5-haiku, or gpt-5-mini (but really slow, use gpt-4.1) instead of expensive mainstream models

The fun part of this is, if this pattern works for okta, this can be used for other product's APIs like let's say Jamf.

Super easy to test - clone repo, set env variables, and you're done. Video attached - would love feedback from anyone willing to test it!



---

## Post #2: Setup Instructions (Reply in Thread)

**Prerequisites:**
- Python 3.9+
- Okta read-only admin API key and Okta environment access
- API key from one of these: Google Gemini, Anthropic Claude, or OpenAI

**What to do:**

1. Clone the GitHub repo: `git clone -b feature/one-react-agent https://github.com/fctr-id/okta-ai-agent`
2. Set up Python virtual environment and install requirements
3. Copy `.env.sample` to `.env` and configure (OKTA_ORGURL, OKTA_API_TOKEN, and your LLM API key)
4. Execute the test script: `python scripts/okta_react_agent_test.py "your query here"`
5. Run the generated Python script to get CSV results in `src/core/data/`

**Example query to try:**
"List users who logged in to okta in the last 10 days and fetch all their assigned applications and group memberships"

Full installation guide: https://github.com/fctr-id/okta-ai-agent/wiki/Installation-%E2%80%90-ReAct-Agent-Patterm

I'm here or reach out to dan@fctr.io if you need more help!

---

## Alternative Post #1 (Even Shorter)

Rebuilt my Okta AI agent - single ReAct agent that reads docs, writes code, tests itself. Works with fast/cheap models (gemini-flash, claude-haiku).

Ask Okta questions → get CSV results. If successful, architecture can expand to JAMF APIs and others.

CLI-only. Setup in thread. Feedback welcome!

---

## Notes on Tone & Positioning

**What works well for tech communities:**
✅ Focus on technical improvements (ReAct architecture, model efficiency)
✅ Honest about current state (CLI only, looking for feedback)
✅ Specific examples they can relate to
✅ Acknowledge previous testers
✅ Clear, practical value proposition

**What to avoid:**
❌ Marketing language ("revolutionary", "game-changing")
❌ Overselling capabilities
❌ Pressure to try it ("you MUST check this out")
❌ Vague benefits without specifics
❌ Hiding limitations

**Slack Community Best Practices:**
- Lead with value, not features
- Show respect for their time (5 minute setup, not "quick and easy")
- Be specific about what you're testing
- Make it easy to ignore if not interested
- Provide escape hatches (GitHub issues, DMs)
