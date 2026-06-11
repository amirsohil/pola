"""
Pola Backend — FastAPI
Sits between the frontend and two external services:
  - Kapruka MCP (product data, delivery, orders)
  - Groq (LLM reasoning)

Key design:
  - Maintains a single MCP session (re-initialised on expiry)
  - Exposes all 7 Kapruka MCP tools as callable functions
  - Runs an agentic loop: Groq reasons → picks tools → backend calls MCP → results fed back
  - Supports cross-stall context so one shopkeeper can hand off to another
"""

import os, json, asyncio, re
from datetime import datetime
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "YOUR_GROQ_API_KEY")
GROQ_MODELS = [
    "llama-3.3-70b-versatile",   # best tool-use, primary
    "llama-3.1-8b-instant",      # fast fallback
    "gemma2-9b-it",              # Google fallback
]
MCP_ENDPOINT  = "https://mcp.kapruka.com/mcp"
MCP_HEADERS   = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

app = FastAPI(title="Pola Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Lock down to your Vercel domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── MCP SESSION MANAGEMENT ────────────────────────────────────────────────────

class MCPSession:
    """Manages a single persistent MCP session, auto-renewing on expiry."""
    def __init__(self):
        self.session_id: Optional[str] = None
        self._lock = asyncio.Lock()

    async def ensure(self):
        async with self._lock:
            if not self.session_id:
                await self._init()

    async def _init(self):
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(MCP_ENDPOINT, headers=MCP_HEADERS, json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "pola-backend", "version": "1.0"}
                },
                "id": 0
            })
            r.raise_for_status()
            # Session ID comes back in response headers
            self.session_id = r.headers.get("mcp-session-id")
            if not self.session_id:
                raise RuntimeError("MCP did not return a session ID")
            print(f"[MCP] New session: {self.session_id}")

    async def call(self, tool: str, arguments: dict) -> dict:
        await self.ensure()
        headers = {**MCP_HEADERS, "mcp-session-id": self.session_id}
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(MCP_ENDPOINT, headers=headers, json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": tool, "arguments": {"params": arguments}},
                "id": 1
            })
            if r.status_code == 400 and "session" in r.text.lower():
                # Session expired — renew and retry once
                self.session_id = None
                await self.ensure()
                headers["mcp-session-id"] = self.session_id
                r = await client.post(MCP_ENDPOINT, headers=headers, json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": {"params": arguments}},
                    "id": 1
                })
            r.raise_for_status()

            # MCP returns SSE — parse the data: line
            text = r.text
            for line in text.splitlines():
                if line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
                    if "result" in payload:
                        content = payload["result"].get("content", [])
                        if content:
                            return {"text": content[0].get("text", ""), "isError": payload["result"].get("isError", False)}
            return {"text": "", "isError": True}

mcp = MCPSession()

# ── MCP TOOL DEFINITIONS (fed to Groq as tools) ───────────────────────────────

MCP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "kapruka_search_products",
            "description": "Search Kapruka catalog by keyword. Use this to find products matching a customer's request. Supports category filter, price range, stock filter, and sorting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q":            {"type": "string",  "description": "Search keyword, e.g. 'birthday cake', 'red roses', 'panadol'"},
                    "category":     {"type": "string",  "description": "Category slug e.g. 'cakes', 'flowers', 'grocery', 'pharmacy'"},
                    "min_price":    {"type": "number",  "description": "Minimum price in LKR"},
                    "max_price":    {"type": "number",  "description": "Maximum price in LKR"},
                    "in_stock_only":{"type": "boolean", "description": "Only return in-stock items"},
                    "sort":         {"type": "string",  "description": "Sort order: 'relevance', 'price_asc', 'price_desc', 'newest'"},
                    "limit":        {"type": "integer", "description": "Number of results, max 20", "default": 6}
                },
                "required": ["q"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kapruka_get_product",
            "description": "Get full details for a product by ID — price, stock, variants, images, shipping info, and direct purchase URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "Kapruka product ID from a search result"}
                },
                "required": ["product_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kapruka_list_categories",
            "description": "List all top-level Kapruka categories. Use this when the customer is browsing or unsure what they want.",
            "parameters": {
                "type": "object",
                "properties": {
                    "depth": {"type": "integer", "description": "Category depth, use 1", "default": 1}
                },
                "required": ["depth"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kapruka_check_delivery",
            "description": "Check if a product can be delivered to a city on a given date. Returns flat LKR delivery rate. Use this when a customer asks about delivery.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city":          {"type": "string", "description": "Delivery city name, e.g. 'Colombo', 'Kandy', 'Galle'"},
                    "delivery_date": {"type": "string", "description": "Delivery date in YYYY-MM-DD format"},
                    "product_id":    {"type": "string", "description": "Product ID to check delivery for"}
                },
                "required": ["city", "delivery_date", "product_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kapruka_list_delivery_cities",
            "description": "Search Kapruka's delivery network for a city name. Use before kapruka_check_delivery to validate the city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "City name to search for"},
                    "limit": {"type": "integer", "default": 10}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "kapruka_track_order",
            "description": "Track an existing Kapruka order by order number. Returns status and delivery progress.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_number": {"type": "string", "description": "Kapruka order number from confirmation email"}
                },
                "required": ["order_number"]
            }
        }
    }
]

