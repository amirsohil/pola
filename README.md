# Pola — Kapruka's Virtual Market

A 3D isometric virtual marketplace built on Kapruka's public MCP API.
Eight shopkeeper personas, each with a distinct personality, powered by Groq.
Kalu the guide cat navigates you between stalls. Cross-stall recommendations
let one shopkeeper hand you off to another with context intact.

---

## Project structure

```
pola/
  index.html      — Frontend (Three.js 3D world, chat panels, Kalu)
  backend.py      — FastAPI backend (MCP agentic loop, Groq, cross-stall)
  requirements.txt
  .env            — your secrets (never commit this)
```

---

## Local setup

### 1. Create a `.env` file

```
GROQ_API_KEY=your_groq_api_key_here
```

Get a free key at https://console.groq.com

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the backend

```bash
python backend.py
```

Backend runs at `http://localhost:8000`.
Check it's alive: `http://localhost:8000/health`

### 4. Open the frontend

Open `index.html` directly in your browser, or serve it locally:

```bash
npx serve .
```

---

## How the agent works

Every message from a stall chat goes to `POST /chat` with:
- `stall_id` — which shopkeeper is active
- `message` — user's message
- `history` — last 8 turns of conversation
- `cart_context` — items already in cart
- `cross_stall_hint` — optional context from another shopkeeper

The backend runs an **agentic loop**:
1. Groq receives the persona system prompt + all 6 MCP tool definitions
2. Groq decides which tools to call (search, product detail, delivery check, etc.)
3. Backend executes those calls against `mcp.kapruka.com`
4. Tool results are fed back into Groq
5. Loop repeats up to 4 times until Groq returns a final response
6. Backend parses `<products>`, `<cross_stall>` blocks from the response

Kalu calls `POST /kalu` — simpler, no MCP tools, just navigation.

---

## Deployment

### Backend — Railway or Render (free tier)

```bash
# Railway
railway init
railway up

# Render — connect GitHub repo, set GROQ_API_KEY env var
```

Set `BACKEND_URL` in `index.html` to your deployed backend URL.

### Frontend — Vercel or Netlify (free)

Drop `index.html` into a new Vercel project. No build step needed.

### Lock down CORS

In `backend.py`, replace `allow_origins=["*"]` with your Vercel URL:

```python
allow_origins=["https://your-pola.vercel.app"]
```

---

## Stalls

| Shopkeeper    | Stall      | Personality                              |
|---------------|------------|------------------------------------------|
| Aunty Manel   | Bakery     | Warm, emotionally manipulative, calls everyone darling |
| Ruwani        | Florist    | Poetic, reads too much into flower choices |
| Sampath       | Grocery    | Blunt, fast, minimal small talk          |
| Dilki         | Gifts      | Infectiously enthusiastic, always right  |
| Nadee         | Beauty     | Direct, zero filter, genuinely helpful   |
| Kasun         | Electronics| Brilliant, slightly awkward, over-explains |
| Chuti Nanda   | Kids/Baby  | Boisterous grandmother energy            |
| Dr. Rohan     | Pharmacy   | Calm, measured, trustworthy              |

Kalu the guide cat lives in the courtyard and navigates between all stalls.

---

## Kapruka MCP tools used

- `kapruka_search_products` — keyword search with category, price, stock filters
- `kapruka_get_product` — full product detail by ID
- `kapruka_list_categories` — all categories
- `kapruka_check_delivery` — delivery availability + cost for a city and date
- `kapruka_list_delivery_cities` — validate city names before delivery check
- `kapruka_track_order` — order tracking by order number

---

## Cloudflare Worker (API key gate — Phase 2)

To avoid exposing the Groq key in the frontend, route calls through a
Cloudflare Worker that injects the key server-side.
The `GROQ_KEY` constant in `index.html` is intentionally a placeholder —
swap it for your Worker URL when ready.
