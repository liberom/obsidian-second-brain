#!/usr/bin/env python3
"""/notebooklm [topic] — vault-first NotebookLM workflow facilitator.

NotebookLM (notebooklm.google.com) does source-grounded Q&A against sources you upload.
This command makes it useful as a research tool inside the vault loop:

1. Scan the vault for notes related to the topic (same as /research-deep Phase 1).
2. Bundle the top N notes as a single markdown text the user pastes into NotebookLM
   as a "Pasted Text" source.
3. Emit a structured prompt template the user runs against the notebook.
4. Pause. User does the manual step in NotebookLM (open browser, paste source, ask).
5. User pastes the response back (via the calling command).
6. Save the response to `Research/NotebookLM/YYYY-MM-DD — <slug>.md` in AI-first format.
7. Emit a propagation payload so the calling Claude can run /obsidian-save.

Why not full API: NotebookLM API is beta-access only as of 2026-01 and Google Workspace
gated. The pasted-source workflow works for every user.

Modes:
  --topic "..."         start a new notebook session (output bundle + prompt)
  --save-response       finalize: read response from stdin, write the note, emit payload
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from .lib import vault
from .lib.config import VAULT_PATH

VAULT_SCAN_DIRS = ["wiki", "Research", "Knowledge", "Projects", "Ideas"]
MAX_BUNDLE_NOTES = 12
MAX_CHARS_PER_NOTE = 2000
NOTEBOOKLM_DIR = VAULT_PATH / "Research" / "NotebookLM"


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:80]


def vault_scan(topic: str) -> list[dict]:
    keywords = [w for w in re.split(r"\s+", topic.lower()) if len(w) > 2]
    if not keywords:
        return []
    hits: list[dict] = []
    for sub in VAULT_SCAN_DIRS:
        root = VAULT_PATH / sub
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            if "Research/NotebookLM/" in str(path):
                continue
            try:
                text = path.read_text(errors="ignore").lower()
            except OSError:
                continue
            score = sum(text.count(k) for k in keywords)
            path_score = sum(k in str(path).lower() for k in keywords) * 5
            total = score + path_score
            if total > 0:
                hits.append(
                    {
                        "path": str(path.relative_to(VAULT_PATH)),
                        "abs_path": str(path),
                        "score": total,
                    }
                )
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:MAX_BUNDLE_NOTES]


def build_bundle(topic: str, hits: list[dict]) -> str:
    if not hits:
        return f"# Vault baseline on: {topic}\n\n(Vault has no existing notes referencing this topic.)\n"
    out = [f"# Vault baseline on: {topic}", ""]
    out.append(
        f"This is a bundle of the {len(hits)} most relevant vault notes on the topic, "
        f"prepared as a single source for NotebookLM. Each section below is one vault note. "
        f"Recency markers and wikilinks are preserved verbatim from the vault."
    )
    out.append("")
    for h in hits:
        try:
            text = Path(h["abs_path"]).read_text(errors="ignore")[:MAX_CHARS_PER_NOTE]
        except OSError:
            continue
        out.append("---")
        out.append("")
        out.append(f"## {h['path']}  (relevance score: {h['score']})")
        out.append("")
        out.append(text.strip())
        out.append("")
    return "\n".join(out)


PROMPT_TEMPLATE = """\
You are answering from the sources I pasted above. Topic: "{topic}".

Produce a synthesis with EXACTLY these sections:

## Source summary (3-5 sentences)
What do the pasted sources collectively say about this topic? Be specific. Cite source titles in [brackets].

## Confirmed claims
- [claim] — [which source(s) state it]
- ...

## Contradictions or tensions across sources
- [claim A in source X] vs [claim B in source Y]
- ...

## Gaps in the sources
What questions does the topic raise that the pasted sources don't answer?
- [question]
- ...

## Recommended next reads or angles
Where would a vault writer go next to fill the gaps?
- [angle / source / query]
- ...

## Confidence on the synthesis
high | medium | low — and one sentence on why.

