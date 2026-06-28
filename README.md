# Pola — Kapruka's Virtual Market

**A 3D market town you walk into and shop by talking to seven shopkeepers, each backed by their own AI persona running real agentic tool calls against the live Kapruka MCP.**

Entry for the **[Kapruka Agent Challenge 2026](https://www.kapruka.com/contactUs/agentChallenge.html)**, a competition for Sri Lankan developers to build the most innovative AI shopping agent on Kapruka's production MCP, judged entirely on experience quality.

- **Live demo:** `https://amirsohil.github.io/pola/`
- **Frontend:** single `index.html` — Three.js + vanilla JS, zero build tooling
- **Backend:** FastAPI on Render (`main.py`) — model fallback chain + hand-rolled MCP client
- **Stack:** Gemini → Cerebras → Groq · `mcp.kapruka.com/mcp` · Python 3.11+

---

## 1. The core bet: don't build a chat widget, build a place

The brief asks for *"a polished, immersive conversation as the main surface — not a tiny widget in a corner."* Most entries will interpret that as a bigger chat box. I created *Pola* to interpret it literally: the chat *is* the destination, but the way you reach it is by walking into a small, warm, hand-built 3D village.

The idea comes from a thought I used to have when I was a kid: what if tiny shopkeepers actually lived inside ecommerce platforms? That image stayed with me. Then I realised Sri Lanka already has a word for that kind of place: *pola*, an open-air marketplace where people browse, discover, and talk before they buy. That's exactly what this is modeled as.

This was the single biggest decision in the project, and everything else flows from it:

- A flat list of categories is forgettable. A market square with seven lit-up stalls, each with its own roof colour, glowing sign, and shopkeeper, is not. The judges open one link and see a living town before a single product card has rendered, which maps directly onto the rubric's two highest-weighted criteria: **Experience & Polish** and **Visual richness**.
- It gives **Personality** a home. A generic chatbot has to manufacture character out of nothing. A market stall comes pre-loaded with one: who's the shopkeeper, what does their corner of the world look like, why would you want to talk to them specifically.
- It turns Kapruka's enormous, genuinely undifferentiated catalog (groceries sitting next to electronics sitting next to baby trolleys) into something a customer can *spatially* understand in two seconds: "gifts are over there, tech is over there." That's catalog navigation solved with geography instead of menus, which is exactly why it scales to **Usefulness**.
- It earns the **Creativity** mark in one screenshot.

The risk is obvious: a 3D scene can look like a tech demo, or perform badly, or distract from the actual shopping. Every decision below is about making sure the 3D layer earns its place, and never gets in the way of the core loop: discovery → cart → checkout.

---

## 2. The world itself

I built this directly in Three.js r128 (loaded from CDN — the whole frontend is a single `index.html`, no bundler, no build step), with a deliberate Ghibli-leaning, toon-shaded, low-poly look rather than photorealism.

- `MeshToonMaterial` with a hand-built 4-step gradient texture (`makeToonGradientTexture`) on almost every mesh, plus a slightly-oversized backface-culled duplicate mesh per shape (`addOutline`) to get the dark ink-outline look of hand-drawn animation. This is a stylistic choice, not a performance shortcut. Outlines and flat shading read as intentional and crafted in a screenshot in a way that default-lit PBR doesn't, and they're far cheaper to render than anything photorealistic on a judge's laptop with no GPU guarantees.
- A gradient sky dome, soft directional light, drifting low-poly clouds, a firefly particle system, and a procedural cherry-blossom petal fall (`buildPetals`) — all built from primitive geometry (icosahedra, cones, planes), not imported assets. Nothing here is a downloaded model. Everything is code, which means nothing to license, nothing to fail to load, and no dependency beyond Three.js.
- Seven pavilions arranged on a lit courtyard, each a cylinder-base-plus-cone-roof hut coloured to its pavilion, with a glowing emissive core, torus trim, finial, and small thematic decorations at its base (an apple for the grocer, a diamond for fashion, a gift box for gifting, a flatscreen for tech, a cross for culture, a block for family, a ring for *The Lounge*). Small details, but they're the difference between "seven identical boxes with labels" and "seven stalls that look like what they sell."
- A central courtyard landmark and a guide character — **Sudu**, modeled entirely in primitives — visually anchoring the "you are in a town" mental model before a word of copy has been read.

### Camera & navigation

`zoomToPavilion()` doesn't cut or teleport. It sets `targetCamPos` / `targetLookAt` and a render-loop lerp eases the camera in over several frames, while a darkening overlay fades up and a `← Back to Courtyard` button appears. That small motion is what turns "this is a webpage with a 3D background" into "I am walking up to a stall" — cheap to implement, disproportionately effective for **Experience & Polish**.

### Failing gracefully

Two defensive decisions that exist because this has to survive being opened cold by a judge on an unknown machine:

- **Mobile gate.** Below 760px, a full-screen card explains plainly that *"this is a 3D market town with a fair bit going on — it's much happier on a bigger screen"* and offers a "Continue anyway" override. I deliberately chose not to silently degrade the scene on phones (which would look broken) and not to hard-block either (which would fail the "if the judges can't open it, it can't win" rule). It tells the truth and gets out of the way.
- **Ambient sound, opt-in and remembered.** A quiet looping market ambience exists, but browser autoplay policy blocks it until a real user gesture — playback only starts on the first actual click (`document.addEventListener('click', startAmbientSound, { once: true })`), and mute preference persists in `localStorage`. No judge gets an unexpected audio blast on load, which is a small thing that nonetheless reads as polish.

---

## 3. Seven pavilions — turning a catalog into characters

The hardest thing about Kapruka's MCP for any agent is that the catalog is enormous and the categories cut across each other in non-obvious ways (liquor and non-alcoholic wine both file under "Grocery"; adult products and intimate pharmacy both file under "Pharmacy"). A single generalist bot would need a huge, brittle system prompt trying to hold the entire taxonomy in its head, or would constantly answer from the wrong part of the catalog.

My solution: split the catalog into seven pavilions that mirror how a Sri Lankan market is actually organised, and give each one its own dedicated persona, narrow taxonomy slice, and full character sheet baked into a system prompt. This lives in `PERSONAS` in `main.py` — one complete shopkeeper per pavilion.

| Pavilion | Shopkeeper | Personality in one line |
|---|---|---|
| 🍎 Fresh Food & Grocery | **Sampath Aiya**, 46 | Lifelong market trader. Warm under a gruff, efficient surface, calls everyone *machan* or *baba* |
| 🎁 Gifts & Celebrations | **Tharushi**, 28 | Professionally excited about every occasion; turns "I forgot until yesterday" into a plan |
| 👶 Kids, Toys & Parents | **Chuti Nanda**, 53 | Grandmotherly, anticipates the unasked safety question (*"that toy has small parts, putha"*) |
| 👗 Fashion & Beauty | **Safi**, 32 | Stylish, blunt, never cruel. Pushes people out of the "safe" choice they're settling for |
| 📱 Electronics & Home | **Kavindu**, 24 | Tech-nerd energy, always asks budget + use case before recommending anything |
| 📚 Culture & Services | **Malsha**, 35 | Measured, literary, distinguishes what you *asked for* from what you might actually *need* |
| 🔞 The Lounge (21+) | **Dev**, 38 | Unflappable, dry, zero judgement — age-gated; frontend enforces 21+ before entry |

This is what makes **Personality** real rather than cosmetic: each persona has a name, an age, a backstory, a speech pattern, and worked examples of their voice baked directly into the system prompt (e.g. Safi: *"No no. You're buying that because it's safe, not because you like it."*). The model isn't asked to "be friendly" in the abstract — it's handed a fully realised character and a believable reason that character would say what it says.

It also directly serves **Usefulness**: each persona's `BEHAVIOUR RULES` are tailored to that aisle's actual stakes. Chuti Nanda is instructed to *always ask the child's age before recommending toys*. Kavindu is told to *always clarify use case before searching*. Safi asks about occasion and recipient first, *because it changes everything*. These aren't generic "be helpful" instructions — they're domain-specific judgment calls about what a good shopkeeper in that specific aisle actually does before recommending anything.

### Cross-referral instead of cross-shopping

No persona is allowed to pretend it can sell everything. Every system prompt includes the full `MARKET_DIRECTORY` and an explicit rule: *when a customer's need fits another shopkeeper better, recommend them warmly and specifically by name.* This was a deliberate choice over having one shopkeeper answer across categories, because it keeps each character's knowledge believable. Sampath Aiya genuinely wouldn't know which perfume to recommend, and having him admit that and point you to Safi is *more* trustworthy than having him bluff it.

### Voice notes, not bullet points

Every persona's prompt includes a hard rule: *no markdown in spoken replies.* The chat bubble is plain text — `**bold**` and `* bullets` render as literal asterisks. So every persona is told to write like a voice note from a market vendor and *not* to re-list products that are already appearing as cards. A wall of markdown bullets reads like a help-desk bot no matter what backstory you give it; a couple of warm spoken sentences next to a row of product photos reads like a person.

---

## 4. Sudu — the guide who doesn't sell anything

Most agent demos put one bot in charge of everything. I deliberately split "figuring out where to go" from "actually buying something," and gave the first job to a separate, much simpler character: **Sudu**, a small white cat who lives in the courtyard and knows every corner of the market, but explicitly does not sell anything herself.

Why this gets its own section rather than being lumped into the pavilion list:

- It solves a real UX problem. A first-time visitor doesn't know which of seven doors to walk through. Asking Sudu "where do I find a birthday gift for my dad?" and getting *"That's Tharushi, at Gifts & Celebrations — go on, she'll sort you out"* is a gentler onramp than guessing.
- Sudu is **intentionally tool-free** (`gemini_tools = None if is_sudu else GEMINI_TOOLS`). She's a lightweight routing layer, not a second full shopping agent. No MCP round-trips means snappy replies, and a clean architectural separation between navigation and commerce that's also easier to debug.
- I did something deliberately low-tech to turn Sudu's free-text replies into tappable navigation: `extractPavilionChips()` scans her reply for keyword signals ("flower," "gift," "tharushi," …) and turns any hit into a chip the user can tap to jump straight there. Rather than forcing structured JSON output (which would fight against her loose, cat-like voice), the client does cheap keyword matching on her natural language. Sudu gets to stay a cat; the UI still gets buttons.
- Cross-pavilion hints from Sudu flow all the way through — when a chip tap fires, it attaches a `hint` string to the next `/api/chat` request, and the receiving shopkeeper's system prompt is silently prepended with that navigation context, so they know why you've just walked in without you having to re-explain.
- This is also the **Creativity** answer: instead of a settings menu or category sidebar, "I don't know where to go" is handled by a character, in the world, in plain English.

---

## 5. System architecture

```
┌──────────────────────────┐        POST /api/chat            ┌────────────────────────────┐
│   index.html (static)    │ ───────────────────────────────▶  │  FastAPI backend (Render)  │
│  Three.js market scene   │                                    │        main.py             │
│  chat / cart / Sudu UI   │ ◀─────────────────────────────────│                            │
└──────────────────────────┘   { text, products, orderSummary } └─────────────┬──────────────┘
                                                                               │
                                                          model fallback chain │
                                                     Gemini → Cerebras → Groq │
                                                                               ▼
                                                              ┌─────────────────────────────┐
                                                              │   mcp.kapruka.com/mcp        │
                                                              │ (search / delivery / orders) │
                                                              └─────────────────────────────┘
```

The frontend never talks to Gemini, Cerebras, Groq, or the Kapruka MCP directly — it only ever calls its own backend's four endpoints: `/api/chat`, `/api/delivery-cities`, `/api/check-delivery`, and `/api/cart-checkout`. Beyond keeping API keys off the browser, this is what allows the backend to run the same MCP session lifecycle, the same product-card curation, and the same anti-hallucination guardrails regardless of which model provider answered a given turn — the frontend genuinely doesn't know or care which one it was.

---

## 6. The backend, in depth

### 6.1 A model fallback chain — because a dead demo scores zero

`/api/chat` tries Gemini first (cheapest-first: `gemini-2.5-flash-lite` → `gemini-2.5-flash` → `gemini-2.0-flash`), then falls back to Cerebras (`gpt-oss-120b`, `zai-glm-4.7`), then to Groq (`llama-3.3-70b-versatile`, `meta-llama/llama-4-scout-17b-16e-instruct`) — three independent providers, six total model endpoints, tried in order within a single request.

The brief is explicit: *"if it isn't live when we judge, it can't be scored."* Every provider here is a free tier, and free tiers rate-limit. A single-provider build is one 429 away from failing live at exactly the wrong moment. The fallback chain means a transient outage degrades the response quality slightly (a different model finishes the same agentic loop) rather than breaking the demo outright. The response includes an honest `_fallback` field for my own debugging — never shown to customers, because a shopkeeper apologising for "switching AI providers" would break character for no benefit.

### 6.2 A hand-rolled MCP client

Rather than using an off-the-shelf MCP client library, I implemented the streamable-HTTP MCP transport directly in `main.py`: `initialize` → capture `Mcp-Session-Id` → `notifications/initialized` → repeatable `tools/call`, with both plain-JSON and Server-Sent-Events response bodies handled (`_mcp_transport` parses `text/event-stream` payloads and pulls the last well-formed JSON-RPC result out of the `data:` lines).

Three reasons this was worth building by hand:

1. **Session correctness under concurrency.** A single chat turn can trigger several parallel tool calls. The lazy session-init path is guarded with an `asyncio.Lock` and a double-check (`if not session.get("id"): async with lock: if not session.get("id"): ...`) so two coroutines racing to initialise at the same moment can't each spin up their own session and silently clobber each other — a bug that's easy to miss with a naive wrapper and hard to notice until it surfaces live.
2. **429 resilience exactly where it matters.** The free MCP tier caps at 60 requests/minute per IP; a busy chat turn can plausibly burst past that. `_mcp_transport` does one short, capped retry (`min(retry_after, 5.0)` seconds) on a 429 before giving up — enough to absorb a momentary burst without making every dropped request fatal.
3. **Self-healing sessions.** If a tool call fails mid-conversation (e.g. a session quietly expired), `_mcp_call_tool` re-initialises a fresh session once and retries automatically, rather than surfacing a raw error to the model and derailing the conversation.

I also built a dedicated `/api/debug-mcp` endpoint that runs the entire lifecycle end-to-end (`initialize` → `notifications/initialized` → `tools/list` → a sample `tools/call`) and returns a plain-English verdict. It exists purely as an operational safety net — if something looks wrong during the judging window, this endpoint answers "is this my bug or Kapruka's MCP?" in one request rather than a guessing game under pressure.

### 6.3 Two agentic loops, because Gemini and the OpenAI-compatible providers don't speak the same dialect

`gemini_loop()` uses Gemini's native `function_declarations` / `functionCall` format; `openai_loop()` (shared by Cerebras and Groq) uses the OpenAI-style `tools[]` / `tool_calls[]` format. Both are full multi-step agentic loops — each iterates up to `MAX_LOOPS = 8` rounds of "model decides to call a tool → tool runs → result goes back → model decides again." A fallback model gets exactly the same live-catalog grounding the primary model does, not a degraded experience.

Within a single round, tool calls run concurrently (`asyncio.gather`) — if the model wants to search two things and check delivery in the same turn, those happen in parallel. For the OpenAI-compatible loop this required care to preserve ordering, since `tool_call_id`s have to pair back to the right result; `asyncio.gather` preserves input order in its output regardless of which call finishes first, so the pairing stays correct without extra bookkeeping.

Both loops write into one shared `tool_history` list, so every downstream step — product extraction, order-summary construction, card curation — works identically regardless of which of the six models answered.

### 6.4 Guardrails — the parts that exist because models lie confidently

This is the part I'd point to if anyone asks "what separates this from a weekend hackathon wrapper?" A raw LLM-plus-tools loop on a real commerce API will, left alone, occasionally hallucinate a category slug, invent a product ID, or surface an adult-section product to a general audience. None of that is acceptable for **Usefulness** or for the brief's "no abuse of the live order tools" rule, so each has a specific, tested fix:

- **Guessed category slugs silently return zero results.** Kapruka's `category` filter is exact-match — a model guessing `"flowers"` instead of the real slug doesn't error, it just returns nothing, then confidently tells the customer the product is unavailable. Prompting alone didn't reliably stop this (logs showed the model guessing exactly the example slugs it was told *not* to use). Fix: `_mcp_call_tool` only forwards a `category` argument if `kapruka_list_categories` has been called and confirmed in the same turn; an unconfirmed guess is silently dropped and logged.
- **Product cards are never built from raw search results.** Every persona's prompt ends with a `SHOW_CARDS: id1, id2, …` instruction — the model must explicitly name, as the very last line of its reply, which product IDs from *this turn's* tool results belong on screen *for this shopkeeper*. The backend strips that line and uses it as an allowlist (`extract_show_cards`). This solves cross-pavilion leakage: a "rice" search legitimately returns rice cookers (Electronics) alongside rice meals (Grocery) — the model decides which belong here, not the raw API response.
- **The Lounge is safety-netted in both directions, independent of model compliance.** A coarse keyword filter (`_is_lounge_product`) runs after curation: outside The Lounge, anything matching liquor/tobacco/adult-product keywords is dropped even if a persona's `SHOW_CARDS` line accidentally included one; *inside* The Lounge, the inverse filter only passes through products that actually match those keywords, so a search that also returns a rose bouquet doesn't card it under a 21+ section. It deliberately accepts occasional over-filtering (a "wine glass" home-decor item) in exchange for never under-filtering — for an age gate, a false negative is always the right side to be on. There's also a specific carve-out for non-alcoholic wine, which is genuinely Sampath Aiya's to sell.
- **Product IDs are never invented.** Dev's persona is explicitly told never to construct or guess a product ID from a name — only to use an ID actually returned by a search *in this same turn*. Combined with the rule that checkout must reuse IDs already established in the conversation, this closes off the most likely path to a broken or fraudulent-looking order.
- **Search results are re-ranked before the model sees them.** Testing showed that Kapruka's API doesn't always surface the most query-relevant results first. `_rerank_search_results` computes an IDF-style weight per query term *from the result set itself* (terms appearing in almost every result get near-zero weight automatically; terms appearing in only a few dominate the ranking), then stable-sorts. No hardcoded stop-word list; it's self-calibrating and works across every pavilion without per-category tuning.
- **Hard cap of 8 cards, enforced twice.** The prompt asks each persona to curate 6–8 cards; the backend additionally hard-caps at 8 regardless of what the model lists, so a model ignoring the curation instruction can't dump twenty cards under one message.

Every one of these guardrails exists because the failure was observed in practice during development, and the fix is in code specifically because the fix in the *prompt* didn't reliably hold. That's the honest story, and the right one for a system about to be judged running end-to-end without supervision.

---

## 7. Closing the loop, twice

The brief's fifth criterion is explicit: *"discovery all the way through to a working checkout."* I built **two distinct, complete checkout paths** — because they serve two genuinely different shopping behaviours:

**1. Conversational checkout**, inside the chat itself. The shopkeeper collects recipient name, phone, delivery address, city, date, and (for Tharushi especially) an optional gift message, entirely through dialogue, then calls `kapruka_create_order` directly. The backend parses the structured JSON response (`response_format: "json"` is requested specifically so the price breakdown comes back as real numbers, not something scraped out of prose), reconstructs a full order summary cross-referencing item names and images from earlier in the conversation, and the frontend renders a **🧾 View Order & Checkout →** button leading to an Order Summary modal — not a bare payment link dropped into a chat bubble. Each shopkeeper's conversational checkout is scoped to their own pavilion, mirroring how a real market stall works: Tharushi handles gifting orders, Kavindu handles electronics, and so on. This is intentional. Cross-pavilion or multi-stall carts are what the cart-drawer path is for.

**2. Cart-drawer checkout**, for the browse-then-decide shopper. Add to cart from any product card or lightbox; the cart drawer has its own quantity controls and running total, and "Checkout at the Till →" opens a delivery-details form with **live city autocomplete** (debounced, hitting `/api/delivery-cities`) and a **live delivery-fee/date preview** (`/api/check-delivery`) that updates the moment both city and date are chosen, before the order is even placed. I kept these three backend endpoints deliberately thin, stateless, and model-free — there's no conversation to extract structure from, so there's no reason to pay for an LLM round-trip just to fill a form. Submitting calls `/api/cart-checkout`, which builds the same order-summary shape the chat flow does, and hands off to the same Order Summary modal — one UI, two ways to reach it.

A few smaller decisions inside this flow worth calling out:

- The form **remembers delivery details** in `localStorage`, updated only on a *successful* order so a failed attempt never overwrites previously good data, with an explicit "Clear saved details" escape hatch. A returning customer shouldn't have to retype their address every visit.
- The date picker's minimum is set to today — *past dates were the single biggest cause of failed orders observed during testing.*
- If `kapruka_create_order` is called with a product ID whose details were never fetched earlier in the conversation (the model jumped straight to checkout on an ID it remembered from several turns back), the backend detects the gap and **backfills it with a fresh `kapruka_get_product` lookup** after the agentic loop completes, so the Order Summary modal never shows a bare product ID where a name and photo should be.
- Both checkout error paths are translated from whatever shape Kapruka returns (`"Error (city_not_deliverable): …"` plain text *or* a JSON error envelope) into one consistent, human-readable message.

---

## 8. The product layer — what "visual" actually means here

Beyond the 3D scene, I built every product touchpoint to satisfy *"show products beautifully — not a wall of text"* literally:

- **Cards, not lists.** Search results render as an image-led card grid under the chat bubble, never as bulleted text — personas are explicitly forbidden from re-listing items in prose because the cards are already doing that job.
- **A lightbox for considering, not just buying.** Clicking a product image opens a full lightbox with a larger photo, name, price, description, and its own "Add to Cart" — for the customer who wants one more look before committing.
- **A real Order Summary, not a payment link.** Recipient, delivery address/city/date, every line item with its photo, gift message and icing text where relevant, and a proper items/delivery/add-ons/grand-total breakdown — *before* the customer is sent to pay. The difference between "the agent placed an order" and "the customer can see exactly what they're about to pay for."
- **Graceful image failure.** Every product image has an inline SVG fallback (`onerror="this.src='data:image/svg+xml,…'"`) so a slow or missing Kapruka CDN image degrades to a small "📦" placeholder instead of a broken-image icon.

---

## 9. How this maps to the rubric

| Criterion | Weight | How I addressed it |
|---|---|---|
| Experience & Polish | 30 pts | Toon-shaded 3D scene, camera-lerp navigation, ambient sound, mobile gate, loaded state indicators, consistent Ghibli visual language end-to-end |
| Visual Richness | 20 pts | Product card grids, image lightbox, Order Summary modal with per-item photos, custom 3D stall decorations per pavilion, firefly/petal particles |
| Personality | 15 pts | Seven fully realised shopkeeper characters with names, ages, backstories, speech patterns, and worked example lines in every system prompt |
| Usefulness | 15 pts | Domain-specific behaviour rules per shopkeeper, Sudu as a routing layer, IDF re-ranking, two complete checkout paths, live delivery preview |
| End-to-end Completeness | 15 pts | Conversational checkout + cart-drawer checkout, both flowing into the same Order Summary modal with working Kapruka pay links |
| Creativity | 5 pts | The market-as-place metaphor; Sudu as a cat guide you ask in plain English instead of using a menu |
| **Bonus — Multi-item carts** | ✅ | Cart drawer with quantity controls, running total, and full cart-level checkout |
| **Bonus — Delivery-date constraints** | ✅ | Live `kapruka_check_delivery` preview in the cart form; "next available date" surfaced before the order is placed |
| **Bonus — Gift messaging** | ✅ | Tharushi specifically prompts for recipient name and gift message; `icing_text` flows through to Order Summary |
| **Bonus — Tanglish / Sinhala** | ❌ | See Honest Gaps below |

---

## 10. Honest gaps and what they cost

I'm not going to pretend everything is finished — it's more useful to be clear about what was prioritised and why.

- **No Sinhala or Tanglish support yet.** The brief calls Sinhala out as a near-guaranteed differentiator ("almost no one will attempt it"). Every persona is currently English-only; the underlying models are multilingual and would very likely respond reasonably if addressed in either, but that's an untested assumption, not a claimed feature. Given more time this is the single highest-leverage bonus item — adding language-handling notes to each persona's prompt and testing the `SHOW_CARDS` pipeline against non-Latin script queries is the complete scope.
- **Structured cross-stall referral banners aren't live yet.** I built a full UI for them (`renderCrossStallBanner`), and Sudu's keyword chips *are* live, and navigation hints now flow through to receiving shopkeepers. But the structured `cross_stall_suggestions` signal isn't currently emitted by the backend — shopkeeper-to-shopkeeper referrals happen conversationally ("go see Tharushi for that"), which satisfies the underlying need, just without the one-tap banner UI. This is a backend-only addition (a classifier step after the agentic loop) rather than a frontend rebuild.
- **Delivery-date constraints are plumbed, not proactively surfaced.** `kapruka_check_delivery` and the live cart-drawer preview both surface real availability and cost. But no persona currently goes out of its way to *proactively* warn about tight windows ("that won't make it by tomorrow — here's the earliest it can") unless asked. That's a prompt addition, not an architecture change.

None of these are structural weaknesses. They're the right calls for where time was best spent — getting the core discovery-to-checkout loop airtight — and each has a clear, scoped next step.

---

## 11. Tech stack

| Layer | Choice |
|---|---|
| 3D scene | Three.js r128 (CDN, no bundler) |
| Frontend | Vanilla JS + hand-written CSS, single `index.html` |
| Backend | FastAPI + httpx (async), deployed on Render |
| Primary model | Gemini (`gemini-2.5-flash-lite` → `gemini-2.5-flash` → `gemini-2.0-flash`) |
| Fallback chain | Cerebras (`gpt-oss-120b`, `zai-glm-4.7`) → Groq (`llama-3.3-70b`, `llama-4-scout`) |
| Commerce | Kapruka MCP (`mcp.kapruka.com/mcp`) — search, categories, delivery check, guest checkout, order tracking |