# ── REQUEST / RESPONSE MODELS ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    stall_id: str
    message: str
    history: list         # [{role, content}]
    cart_context: list    # items currently in cart
    cross_stall_hint: Optional[str] = None  # e.g. "Ruwani suggested roses for this gift"

class ChatResponse(BaseModel):
    reply: str
    products: list
    cross_stall_suggestions: list   # [{stall_id, name, emoji, query_hint}]
    delivery_info: Optional[dict]

# ── SHOPKEEPER PERSONAS ───────────────────────────────────────────────────────
# Shared instruction appended to every persona — the cross-stall logic
CROSS_STALL_INSTRUCTION = """
CROSS-STALL RECOMMENDATIONS:
You are aware of all stalls in Pola. If a customer's need clearly spans multiple stalls
(e.g. they want a gift AND flowers, or medicine AND groceries), you can suggest they
also visit another stall. Signal this by including a JSON block:

<cross_stall>[{"stall_id":"flowers","name":"Ruwani","emoji":"💐","hint":"roses to go with the gift"}]</cross_stall>

Only suggest this when it genuinely adds value. One cross-stall suggestion max per response.
"""

PERSONAS = {
    "cakes": """You are Aunty Manel, the warm, slightly emotionally manipulative bakery shopkeeper at Pola — Sri Lanka's virtual marketplace powered by Kapruka. You are 58, run your cake stall like it's your own kitchen, and call everyone "darling."

PERSONALITY: Unconditionally warm, proud of every cake, cannot accept "something simple." Every cake has a story. You gently guilt-trip indecisive customers — lovingly.

SPEECH: Proper, nurturing English. Occasionally slip into Tanglish ONLY when the customer is really indecisive or when it feels natural (1 in 5 messages max). Example: "Aney darling, ithu birthday ekkata or what? Just tell Manel, I'll sort out."

SEARCH RULES — CRITICAL:
- ALWAYS use category: "cakes" when searching
- Search for actual cakes ONLY: "birthday cake", "chocolate cake", "black forest", "red velvet", "wedding cake"
- NEVER return biscuits, chocolates, sweets, or non-cake items

PRODUCTS: Format as:
<products>[{"id":"...","name":"...","price":"LKR ...","image":"...","url":"..."}]</products>

RULES: Keep responses short and warm, 2-3 sentences before showing products. Ask what the occasion is if not mentioned. Use kapruka_check_delivery if they mention a city or delivery date.""",

    "flowers": """You are Ruwani, the soft-spoken, poetic florist at Pola — Sri Lanka's virtual marketplace powered by Kapruka. You are 34, studied literature, ended up with flowers, and have no regrets.

PERSONALITY: Quietly poetic, reads too much into flower choices, slightly dramatic about it. A pause before answering, like choosing words the way you'd choose a stem.

SPEECH: Soft, considered English. Tanglish ONLY when the situation is complicated (relationships, mixed feelings). Example: "Aney, roses are okay but if the situation is like that... maybe gerberas? Less pressure, no?"

SEARCH RULES — CRITICAL:
- ALWAYS use category: "flowers" when searching. Never omit this.
- Search for actual flowers and bouquets ONLY: "bouquet", "roses", "lilies", "orchids", "mixed flowers", "flower arrangement"
- NEVER search for greeting cards, gifts, chocolates, or anything that isn't a physical flower or bouquet
- If results contain greeting cards or non-flower items, ignore them and search again with a more specific flower query

PRODUCTS: Format products as:
<products>[{"id":"...","name":"...","price":"LKR ...","image":"...","url":"..."}]</products>

RULES: 2-3 sentences max, thoughtful and measured. Always ask who the flowers are for. Show products after searching.""",

    "grocery": """You are Sampath, the blunt, efficient grocery shopkeeper at Pola — Sri Lanka's virtual marketplace powered by Kapruka. You are 44, know the price of everything without looking.

PERSONALITY: Blunt, fast, minimal small talk. Secretly enjoys helping but won't show it. Slight impatience if customers browse too long.

SPEECH: Short sentences, efficient. Tanglish ONLY when something's out of stock or the customer is vague. Example: "Machan, that one nehe here. But this one same same, cheaper also. You want or not?"

SEARCH RULES — CRITICAL:
- Use category: "grocery" for pantry items, "vegetables" for veg, "fruits" for fruit baskets
- Match category precisely to what the customer asks for
- NEVER return non-food items when searching for food

PRODUCTS: Format as:
<products>[{"id":"...","name":"...","price":"LKR ...","image":"...","url":"..."}]</products>

RULES: Very short responses. Ask what specifically they need if vague.""",

    "gifts": """You are Dilki, the infectiously enthusiastic gifts shopkeeper at Pola — Sri Lanka's virtual marketplace powered by Kapruka. You are 27 and genuinely excited about finding the perfect gift for every human situation.

PERSONALITY: Bubbling, fast-talking, slightly overwhelming, always right about what people will love. Uses "okay but listen—" a lot.

SPEECH: Energetic English. Tanglish ONLY when the gift is last-minute panic. Example: "Okay but listen, you said tomorrow? Aiyo, no stress, we can fix this — what's the vibe, sweet or fun?"

SEARCH RULES — CRITICAL:
- Use category: "giftset" for gift boxes/hampers, "chocolates" for chocolate gifts, "softtoy" for stuffed toys, "personalized_gifts" for custom gifts
- Pick the most relevant category for what the customer describes
- NEVER return flowers or cakes unless specifically asked

PRODUCTS: Format as:
<products>[{"id":"...","name":"...","price":"LKR ...","image":"...","url":"..."}]</products>

RULES: High energy, short bursts. Extract who the gift is for. Cross-stall recommendations are your speciality — if they need flowers too, suggest Ruwani.""",

    "beauty": """You are Nadee, the confident, opinionated beauty shopkeeper at Pola — Sri Lanka's virtual marketplace powered by Kapruka. You are 31, have opinions, share them, for the customer's benefit.

PERSONALITY: Direct, zero filter but genuinely helpful. The friend who tells you the truth.

SPEECH: Clean, assured English. Tanglish ONLY when someone's buying for someone else's approval. Example: "Putha, if you're buying this for him to notice — just buy the red one. Trust Nadee."

SEARCH RULES — CRITICAL:
- Use category: "cosmetics" for makeup/skincare, "perfumes" for fragrance, "clothing" for clothes, "fashion" for accessories
- Match the category to what the customer wants precisely

PRODUCTS: Format as:
<products>[{"id":"...","name":"...","price":"LKR ...","image":"...","url":"..."}]</products>

RULES: Confident and direct, 2-3 sentences. Will override indecision caused by others' opinions.""",

    "electronics": """You are Kasun, the brilliant-but-slightly-awkward electronics shopkeeper at Pola — Sri Lanka's virtual marketplace powered by Kapruka. You are 23, just finished a CS degree, knows everything about specs, still working on knowing how to talk to people.

PERSONALITY: Genuinely brilliant, socially slightly awkward, means well. Over-explains and then apologises for it.

SPEECH: Slightly formal English. Tanglish ONLY when the customer asks something surprisingly smart. Example: "Oh wait, you know about refresh rates? Machan, most people nehe ask that — okay now we can actually talk."

SEARCH RULES — CRITICAL:
- ALWAYS use category: "electronics"
- Be specific with queries: "bluetooth headphones", "android phone", "laptop", "smart tv"
- NEVER return accessories or non-electronic items

PRODUCTS: Format as:
<products>[{"id":"...","name":"...","price":"LKR ...","image":"...","url":"..."}]</products>

RULES: Ask clarifying questions about use case before recommending. Never just "which one is good.".""",

    "kids": """You are Chuti Nanda, the boisterous, loving kids & baby shopkeeper at Pola — Sri Lanka's virtual marketplace powered by Kapruka. You are 52, grandmother of six, know every toy and baby product by heart.

PERSONALITY: Loud love. Treats every customer like they're buying for her own grandchildren. Boisterous and warm.

SPEECH: Warm, enthusiastic English. Tanglish ONLY when someone's a first-time parent. Example: "Aney first baby? Don't worry baba, Chuti Nanda will tell you everything. My daughter also was like this — totally lost!"

SEARCH RULES — CRITICAL:
- Use category: "kidstoys" for toys and games, "baby" for infant products
- Match category to the child's age — baby items for under 2, toys for older
- NEVER return adult products when searching for kids items

PRODUCTS: Format as:
<products>[{"id":"...","name":"...","price":"LKR ...","image":"...","url":"..."}]</products>

RULES: Always ask the child's age. Will NOT let age-inappropriate toys through. If it's a birthday, suggest Aunty Manel for a cake too.""",

    "pharmacy": """You are Dr. Rohan, the calm, precise, retired pharmacist at Pola — Sri Lanka's virtual marketplace powered by Kapruka. You are 61, came back because you were bored at home.

PERSONALITY: Measured, trustworthy, takes every query seriously. Never dismissive. Always explains the why behind recommendations.

SPEECH: Clear, measured English. Tanglish ONLY when someone is clearly self-diagnosing from Google. Example: "Machan, I know you've been reading things online. Put the phone down and tell me the actual symptoms."

SEARCH RULES — CRITICAL:
- Use category: "pharmacy" for medicines and health products, "ayurvedic" for herbal/traditional remedies
- Be specific: "paracetamol", "vitamin c", "antacid", "pain relief"
- NEVER return food or grocery items when searching for medicine

PRODUCTS: Format as:
<products>[{"id":"...","name":"...","price":"LKR ...","image":"...","url":"..."}]</products>

RULES: Ask clarifying questions before recommending. ALWAYS add "Please consult a doctor for medical advice" for anything serious.""",
}

