"""Build the reviewer PDF and matching vector overview. Requires reportlab 4.4.9."""

import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/pdf/capability-studio-reviewer-guide.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)
W, H = 595.28, 841.89
INK = "#173C3A"
TEAL = "#167765"
MINT = "#DBEEE7"
PAPER = "#F4F7F3"
MUTED = "#58706C"
BLUE = "#163447"
GOLD = "#D1A35F"
c = canvas.Canvas(str(OUT), pagesize=(W, H), pageCompression=1)
c.setTitle("Capability Studio | Reviewer Guide")
c.setAuthor("Manish Soni")
c.setSubject("Computer-use discovery, typed capabilities, and model-free replay")
styles = {
    "body": ParagraphStyle(
        "body", fontName="Helvetica", fontSize=10.6, leading=15.2, textColor=HexColor(INK)
    ),
    "small": ParagraphStyle(
        "small", fontName="Helvetica", fontSize=9, leading=12.5, textColor=HexColor(MUTED)
    ),
    "white": ParagraphStyle(
        "white", fontName="Helvetica", fontSize=11, leading=16, textColor=white
    ),
}


def txt(text, x, top, size=11, color=INK, font="Helvetica"):
    c.setFillColor(HexColor(color))
    c.setFont(font, size)
    c.drawString(x, H - top - size, text)


def para(text, x, top, width, style="body"):
    p = Paragraph(text, styles[style])
    _, height = p.wrap(width, 1000)
    if top + height > H - 43:
        raise ValueError(f"Overflow: {text[:70]} at {top + height}")
    p.drawOn(c, x, H - top - height)
    return top + height


def rect(x, top, w, h, fill, r=12, stroke=None):
    c.setFillColor(HexColor(fill))
    c.setStrokeColor(HexColor(stroke or fill))
    c.roundRect(x, H - top - h, w, h, r, fill=1, stroke=bool(stroke))


def card(x, top, w, h, fill="#FFFFFF"):
    rect(x + 3, top + 5, w, h, "#DFE8E2")
    rect(x, top, w, h, fill)


def line(top):
    c.setStrokeColor(HexColor("#CAD9D1"))
    c.line(42, H - top, W - 42, H - top)


def page(n, label, title, subtitle):
    c.setFillColor(HexColor(PAPER))
    c.rect(0, 0, W, H, fill=1, stroke=0)
    txt("C / CAPABILITY STUDIO", 42, 28, 9, TEAL, "Helvetica-Bold")
    txt(label.upper(), 355, 28, 8, MUTED)
    txt(title, 42, 72, 27, INK, "Helvetica-Bold")
    para(subtitle, 42, 113, W - 84)
    line(H - 47)
    txt("MANISH SONI  /  INTERFACE.AI ASSIGNMENT", 42, H - 34, 7.5, MUTED)
    txt(f"{n:02d} / 08", 509, H - 34, 8, MUTED)
    c.bookmarkPage(f"p{n}")
    c.addOutlineEntry(title, f"p{n}", level=0)


def end():
    c.showPage()


def block(x, top, w, h, title, sub, color=TEAL):
    d = 12
    y = H - top - h
    c.setFillColor(HexColor("#D6E1DC"))
    c.roundRect(x + 5, y - 7, w, h, 4, fill=1, stroke=0)
    c.setFillColor(HexColor(color))
    c.rect(x, y, w, h, fill=1, stroke=0)
    p = c.beginPath()
    p.moveTo(x, y + h)
    p.lineTo(x + d, y + h + d)
    p.lineTo(x + w + d, y + h + d)
    p.lineTo(x + w, y + h)
    p.close()
    c.setFillColor(HexColor(MINT))
    c.drawPath(p, fill=1, stroke=0)
    p = c.beginPath()
    p.moveTo(x + w, y)
    p.lineTo(x + w + d, y + d)
    p.lineTo(x + w + d, y + h + d)
    p.lineTo(x + w, y + h)
    p.close()
    c.setFillColor(HexColor("#105346"))
    c.drawPath(p, fill=1, stroke=0)
    txt(title, x + 13, top + 15, 15, "#FFFFFF", "Helvetica-Bold")
    para(sub, x + 13, top + 42, w - 24, "white")