Cite source titles in brackets wherever a claim originates. Do not invent facts beyond the sources.
"""


def emit_start(topic: str) -> int:
    hits = vault_scan(topic)
    bundle = build_bundle(topic, hits)

    NOTEBOOKLM_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(topic)
    bundle_path = NOTEBOOKLM_DIR / f"{today} — {slug} — bundle.md"
    bundle_path.write_text(bundle)

    payload = {
        "topic": topic,
        "today": today,
        "slug": slug,
        "bundle_path": str(bundle_path),
        "vault_baseline_notes": [h["path"] for h in hits],
        "vault_baseline_count": len(hits),
    }

    print("=== NOTEBOOKLM BUNDLE READY ===")
    print()
    print(f"Topic: {topic}")
    print(f"Vault baseline notes: {len(hits)}")
    print(f"Bundle saved to: {bundle_path}")
    print()
    print("=== USER MANUAL STEPS ===")
    print()
    print("1. Open notebooklm.google.com (sign in to personal Google account)")
    print("2. Create a new notebook (or open an existing one for this topic)")
    print("3. Click 'Add source' -> 'Paste text' and paste the contents of:")
    print(f"     {bundle_path}")
    print("4. Optionally add other sources (PDFs, URLs, Google Docs)")
    print("5. Once sources are added, paste this prompt into the chat:")
    print()
    print("--- prompt start ---")
    print(PROMPT_TEMPLATE.format(topic=topic))
    print("--- prompt end ---")
    print()
    print("6. When NotebookLM responds, copy the full response.")
    print("7. Run the next phase to save it to the vault:")
    print()
    print(f"   uv run -m scripts.research.notebooklm --save-response \\")
    print(f"     --topic \"{topic}\" --slug \"{slug}\"")
    print()
    print("   (When prompted, paste the response and press Ctrl-D.)")
    print()
    print("<<<NOTEBOOKLM_BUNDLE_PAYLOAD>>>")
    print(json.dumps(payload, indent=2))
    print("<<<NOTEBOOKLM_BUNDLE_PAYLOAD>>>")
    return 0


def save_response(topic: str, slug: str | None) -> int:
    if not slug:
        slug = slugify(topic)
    today = datetime.now().strftime("%Y-%m-%d")
    note_path = NOTEBOOKLM_DIR / f"{today} — {slug}.md"

    print("Paste the NotebookLM response below. Press Ctrl-D when done.", file=sys.stderr)
    response = sys.stdin.read().strip()
    if not response:
        print("ERROR: empty response", file=sys.stderr)
        return 1

    # Build the AI-first note
    hits = vault_scan(topic)
    body = NOTEBOOKLM_NOTE_TEMPLATE.format(
        date=today,
        topic=topic,
        slug=slug,
        baseline_count=len(hits),
        baseline_links="\n".join(f"- [[{h['path']}]]" for h in hits) or "- (none)",
        response=response,
    )
    NOTEBOOKLM_DIR.mkdir(parents=True, exist_ok=True)
    note_path.write_text(body)

    payload = {
        "topic": topic,
        "today": today,
        "slug": slug,
        "saved_note": str(note_path.relative_to(VAULT_PATH)),
        "vault_baseline_notes": [h["path"] for h in hits],
    }

    print(f"\n=== SAVED ===\n{note_path}\n")
    print("<<<NOTEBOOKLM_PROPAGATION_PAYLOAD>>>")
    print(json.dumps(payload, indent=2))
    print("<<<NOTEBOOKLM_PROPAGATION_PAYLOAD>>>")
    return 0


NOTEBOOKLM_NOTE_TEMPLATE = """---
date: {date}
type: research-notebooklm
tags:
  - research
  - notebooklm
  - source-grounded
ai-first: true
confidence: stated
---

# {topic}: NotebookLM synthesis ({date})

## For future Claude

NotebookLM source-grounded synthesis on "{topic}". Sources included the vault baseline bundle ({baseline_count} notes) plus any external sources Eugeniu added manually in NotebookLM. Output cites source titles in brackets where the underlying NotebookLM run included them. This is a parallel research track to `/research-deep` (Perplexity-based). NotebookLM is grounded in the user's own sources, not the open web. Confidence: stated (NotebookLM is reliable on the sources you give it; less reliable on synthesis breadth).

## Vault baseline that fed this notebook

{baseline_links}

## NotebookLM response (verbatim)

{response}

## Related

- [[NotebookLM]] - the tool
- [[Research/Deep/]] - the parallel Perplexity-based research track
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", help="topic to research")
    parser.add_argument("--save-response", action="store_true", help="finalize: save response from stdin")
    parser.add_argument("--slug", help="slug (only with --save-response)")
    args = parser.parse_args()

    if not args.topic:
        print("ERROR: --topic required", file=sys.stderr)
        return 2

    if args.save_response:
        return save_response(args.topic, args.slug)

    return emit_start(args.topic)


if __name__ == "__main__":
    sys.exit(main())