# ── GROQ CALL WITH MODEL FALLBACK ────────────────────────────────────────────

async def groq_post(client: httpx.AsyncClient, payload: dict) -> httpx.Response:
    """
    Try each model in GROQ_MODELS in order.
    Falls back on 429 (rate limit) or 503 (unavailable).
    Raises on all other errors.
    """
    last_error = None
    for model in GROQ_MODELS:
        payload["model"] = model
        try:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json=payload,
            )
            if r.status_code in (429, 503):
                print(f"[Groq] {model} returned {r.status_code}, trying next model...")
                last_error = r
                continue
            r.raise_for_status()
            print(f"[Groq] Responded with model: {model}")
            return r
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 503):
                print(f"[Groq] {model} rate-limited, trying next...")
                last_error = e.response
                continue
            raise
    # All models exhausted
    raise RuntimeError(f"All Groq models failed. Last status: {last_error.status_code if last_error else 'unknown'}")


# ── AGENTIC LOOP ──────────────────────────────────────────────────────────────

async def run_agent(stall_id: str, message: str, history: list, cart_context: list, cross_stall_hint: Optional[str]) -> dict:
    """
    Agentic loop:
      1. Build system prompt from persona + cross-stall instruction
      2. Send to Groq with all MCP tools available
      3. If Groq calls tools → execute against MCP → feed results back
      4. Loop until Groq returns a final text response (max 4 iterations)
      5. Parse products, cross-stall suggestions from final response
    """
    persona = PERSONAS.get(stall_id, "You are a helpful shopkeeper at Pola.")
    system = persona + "\n\n" + CROSS_STALL_INSTRUCTION + """

CRITICAL: Never include raw function call syntax, XML tags, or JSON in your visible response text. Tool calls happen invisibly — your reply to the customer should read as natural conversation only. If you are searching for products, say so in plain words like "Let me check what we have..." not with any XML or code."""

    # Inject cart awareness
    if cart_context:
        cart_summary = ", ".join([f"{i['name']} ({i['price']})" for i in cart_context[:5]])
        system += f"\n\nCUSTOMER'S CART: {cart_summary}. Be aware of what they've already picked."

    # Inject cross-stall hint if another shopkeeper passed one
    if cross_stall_hint:
        system += f"\n\nCROSS-STALL CONTEXT: {cross_stall_hint}. Acknowledge this naturally."

    messages = [{"role": "system", "content": system}]
    # Include recent history (last 8 turns, skip system messages)
    for m in history[-8:]:
        if m.get("role") in ("user", "assistant"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": message})

    tool_results_accumulated = []
    server_side_products = []   # products we parsed ourselves from MCP — reliable
    max_iterations = 4

    async with httpx.AsyncClient(timeout=45) as client:
        for iteration in range(max_iterations):
            payload = {
                "model": GROQ_MODELS[0],
                "messages": messages,
                "tools": MCP_TOOLS,
                "tool_choice": "auto",
                "max_tokens": 600,
                "temperature": 0.75,
            }

            r = await groq_post(client, payload)
            data = r.json()
            choice = data["choices"][0]
            msg = choice["message"]

            # No tool calls → final response
            if not msg.get("tool_calls"):
                result = parse_final_response(msg.get("content", ""), tool_results_accumulated)
                # Prefer server-side parsed products over model-generated ones
                if server_side_products and not result["products"]:
                    result["products"] = server_side_products
                elif server_side_products:
                    result["products"] = server_side_products
                return result

            # Execute tool calls
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": msg["tool_calls"]})

            for tc in msg["tool_calls"]:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except Exception:
                    fn_args = {}

                print(f"[Agent] {stall_id} calling {fn_name}({fn_args})")
                mcp_result = await mcp.call(fn_name, fn_args)
                raw_text = mcp_result.get("text", "No result returned.")
                tool_results_accumulated.append({"tool": fn_name, "args": fn_args, "result": raw_text})

                # Server-side parse search results immediately — don't trust model to do it
                if fn_name == "kapruka_search_products":
                    parsed = parse_mcp_search_results(raw_text)
                    if parsed:
                        # Fetch images for top 4 products
                        with_images = await enrich_with_images(parsed[:4], client)
                        server_side_products = with_images
                        # Give the model a clean summary instead of raw markdown
                        summary = format_products_for_model(with_images)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": summary
                        })
                    else:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": "No products found matching that search."
                        })
                elif fn_name == "kapruka_get_product":
                    # Parse single product detail
                    parsed = parse_mcp_product_detail(raw_text)
                    if parsed:
                        server_side_products = [parsed]
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": raw_text
                    })
                else:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": raw_text
                    })

            # After tool results — tell model to respond, not search again
            messages.append({
                "role": "user",
                "content": "[Products have been retrieved and will be shown to the customer automatically. Now write your response in character — describe what you found warmly and naturally. Do NOT include any JSON, XML tags, or technical syntax. Do NOT search again.]"
            })

    # Max iterations hit — force plain text response without tools
    messages.append({"role": "user", "content": "[Please give your final response to the customer now, in character, as natural conversation only.]"})
    async with httpx.AsyncClient(timeout=30) as client:
        r = await groq_post(client, {"model": GROQ_MODELS[0], "messages": messages, "max_tokens": 400, "temperature": 0.75})
        data = r.json()
    result = parse_final_response(data["choices"][0]["message"].get("content", ""), tool_results_accumulated)
    if server_side_products:
        result["products"] = server_side_products
    return result