def step(number, title, body, top):
    rect(42, top, 27, 27, TEAL, 7)
    txt(str(number), 51, top + 6, 12, "#FFFFFF", "Helvetica-Bold")
    txt(title, 82, top + 1, 12, INK, "Helvetica-Bold")
    return para(body, 82, top + 23, W - 124) + 18


def link(label, url, x, top):
    txt(label, x, top, 9, TEAL, "Helvetica-Bold")
    c.linkURL(url, (x, H - top - 14, x + len(label) * 5.3, H - top + 2), relative=0, thickness=0)


page(
    1,
    "Reviewer field guide",
    "Discover once. Replay with confidence.",
    "A working integration layer for business software whose only usable interface is its UI.",
)
rect(42, 164, W - 84, 121, BLUE)
txt("THE PROBLEM", 60, 182, 9, "#B1D7CC", "Helvetica-Bold")
para(
    "A bank employee can complete a servicing task by clicking through screens. An agent needs the same ability when the vendor offers no business integration API.",
    60,
    206,
    W - 120,
    "white",
)
block(42, 337, 149, 128, "01  Discover", "AI observes the screen and proposes each next action.")
block(211, 337, 149, 128, "02  Save", "Verified success becomes a typed, reusable capability.")
block(380, 337, 149, 128, "03  Replay", "New inputs. Fixed steps. No model in the loop.", BLUE)
para(
    "<b>The engine is the project.</b> Harbor Ledger Bank is the synthetic target used to demonstrate it. You do not have to perform the clicks yourself before discovery.",
    42,
    506,
    W - 84,
)
for x, n, label in [
    (42, "6", "banking workflows"),
    (216, "141", "passing local tests"),
    (390, "0", "model calls on replay"),
]:
    card(x, 569, 157, 86)
    txt(n, x + 15, 580, 28, TEAL, "Helvetica-Bold")
    txt(label, x + 15, 623, 9, MUTED)
para(
    "Start with the no-key replay on page 3. Then inspect a discovery, change the inputs, and try the same-session human takeover. All records are fictional; every flow stops at review.",
    42,
    692,
    W - 84,
)
link(
    "Public repository and source",
    "https://github.com/Maniss-ai/computer-use-capabilities",
    42,
    754,
)
end()

page(
    2,
    "Architecture",
    "What each part does",
    "One shared executor keeps policy, browser actions, result checks, and control ownership consistent.",
)
block(
    48,
    184,
    215,
    99,
    "Operator dashboard",
    "Choose workflow and inputs. Inspect activity and results.",
)
block(
    318, 184, 215, 99, "Banking website", "The separate target UI, operated through Chromium.", BLUE
)
card(42, 322, W - 84, 120)
txt(
    "Goal + masked screen > model proposal > checked UI action", 58, 340, 12, TEAL, "Helvetica-Bold"
)
para(
    "Gemini receives the goal, typed contract, approved visible controls, recent context, and masked screenshot. It chooses one next action. The engine validates that proposal, binds the input values, and acts through Playwright. Then it observes again.",
    58,
    369,
    W - 116,
)
card(42, 461, 246, 135)
txt("Discovery produces the artifact", 58, 480, 12, INK, "Helvetica-Bold")
para(
    "A finish proposal is not proof. The engine reads the final UI and checks its values. Only successful, unassisted discovery saves a capability.",
    58,
    507,
    214,
)
card(304, 461, 249, 135)
txt("Replay consumes the artifact", 320, 480, 12, INK, "Helvetica-Bold")
para(
    "Typed inputs replace parameter references. Fixed actions and declared recovery rules run without initializing a model client.",
    320,
    507,
    217,
)
para(
    "<b>What developers still write:</b> the adapter, allowed controls, goal/output contracts, state detectors, and error rules. The model discovers the order of actions; it does not build the whole integration from nothing.",
    42,
    625,
    W - 84,
)
para(
    "<b>Why AI here?</b> It can discover an initial UI sequence that would otherwise need manual scripting. Repeated invocation then avoids repeated reasoning. The bank website itself works independently of AI.",
    42,
    690,
    W - 84,
)
end()

