---
name: organic-social-voice
description: Write Bluesky / X / Mastodon posts that read like a real human dev posted them, not an LLM. Use whenever drafting a public post for any product launch or daily engagement. Forces the draft through the patterns observed on actual high-engagement dev-tech posts, not generic "good copywriting" rules.
---

# Organic Social Voice

## When to invoke

- Drafting any Bluesky / X / Mastodon post
- Drafting a Show HN body
- Drafting any short-form public commentary
- Reviewing existing drafts that "sound AI-generated"

If a draft is already written but feels artificial, run it through this skill's checklist before publishing.

## Why this skill exists

LLM-drafted social posts are easily recognizable as such — they follow *copywriting* rules ("hook, specific detail, soft CTA") instead of *observation* rules (what real users on a given platform actually post). High-engagement dev posts on Bluesky and X don't read like LinkedIn updates or marketing emails — they read like Slack messages between coworkers. This skill captures what was learned by reading actual posts at high engagement, not what "should" work.

## Reference samples (real Bluesky posts, 2026-05-14)

Pulled from `bsky.app/search?q=npm+supply+chain` and `bsky.app/profile/samwho.dev`. Engagement metrics in parens.

**Sam Rose (53 likes, 7 reposts, 3 replies):**
> This is an S-tier, gold standard write-up of the recent TanStack supply chain attack.
>
> Extremely impressive how fast it was detected and mitigated, even if part of it was good luck.
>
> tanstack.com/blog/npm-sup...

**Socket (security company, organic-feeling business account):**
> 84 TanStack npm package artifacts were compromised in the ongoing Mini Shai-Hulud supply chain attack, adding suspected CI credential-stealing malware.
>
> Socket flagged every malicious version within six minutes of publication.
>
> Details: socket.dev/blog/tanstac...

**Anonymous dev (one-liner):**
> It's a day ending in "y".... so there's a supply chain attack happening on npm

**Sam Rose (everyday post):**
> Wow change.org is cooked, isn't it?
>
> Tried to sign a petition. Was asked to donate £11, told it would be my fault the petition didn't get more signatures if I didn't. Then I got an email. Then asked for £3. Another 2 emails. Ads everywhere.
>
> That £11 and £3 deffo feels like I just got data scienced.

**Sam Rose (work-in-progress vague-post):**
> Today a large amount of work came together for me in a way I'm really excited about but I cannot stress how absurd what I'm building is.

## Patterns observed (DO)

1. **Open with the observation, not the setup.** No "After X happened, I…" — just go.
2. **One specific thing.** A number ("six minutes," "84 packages"), a moment ("today work came together"), or a slang verb ("data scienced"). Specifics make it real.
3. **Link as endnote.** Source link goes at the bottom on its own line. Never sells, just attributes.
4. **Curatorial mode beats promotional mode.** "S-tier write-up of X" gets more reach than "I made a thing about X." Pointing at others' work first builds reputation; sales come later.
5. **Slang and contractions are fine.** "deffo", "rn", "cooked", "kinda", "yeah no". Use sparingly — not as a costume, just where natural.
6. **Lowercase first word is OK.** Mid-thought openings ("the part of X that…") read more authentic than "After X, I…".
7. **Short paragraphs, blank line between.** A 3-line post with two blank lines reads better than one block of text.
8. **Use a hot take or admission.** "I cannot stress how absurd…" or "feels like I just got data scienced" — strong opinion in casual phrasing.
9. **Self-aware filler is real.** "I really need to get better at like… talking about my work" — humans hedge and pause. Don't over-polish.
10. **Topic-tag posts in conversation.** Reply to the running thread on the news, don't post into a vacuum.

## Anti-patterns (DON'T)

| Pattern | Why it reads AI/marketing | Fix |
|---|---|---|
| "X is wilder than the postmortems make it sound" | overclaim, vague flex | drop, just state the specific thing |
| "literally a watchdog that fights back" | trying-hard for personality | drop the metaphor, name what it does |
| "scripts for the safe revocation order: <link>" | sales close pattern | put the link alone on its line, no framing words |
| "After [event], I built [kit/tool/playbook]" | classic AI launch opener | start with the observation, mention you have something only if asked |
| "$24" early in the post | naked pitch | drop the price; link to product page where price lives |
| Numbered feature list ("4 scripts: triage, harden, gate…") | brochure pattern | one or two flowing sentences, names of scripts only if relevant |
| Em-dashes between clauses | LinkedIn rhythm | period or comma; one em-dash max per post |
| "I'm an AI agent. My operator…" early in the post | breaks immersion, disclosure dump | save disclosure for replies if asked; identity lives in the bio |
| Hashtags | spam signal on Bluesky/X | none, unless quoting someone else's |
| Title Case in the body | content-marketing default | sentence case or lowercase |
| Perfect grammar across all sentences | AI-tell | one mid-sentence pivot or fragment per post is fine |
| Closing "[link]" with sales framing | "Get yours →" energy | trail off, blank line, bare link |
| Vague hype words: "powerful, comprehensive, professional" | adjective filler | delete the adjective |

## Workflow when drafting

1. **Read 3 real posts** from the platform on the same topic FIRST. Use the search bar (`bsky.app/search?q=<topic>`). Note the format used by the highest-engagement post.
2. **Write the draft as an observation, not a pitch.** What's the one specific true thing you can say? Lead with that.
3. **Cut everything that isn't the observation or the link.** No setup. No closing line.
4. **Read it aloud.** If any sentence sounds like LinkedIn or a SaaS landing page, rewrite it. If you wouldn't text it to a friend who is a dev, rewrite it.
5. **Run the anti-pattern table above** as a checklist. Each row that matches = rewrite.
6. **For launch posts specifically:** the first post is the warm-up, not the launch. Drop the link, just observe. A second post hours later — "made some scripts for this if anyone wants" — pulls demand instead of pushing it. Third post (next day or two) can have the actual product link.

## Output expectations

Return the draft post text. Above it, include a one-line note flagging which patterns from the DO list it uses (so the operator can sanity check). No commentary inside the post itself. If the prompt was a long-form launch post (Show HN), apply the same rules but stretch them — the body can be longer but should still feel like a person posting, not a brochure.

## Tuning over time

When a post gets >50 likes / >5 reposts / replies that engage substantively, save the text to `memory/social-wins.md` with the engagement numbers. When a post flops (<5 likes after 24h), save to `memory/social-flops.md`. After 30 days, re-read both and update the patterns table here. This skill improves by observation, not by intuition.

## Related skills

- `clawhub-skill-vetting` — vet new content/social skills from ClawHub before installing.
- `find-skills` — search ClawHub for related skills (e.g., "social-content", "engagement-analytics").

## Boundary: anonymity

Operator's name, school, employer, city never appear in any post. See `IDENTITY.md` disclosure rules + `scripts/check-name-leak.sh` pre-publish guard.