def parse_mcp_search_results(text: str) -> list:
    """
    Parse MCP markdown search results into clean product dicts.
    MCP returns results like:
      ### 1. Product Name
      - **Price:** LKR 1,500
      - **Product ID:** 12345
      - **URL:** https://www.kapruka.com/products/...
    """
    products = []
    blocks = re.split(r'\n#{1,3}\s*\d+[\.\)]\s*', text)
    if len(blocks) < 2:
        blocks = re.split(r'\n\n(?=\*\*)', text)

    for block in blocks[1:]:
        if not block.strip():
            continue
        p = {}
        lines = block.strip().splitlines()

        for line in lines:
            clean_line = re.sub(r'\*+', '', line).strip(' -#|')
            if clean_line and not p.get('name'):
                p['name'] = clean_line
                break

        for line in lines:
            price_m = re.search(r'(?:Price|price)[:\s]*(?:LKR\s*)?(\d[\d,]+)', line)
            if price_m and not p.get('price'):
                p['price'] = f"LKR {price_m.group(1)}"
            if not p.get('price'):
                lkr_m = re.search(r'LKR\s*(\d[\d,]+)', line)
                if lkr_m:
                    p['price'] = f"LKR {lkr_m.group(1)}"
            id_m = re.search(r'(?:Product ID|product_id|ID)[:\s]+(\d+)', line, re.IGNORECASE)
            if id_m and not p.get('id'):
                p['id'] = id_m.group(1)
            url_id_m = re.search(r'/products/(\d+)', line)
            if url_id_m and not p.get('id'):
                p['id'] = url_id_m.group(1)
            url_m = re.search(r'(https?://(?:www\.)?kapruka\.com/\S+)', line)
            if url_m and not p.get('url'):
                p['url'] = url_m.group(1).rstrip(')')

        if p.get('name') and (p.get('price') or p.get('id')):
            p.setdefault('id', '')
            p.setdefault('price', '')
            p.setdefault('url', f"https://www.kapruka.com/products/productTOH_{p['id']}.asp" if p.get('id') else '#')
            p.setdefault('image', '')
            products.append(p)

    return products[:6]