page(
    3,
    "Five-minute first run",
    "Try a replay without a key",
    "Install once, start both servers with one command, and use the dashboard for the demonstration.",
)
card(42, 157, W - 84, 149, BLUE)
commands = [
    "git clone https://github.com/Maniss-ai/computer-use-capabilities.git",
    "cd computer-use-capabilities",
    "uv sync --locked --extra dev",
    'export PLAYWRIGHT_BROWSERS_PATH="$PWD/.browser-cache"',
    "uv run playwright install chromium",
    "uv run capabilities web",
]
for i, s in enumerate(commands):
    txt(s, 56, 174 + i * 19, 10, "#FFFFFF", "Helvetica")
para(
    'Requires Python 3.12 and uv. On Linux, install browser system libraries with <font name="Helvetica">uv run playwright install --with-deps chromium</font>.',
    42,
    322,
    W - 84,
    "small",
)
y = step(
    1,
    "Open Capability Studio",
    "Visit <b>http://127.0.0.1:8766/</b>. The same command also starts the banking sandbox on port 8767.",
    366,
)
y = step(
    2,
    "Choose the bundled capability",
    "Select <b>Sub-account review</b>, <b>Replay capability</b>, and <b>Prepared sub-account review</b>. This artifact came from a genuine recorded Gemini run.",
    y,
)
y = step(
    3,
    "Use a different member",
    "Click <b>Member 10042</b>. Verify <b>10042 / Checking / Travel Fund</b>. Leave Test scenario on <b>Normal workflow</b>. Click <b>Run capability</b>.",
    y,
)
y = step(
    4,
    "Check the actual result",
    "Expect <b>Success</b>, <b>Model calls = 0</b>, and <b>Review sub-account</b>. Result must show all three input values and <b>review ready = true</b>. Activity lists checkpoints; Capability shows the JSON.",
    y,
)
para(
    "<b>Success stops at review.</b> No account is opened and no banking record changes. The live view shows the engine-owned browser, not a pre-rendered animation.",
    42,
    y + 3,
    W - 84,
    "small",
)
end()

page(
    4,
    "Discovery and reuse",
    "Let AI find the path",
    "No manual recording or demonstration is needed. Supply the goal inputs and let the agent operate the UI.",
)
y = step(
    1,
    "Configure discovery access",
    'Add <font name="Helvetica">GEMINI_API_KEY=...</font> to the ignored local <b>.env</b> file and restart the dashboard. Keep the key out of Git. Replay and tests need no key.',
    165,
)
y = step(
    2,
    "Start one genuine discovery",
    "Choose <b>Sub-account review > Discover with AI > Gemini</b>. Click <b>Member 10023</b>: 10023 / Savings / Emergency Fund. Keep Normal workflow, then click <b>Discover and save</b>.",
    y,
)
y = step(
    3,
    "Verify before reusing",
    "Wait for Success, a matching review, nonzero model calls, and a new saved capability. If the run stops, inspect Result and Activity; a failed discovery must not publish an artifact.",
    y,
)
y = step(
    4,
    "Replay that same capability",
    "Click <b>Use this capability with new inputs</b>. Keep the new capability selected. Click <b>Member 10042</b>, then <b>Run capability</b>. Confirm new values and zero model calls.",
    y,
)
card(42, 546, W - 84, 104)
txt("RECORDED EXAMPLE / SUB-ACCOUNT", 58, 562, 9, TEAL, "Helvetica-Bold")
txt("Discovery: 7 calls / 86.2s", 58, 585, 17, INK, "Helvetica-Bold")
txt("Replay: 0 calls / 5.3s", 310, 585, 17, INK, "Helvetica-Bold")
para(
    "One observed pair after the timeout fix; timings vary. This successful live discovery did not need a retry.",
    58,
    618,
    W - 116,
    "small",
)
para(
    "<b>If Gemini is slow:</b> transient request failures have bounded retries of the undecided step; completed UI actions are not repeated. Quota and authentication errors stop. There is no paid-provider fallback.",
    42,
    680,
    W - 84,
)
para(
    "The workflow library counts saved artifacts, not trained models. A fresh checkout bundles one sub-account capability. Each workspace adds its own discoveries.",
    42,
    739,
    W - 84,
    "small",
)
end()

