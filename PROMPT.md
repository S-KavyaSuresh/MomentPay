# Prompt: build MomentPay

Build **MomentPay**, a web app for private group fundraising and gifting, for the PayPal AI Hackathon. Use only free services.

**Stack:** FastAPI backend (single `main.py`), SQLite, a no-build single-page frontend in plain HTML/CSS/JS served by FastAPI, PayPal Sandbox (Orders v2 + Payouts v1 + webhook receiver), Google Gemini free tier for AI, DummyJSON and FakeStore APIs as free product catalogs. Every AI call must have a non-AI fallback so the demo never breaks.

**Accounts:** register/login with name, email, PayPal sandbox email, password. Users are searchable by name or email, like picking a contact in GPay.

**Create a moment:** the organiser searches and selects a recipient from existing accounts (or "it's for me"), chooses type (special occasion or emergency fund), enters occasion, details, relationship context, target amount, group members, and a surprise toggle (occasions only). On "Generate message", the AI writes a warm, personalised fundraising message (max ~110 words) saying any amount is welcome and there are no fixed shares. The organiser can edit it, press "Send to group" (members then see the moment in-app) or "Copy" to paste into WhatsApp and similar apps. Surprise mode: the recipient is excluded from members and can never see or be notified about the moment.

**Contributing:** members give any amount through PayPal Smart Buttons (create order and capture endpoints). Record each contribution. Show a pool bar split into coloured segments per contributor, plus each person's amount and percentage share.

**After the fund is raised:** the organiser closes the fund and sees leftover money and three options.
1. Send the money directly to the recipient with a Payout.
2. Buy something: the organiser describes it and an optional budget. The AI extracts keywords, searches both catalogs, filters by budget, scores by rating, discount and price, then picks the best option and explains the choice with concrete numbers. The organiser can buy the pick or any other result; the purchase creates a PayPal order and is recorded.
3. Ask the recipient (not allowed in surprise mode): the recipient answers "send me the money" or describes the gift. Money answer: the organiser sees it and a send button. Gift answer: the spec pre-fills option 2.

**Leftovers:** after spending, return remaining money to contributors in proportion to what each gave (A gave 600, B gave 400, 100 left: A gets 60, B gets 40). Use integer cents with largest-remainder rounding so shares sum exactly. Preview shares before sending via Payouts.

**Rules:** only the organiser can run post-fund actions; never spend more than the leftover; status flow draft, active, funded, asking, answered, done. Payouts fall back to "simulated" when the sandbox cannot send them (configurable).

**UI:** responsive, accessible, calm and trustworthy, copy in plain verbs, errors that say how to fix them. The memorable element is the proportional contributor pool bar.

**Deliver:** runnable code, requirements.txt, .env.example, README with setup and honest limitations, MIT LICENSE.

## v2 additions (give these to the generator too)
- "Send to group" must create a real group chat: the organiser's message becomes the first chat message, members get it in their moments list, and every PayPal contribution, purchase, payout and refund is posted into the chat automatically and appears live for everyone (polling is fine).
- Add an AI assistant "Pip": 4 message tones with regenerate, a welcome message, per-member personal nudges derived from the who-is-who notes, milestone cheers at 50% and 100%, `@pip` questions answered in chat, AI gift ideas, and reasoning shown for each product pick. Every AI call needs a non-AI fallback.
- Brand voice: warm, poetic, human. Delight-driven microcopy everywhere, e.g. payment success lines like "Your value has safely changed hands.", "The digital currents have carried your treasure through.", "A successful handshake between balances."; soft, comforting errors ("A small knot in the thread: ...") and empty states ("A quiet shore.").
- UI: dark aurora background, glass cards, animated progress ring, hover lifts and shine sweeps, chat bubble pop-ins, confetti on payments, emoji cover art per occasion, rotating loading copy, reduced-motion support.