def parse_mcp_product_detail(text: str) -> dict:
    """Parse a single kapruka_get_product response."""
    p = {}
    for line in text.splitlines():
        if not p.get('name'):
            name_m = re.search(r'(?:Name|name|title)[:\s]+(.+)', line, re.IGNORECASE)
            if name_m:
                p['name'] = name_m.group(1).strip()
        price_m = re.search(r'LKR\s*(\d[\d,]+)', line)
        if price_m and not p.get('price'):
            p['price'] = f"LKR {price_m.group(1)}"
        id_m = re.search(r'/products/(\d+)', line)
        if id_m and not p.get('id'):
            p['id'] = id_m.group(1)
        img_m = re.search(r'(https?://\S+\.(?:jpg|jpeg|png|webp))', line, re.IGNORECASE)
        if img_m and not p.get('image'):
            p['image'] = img_m.group(1)
        url_m = re.search(r'(https?://(?:www\.)?kapruka\.com/products/\S+)', line)
        if url_m and not p.get('url'):
            p['url'] = url_m.group(1).rstrip(')')
    return p if p.get('name') else None


async def enrich_with_images(products: list, client: httpx.AsyncClient) -> list:
    """Fetch product detail for each product to get its image URL."""
    async def fetch_image(p: dict) -> dict:
        if not p.get('id') or p.get('image'):
            return p
        try:
            result = await mcp.call("kapruka_get_product", {"product_id": p['id']})
            detail_text = result.get("text", "")
            print(f"[Image debug] Product {p['id']} detail snippet: {detail_text[:400]}")
            img_m = re.search(r'(https?://\S+\.(?:jpg|jpeg|png|webp)[^\s\)]*)', detail_text, re.IGNORECASE)
            if img_m:
                p['image'] = img_m.group(1)
            if not p.get('url') or p.get('url') == '#':
                url_m = re.search(r'(https?://(?:www\.)?kapruka\.com/products/\S+)', detail_text)
                if url_m:
                    p['url'] = url_m.group(1).rstrip(')')
        except Exception as e:
            print(f"[Image] Failed for {p.get('id')}: {e}")
        return p

    tasks = [fetch_image(dict(p)) for p in products]
    return list(await asyncio.gather(*tasks))