workflows = json.loads((ROOT / "src/capabilities/profiles/workflows.json").read_text())
meaning = [
    "Prepare an additional Savings or Checking account request.",
    "Find a member-owned card and prepare replacement preferences.",
    "Find a posted payment and prepare an investigation intake.",
    "Prepare a mailing address change and a verification route.",
    "Prepare a statement period, document format, and delivery request.",
    "Find an assessed fee and prepare a waiver-review request.",
]
for page_num, indices in [(5, [0, 1, 2]), (6, [3, 4, 5])]:
    page(
        page_num,
        "Workflow reference",
        "Six realistic review workflows" if page_num == 5 else "Profile, documents, and fees",
        "A = discover with Member 10023. B = replay the saved capability with Member 10042.",
    )
    top = 160
    for idx in indices:
        w = workflows[idx]
        rows = len(w["labels"])
        height = 157 if page_num == 5 else [212, 174, 183][indices.index(idx)]
        card(42, top, W - 84, height)
        txt(f"{idx + 1:02d}  {w['title']}", 56, top + 11, 14, TEAL, "Helvetica-Bold")
        para(meaning[idx], 56, top + 34, W - 112, "small")
        ty = top + 58
        # Longer address and supporting-note rows use wrapped cells.
        for key, label in w["labels"].items():
            a = escape(w["examples"][0][key])
            b = escape(w["examples"][1][key])
            end1 = para(f"<b>{escape(label)}</b>", 56, ty, 126, "small")
            end2 = para(a, 195, ty, 160, "small")
            end3 = para(b, 371, ty, 164, "small")
            ty = max(end1, end2, end3) + 4
        if ty > top + height - 7:
            raise ValueError(f"Card overflow {w['id']}: {ty} > {top + height}")
        top += height + 14
    if page_num == 5:
        para(
            "<b>Expected for every normal case:</b> the matching review screen, all requested values, review ready = true, and no final submission. Replay always has zero model calls.",
            42,
            top + 7,
            W - 84,
        )
        para(
            "Member 10077 (Avery Patel) is also available. Record references must match the member: CARD-, TXN-, ACC-, or FEE- followed by the member ID.",
            42,
            top + 65,
            W - 84,
            "small",
        )
    end()

page(
    7,
    "Exceptions and handoff",
    "Handle exceptions. Keep control.",
    "Use the bundled sub-account capability with 10042 / Checking / Travel Fund. Change only the item shown.",
)
rows = [
    (
        "Missing member",
        "Member ID = 99999",
        "Outcome: member_not_found. A valid business answer; no review.",
    ),
    (
        "Known notice",
        "Scenario = Known notice",
        "Automatic recovery, then Success. Zero model calls.",
    ),
    (
        "Permission denied",
        "Scenario = Permission denied",
        "Stopped with a permission failure. No attempt to bypass access.",
    ),
    (
        "Session expiry",
        "Scenario = Session expired",
        "Needs you. Claim, restore in the live preview, and return control.",
    ),
]
y = 168
for title, change, expect in rows:
    card(42, y, W - 84, 91)
    txt(title, 57, y + 10, 13, TEAL, "Helvetica-Bold")
    para("<b>" + change + "</b><br/>" + expect, 57, y + 33, W - 114)
    y += 105
rect(42, 601, W - 84, 116, BLUE)
txt("SAME BROWSER. ONE OWNER AT A TIME.", 58, 615, 10, "#B1D7CC", "Helvetica-Bold")
para(
    "Click Claim session. Click Restore session inside the live banking preview. Click Return to automation. The engine rechecks the screen and resumes. A control epoch rejects stale requests and prevents concurrent human/agent actions.",
    58,
    641,
    W - 116,
    "white",
)
para(
    "<b>Do not use Open manual sandbox for takeover.</b> That link opens an independent session. Manual actions there do not train discovery or repair the engine-owned browser.",
    42,
    735,
    W - 84,
    "small",
)
end()