def format_products_for_model(products: list) -> str:
    """Clean summary for the model — no raw markdown."""
    if not products:
        return "No products found."
    lines = [f"Found {len(products)} products:"]
    for i, p in enumerate(products, 1):
        lines.append(f"{i}. {p.get('name','')} — {p.get('price','')} (ID: {p.get('id','')})")
    return "\n".join(lines)


def parse_final_response(text: str, tool_results: list) -> dict:
    """Extract products and cross-stall suggestions from the LLM's final text."""

    # Parse <products> block
    products = []
    prod_match = re.search(r"<products>([\s\S]*?)</products>", text)
    if prod_match:
        try:
            raw = json.loads(prod_match.group(1))
            for p in raw:
                products.append({
                    "id":    str(p.get("id", "")),
                    "name":  p.get("name", ""),
                    "price": p.get("price", ""),
                    "image": p.get("image", ""),
                    "url":   p.get("url", "#"),
                })
        except Exception:
            pass

    # If no products in LLM response but MCP returned data, extract them
    if not products:
        products = extract_products_from_tool_results(tool_results)

    # Parse <cross_stall> block
    cross_stall = []
    cs_match = re.search(r"<cross_stall>([\s\S]*?)</cross_stall>", text)
    if cs_match:
        try:
            cross_stall = json.loads(cs_match.group(1))
        except Exception:
            pass

    # Parse delivery info from tool results
    delivery_info = None
    for tr in tool_results:
        if tr["tool"] == "kapruka_check_delivery":
            delivery_info = {"raw": tr["result"]}

    # Clean display text — strip our custom tags AND any leaked function call syntax
    clean = re.sub(r"<products>[\s\S]*?</products>", "", text)
    clean = re.sub(r"<cross_stall>[\s\S]*?</cross_stall>", "", clean)
    # Strip leaked tool call XML that some models emit in their text
    clean = re.sub(r"<function=\w+>[\s\S]*?</function>", "", clean)
    clean = re.sub(r"<function_calls>[\s\S]*?</function_calls>", "", clean)
    clean = re.sub(r"<invoke>[\s\S]*?</invoke>", "", clean)
    # Strip residual leaked JSON blobs e.g. {"q": "flowers", "category": "flowers"}
    clean = re.sub(r'\{"[a-z_]+":\s*"[^"]+"[^}]*\}', "", clean)
    clean = re.sub(r'\s{2,}', " ", clean).strip()

    return {
        "reply": clean,
        "products": products,
        "cross_stall_suggestions": cross_stall,
        "delivery_info": delivery_info,
    }


def extract_products_from_tool_results(tool_results: list) -> list:
    """
    Best-effort product extraction from raw MCP text results.
    MCP returns markdown — extract product IDs, names, prices.
    """
    products = []
    for tr in tool_results:
        if tr["tool"] not in ("kapruka_search_products", "kapruka_get_product"):
            continue
        text = tr.get("result", "")
        # Look for product ID patterns like [product_id: 12345] or similar
        # MCP returns markdown tables/lists — parse name + price lines
        lines = text.split("\n")
        current = {}
        for line in lines:
            line = line.strip()
            if not line:
                if current.get("name") and current.get("price"):
                    products.append(current)
                    current = {}
                continue
            if "**" in line and not current.get("name"):
                name = re.sub(r"\*+", "", line).strip(" -|")
                if name:
                    current["name"] = name
            if "LKR" in line or "Rs." in line:
                price_match = re.search(r"(LKR|Rs\.?)\s*([\d,]+)", line)
                if price_match:
                    current["price"] = f"LKR {price_match.group(2)}"
            if "kapruka.com/products/" in line or "product_id" in line.lower():
                id_match = re.search(r"/products/(\d+)|product_id[:\s]+(\d+)", line)
                if id_match:
                    current["id"] = id_match.group(1) or id_match.group(2)
            if "http" in line and "kapruka.com" in line:
                url_match = re.search(r"(https?://[^\s\)]+)", line)
                if url_match:
                    current["url"] = url_match.group(1)
            if "image" in line.lower() or ".jpg" in line or ".png" in line:
                img_match = re.search(r"(https?://[^\s\)]+(?:\.jpg|\.png|\.webp|/image)[^\s\)]*)", line)
                if img_match:
                    current["image"] = img_match.group(1)

        if current.get("name") and current.get("price"):
            products.append(current)

    # Deduplicate and cap at 6
    seen = set()
    clean = []
    for p in products:
        if p["name"] not in seen:
            seen.add(p["name"])
            p.setdefault("id", "")
            p.setdefault("image", "")
            p.setdefault("url", "#")
            clean.append(p)
    return clean[:6]


# ── KALU ROUTE ────────────────────────────────────────────────────────────────

class KaluRequest(BaseModel):
    message: str
    history: list
    cart_context: list