page(
    8,
    "Evidence and scope",
    "What is proven, and where to look",
    "The evidence is reviewable. Fixture tests and genuine model runs are labeled separately.",
)
card(42, 158, W - 84, 115)
txt("141 local tests passed", 58, 174, 22, TEAL, "Helvetica-Bold")
para(
    "Lint, format, strict typing, real-browser tests, and submission evidence checks pass. The live gate requires genuine discovery and a successful zero-model replay with the same artifact hash.",
    58,
    211,
    W - 116,
)
items = [
    ("Core loop and artifact", "evidence/live/ + schemas/capability.schema.json"),
    ("Error handling and handoff", "evidence/offline/ + tests/test_dashboard.py"),
    ("Expanded genuine runs", "evidence/expanded/ (card replacement and dispute)"),
    ("Timeout fix and matching replay", "evidence/timeout-recovery/"),
    ("Reasoning and deliberate cuts", "REPORT.md (seven required assignment headings)"),
]
y = 295
for a, b in items:
    txt(a, 42, y, 11, INK, "Helvetica-Bold")
    txt(b, 42, y + 19, 9, MUTED)
    y += 47
para(
    "<b>Coverage:</b> all six goals pass browser tests with scripted planners. Sub-account, card replacement, and dispute also have successful genuine Gemini discovery/replay evidence. Address, statement, and fee do not yet have successful live-model evidence. Failed runs are retained.",
    42,
    540,
    W - 84,
)
para(
    "<b>Scope:</b> synthetic data; one active run; local console; files for artifacts/evidence; in-memory target records. Desktop drivers, production authentication, and multi-tenant runtime are design extensions. This is not a deployed production banking service.",
    42,
    619,
    W - 84,
)
para(
    "<b>Sharing:</b> GitHub hosts the repository, guide, and evidence. GitHub Pages cannot run Python/Chromium. A full online demo needs a runtime such as Codespaces or a separate authenticated server host.",
    42,
    693,
    W - 84,
    "small",
)
link("Repository", "https://github.com/Maniss-ai/computer-use-capabilities", 42, 750)
link("Tests and CI", "https://github.com/Maniss-ai/computer-use-capabilities/actions", 156, 750)
link(
    "Full guide + test inputs",
    "https://github.com/Maniss-ai/computer-use-capabilities/blob/main/docs/REVIEWER_GUIDE.md",
    275,
    750,
)
end()
c.save()

# Accessible, code-native vector artwork for the Markdown guide.
svg = [
    '<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="400" viewBox="0 0 1080 400" role="img" aria-labelledby="title desc">',
    '<title id="title">Discover, save, replay</title><desc id="desc">AI discovers a UI workflow. Verified success becomes a capability. Code replays it with new inputs and zero model calls.</desc>',
    '<rect width="1080" height="400" rx="20" fill="#f4f7f3"/>',
    '<text x="44" y="49" font-family="Arial,sans-serif" font-size="15" fill="#167765" font-weight="bold">CAPABILITY STUDIO / HOW IT WORKS</text>',
]
for x, title, lines in [
    (44, "01  Discover", ["Goal + observed UI", "AI proposes each next action"]),
    (394, "02  Save", ["Independent success checks", "Typed, parameterized JSON"]),
    (744, "03  Replay", ["New inputs + same capability", "Fixed steps, zero model calls"]),
]:
    svg.extend(
        [
            f'<rect x="{x + 8}" y="137" width="280" height="160" rx="8" fill="#dce5df"/>',
            f'<path d="M{x} 120 l18 -18 h280 l-18 18 Z" fill="#b8d8c9"/>',
            f'<path d="M{x + 280} 120 l18 -18 v160 l-18 18 Z" fill="#105346"/>',
            f'<rect x="{x}" y="120" width="280" height="160" fill="#167765"/>',
            f'<text x="{x + 20}" y="162" fill="white" font-family="Arial,sans-serif" font-size="26" font-weight="bold">{title}</text>',
        ]
    )
    for j, s in enumerate(lines):
        svg.append(
            f'<text x="{x + 20}" y="{209 + j * 28}" fill="white" font-family="Arial,sans-serif" font-size="17">{s}</text>'
        )
svg.append(
    '<text x="44" y="349" fill="#173c3a" font-family="Arial,sans-serif" font-size="18">One policy-checked executor drives the real browser and verifies the outcome.</text></svg>'
)
(ROOT / "docs/diagrams/discover-save-replay.svg").write_text("\n".join(svg) + "\n")
print(OUT)