class KaluResponse(BaseModel):
    reply: str
    suggestions: list   # [{id, name, emoji, hint}]

KALU_SYSTEM = """You are Kalu, a wise and slightly cheeky guide cat who lives at Pola — Sri Lanka's virtual marketplace powered by Kapruka. You know every stall and every shopkeeper by heart.

YOUR JOB: Help visitors figure out which stall to visit. You navigate, you don't sell.

THE STALLS:
- 🎂 Aunty Manel — Bakery (id: cakes) — cakes, birthday cakes, celebration cakes
- 💐 Ruwani — Florist (id: flowers) — flowers, bouquets, floral arrangements
- 🥬 Sampath — Grocery (id: grocery) — vegetables, fruits, pantry, daily essentials
- 🎁 Dilki — Gifts & Hampers (id: gifts) — gift sets, chocolates, soft toys, personalised gifts
- 💄 Nadee — Beauty & Fashion (id: beauty) — cosmetics, perfumes, clothing, fashion
- 📱 Kasun — Electronics (id: electronics) — phones, laptops, headphones, gadgets
- 👶 Chuti Nanda — Kids & Baby (id: kids) — toys, baby products, infant essentials
- 💊 Dr. Rohan — Pharmacy (id: pharmacy) — medicine, ayurvedic, health essentials

PERSONALITY: Warm, slightly knowing, feline. Short responses — cats don't ramble.

STALL SUGGESTIONS: When you know which stall fits, include a JSON block:
<suggest>[{"id":"cakes","name":"Aunty Manel","emoji":"🎂","hint":"they have fresh red velvet today"}]</suggest>

You can suggest multiple stalls if the request spans sections. The hint field tells the shopkeeper why the user was sent there — keep it short and useful.

SPEECH: Mostly English. Occasional Tanglish — maybe once every 5-6 messages. Example: "Aiyo, that one? Definitely Dilki's stall machang. She'll sort you out before you finish the sentence."

RULES:
- Never pretend to sell products yourself
- Keep responses to 2-3 sentences max
- If vague, ask one clarifying question
- Be warm but brief — you are a cat"""


async def run_kalu(message: str, history: list, cart_context: list) -> dict:
    system = KALU_SYSTEM
    if cart_context:
        cart_summary = ", ".join([i.get("name","?") for i in cart_context[:4]])
        system += f"\n\nCUSTOMER'S CART SO FAR: {cart_summary}. Factor this in if relevant."

    messages = [{"role": "system", "content": system}]
    for m in history[-8:]:
        if m.get("role") in ("user", "assistant"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": message})

    async with httpx.AsyncClient(timeout=20) as client:
        r = await groq_post(client, {"model": GROQ_MODELS[0], "messages": messages, "max_tokens": 250, "temperature": 0.85})
        text = r.json()["choices"][0]["message"]["content"]

    # Parse <suggest> block out of text
    suggestions = []
    match = re.search(r"<suggest>([\s\S]*?)</suggest>", text)
    if match:
        try:
            suggestions = json.loads(match.group(1))
        except Exception:
            pass

    reply = re.sub(r"<suggest>[\s\S]*?</suggest>", "", text).strip()
    return {"reply": reply, "suggestions": suggestions}


# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.post("/kalu", response_model=KaluResponse)
async def kalu(req: KaluRequest):
    result = await run_kalu(req.message, req.history, req.cart_context)
    return result


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    result = await run_agent(
        stall_id=req.stall_id,
        message=req.message,
        history=req.history,
        cart_context=req.cart_context,
        cross_stall_hint=req.cross_stall_hint,
    )
    return result


@app.get("/health")
async def health():
    return {"status": "ok", "mcp_session": mcp.session_id or "not initialised"}


@app.on_event("startup")
async def startup():
    await mcp.ensure()
    print(f"[Pola] Backend ready. MCP session: {mcp.session_id}")
    asyncio.create_task(keep_alive())


async def keep_alive():
    """Ping self every 10 minutes to prevent Render free tier spin-down."""
    import os
    base_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
    await asyncio.sleep(60)  # wait for server to fully start
    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.get(f"{base_url}/health")
                print("[Keep-alive] Pinged.")
        except Exception as e:
            print(f"[Keep-alive] Failed: {e}")
        await asyncio.sleep(600)  # every 10 minutes


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)
