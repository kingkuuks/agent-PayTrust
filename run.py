"""
Master orchestrator — runs all four agents in sequence.

Usage:
    python run.py                → starts scheduler, produces one video daily at 8am
    python run.py --once         → picks a random topic, produces one video, exits
    python run.py --dry-run      → picks topic + generates brief only, no render (no output folder)
    python run.py --review      → Strategist only: output/<ts>/brief.json, script.txt, STATUS=draft;
                                    opens script.txt in Notepad (Windows, blocking); exits (no assets)
    python run.py --review --review-folder output/YYYY-MM-DD_HH-mm   → draft written to that folder (not new timestamp)
    python run.py --review --review-skip-editor                         → omit blocking editor — edit script/brief then --continue
    python run.py --dry-run --review → same as --review (folder + editor; Strategist runs)
    python run.py --continue               → resume latest draft (pointer file or newest STATUS=draft);
                                              if script.txt differs from brief full_narration, script.txt wins; narration resync may refresh text overlays (brand.workflow.refresh_text_overlays_after_narration_resync); may write brief.backup.json
    python run.py --continue output/…/    → resume that folder explicitly
    python run.py --manual "topic"  → use this exact topic instead of picking one
    python run.py --topic-id 13   → run pipeline for topics.json id 13
    python run.py --force      → ignores used_topics history
"""

import sys
import os
import json
import random
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from agents.strategist import run_strategist
from agents.asset_builder import run_asset_builder
from agents.assembler import run_assembler
from tools.brief_validation import load_brief_json, validate_production_brief
from tools.output_paths import allocate_output_run_dir

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "agent.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("orchestrator")

# Active rotation source (Batch 3, ids 101-200). Batch 1-2 (topics.json) is
# exhausted but kept for explicit --topic-id lookups and history.
TOPICS_PATH = PROJECT_ROOT / "config" / "topics_batch3.json"
LEGACY_TOPICS_PATH = PROJECT_ROOT / "config" / "topics.json"
USED_TOPICS_PATH = PROJECT_ROOT / "data" / "used_topics.json"
CURRENT_REVIEW_POINTER = PROJECT_ROOT / "data" / "current_review_output.txt"


def _load_used_topics() -> list[int]:
    if USED_TOPICS_PATH.exists():
        return json.loads(USED_TOPICS_PATH.read_text(encoding="utf-8"))
    return []


def _save_used_topics(used: list[int]):
    USED_TOPICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USED_TOPICS_PATH.write_text(json.dumps(used), encoding="utf-8")


def pick_topic(force: bool = False) -> dict:
    """Pick a random topic. No topic repeats until all have been used at least once."""
    with open(TOPICS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    topics = data["topics"]

    used = [] if force else _load_used_topics()

    available = [t for t in topics if t["id"] not in used]
    if not available:
        logger.info("All %d topics used. Resetting rotation.", len(topics))
        used = []
        available = topics

    chosen = random.choice(available)
    used.append(chosen["id"])

    _save_used_topics(used)
    logger.info("Picked topic #%d: %s", chosen["id"], chosen["angle"][:80])
    return chosen


def get_topic_by_id(topic_id: int) -> dict:
    """Load a single topic by id, searching the active Batch 3 file then the legacy file."""
    for path in (TOPICS_PATH, LEGACY_TOPICS_PATH):
        if not path.is_file():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for t in data.get("topics", []):
            if t.get("id") == topic_id:
                return t
    raise ValueError(f"No topic with id={topic_id}")


def _rollback_last_picked_topic(topic_id: int | None):
    """If strategist or later steps fail after pick_topic, undo used_topics append."""
    if topic_id is None:
        return
    used = _load_used_topics()
    if used and used[-1] == topic_id:
        used.pop()
        _save_used_topics(used)
        logger.info("Rolled back topic %d from used_topics (pipeline failed before completion)", topic_id)


def _mark_topic_used(topic_id: int):
    used = _load_used_topics()
    if topic_id not in used:
        used.append(topic_id)
        _save_used_topics(used)


def _build_signals_from_topic(topic: dict) -> list[dict]:
    """
    Convert a topic dict into the signal format the Strategist expects.

    Branches on ``content_type`` (scam_story | safety_tip | win_story) so the
    strategist selects the right narrative_arc and scene-3 framing. The
    scene-3 prompt (forward_question / social_proof_prompt) is directed to the
    on-screen caption, not the narration.
    """
    content_type = topic.get("content_type", "scam_story")
    text = topic["angle"]
    if topic.get("specificity"):
        text += f". Details: {topic['specificity']}"
    core = topic.get("emotional_core") or topic.get("positive_core")
    if core:
        text += f". Emotional angle: {core}"

    if content_type == "win_story":
        text += (
            ". CONTENT TYPE: win_story. Use narrative_arc resolution_arc. "
            "This is a POSITIVE story where PayTrust escrow makes the deal succeed — "
            "funds held and released on confirmation, both sides satisfied. Do NOT frame it "
            "as a loss, scam, or regret, and keep the escrow flow accurate."
        )
        prompt = topic.get("social_proof_prompt")
        if prompt:
            text += f" Use this as the Scene 3 ON-SCREEN CAPTION (text_overlay), not narration: {prompt}"
    elif content_type == "safety_tip":
        text += (
            ". CONTENT TYPE: safety_tip. Use narrative_arc tutorial_arc. "
            "This is educational — show how to stay safe when paying, not a victim story. "
            "Helpful and confident, never preachy."
        )
        prompt = topic.get("forward_question")
        if prompt:
            text += f" Use this as the Scene 3 ON-SCREEN CAPTION (text_overlay), not narration: {prompt}"
    else:  # scam_story
        text += ". CONTENT TYPE: scam_story."
        if topic.get("narrative_arc"):
            text += f" Suggested narrative_arc: {topic['narrative_arc']}."
        if topic.get("discourse_question"):
            text += f" DISCOURSE QUESTION to provoke debate: {topic['discourse_question']}"

    # perspective is optional; only direct it when the topic sets it (no forced default).
    perspective = topic.get("perspective")
    if perspective == "buyer":
        text += " Tell this story from the BUYER's perspective."
    elif perspective == "both":
        text += " Tell this story showing BOTH buyer and seller perspectives."
    elif perspective == "seller":
        text += " Tell this story from the SELLER's perspective."

    return [{
        "source": "topic_bank",
        "text": text,
        "user": "system",
        "engagement": 999,
        "relevance_score": 10.0,
        "keyword": topic["angle"].split()[0],
    }]


def _write_status(output_dir: Path, status: str) -> None:
    (output_dir / "STATUS").write_text(status.strip() + "\n", encoding="utf-8")


def _write_current_review_pointer(path: Path) -> None:
    CURRENT_REVIEW_POINTER.parent.mkdir(parents=True, exist_ok=True)
    CURRENT_REVIEW_POINTER.write_text(str(path.resolve()) + "\n", encoding="utf-8")


def _newest_draft_folder_by_status_mtime() -> Path | None:
    """Pick output/* with STATUS containing draft, by STATUS file mtime."""
    output_root = PROJECT_ROOT / "output"
    if not output_root.is_dir():
        return None
    best_path: Path | None = None
    best_t = -1.0
    for child in output_root.iterdir():
        if not child.is_dir():
            continue
        status_file = child / "STATUS"
        if not status_file.is_file():
            continue
        try:
            if status_file.read_text(encoding="utf-8").strip() != "draft":
                continue
        except OSError:
            continue
        t = status_file.stat().st_mtime
        if t > best_t:
            best_t = t
            best_path = child
    return best_path


def resolve_implicit_continue_folder() -> Path | None:
    """Bare `--continue`: pointer file, else newest draft by STATUS mtime. Clears stale pointer."""
    line = None
    if CURRENT_REVIEW_POINTER.exists():
        text = CURRENT_REVIEW_POINTER.read_text(encoding="utf-8").strip()
        if text:
            line = text.splitlines()[0].strip()

    if line:
        p = Path(line)
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        else:
            p = p.resolve()
        if p.is_dir() and (p / "brief.json").is_file():
            return p
        try:
            CURRENT_REVIEW_POINTER.unlink()
        except OSError:
            CURRENT_REVIEW_POINTER.write_text("", encoding="utf-8")

    return _newest_draft_folder_by_status_mtime()


def _open_file_blocking(editor_path: Path) -> None:
    """Open a file in a blocking editor so the operator can edit before continuing."""
    p = editor_path.resolve()
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "start", "/wait", "notepad", str(p)], check=False)
    elif sys.platform == "darwin":
        subprocess.run(["open", "-W", str(p)], check=False)
    else:
        logger.info(
            "Non-Windows/macOS: open this file in your editor, then return here and press Enter: %s",
            p,
        )
        input()


def run_pipeline(
    dry_run: bool = False,
    force: bool = False,
    manual_topic: str | None = None,
    topic_id: int | None = None,
):
    """Execute the full agent pipeline."""
    start = datetime.now()
    logger.info("=" * 60)
    logger.info("Pipeline started at %s", start.isoformat())
    logger.info("=" * 60)

    rollback_id: int | None = None
    explicit_topic_id: int | None = None

    if manual_topic:
        logger.info("Using manual topic: %s", manual_topic)
        trends = [{
            "source": "manual",
            "text": manual_topic,
            "user": "operator",
            "engagement": 999,
            "relevance_score": 10.0,
            "keyword": manual_topic.split()[0] if manual_topic else "payment",
        }]
    elif topic_id is not None:
        topic = get_topic_by_id(topic_id)
        explicit_topic_id = topic_id
        logger.info("Using topic id %d: %s", topic_id, topic["angle"][:80])
        trends = _build_signals_from_topic(topic)
    else:
        topic = pick_topic(force=force)
        rollback_id = topic["id"]
        trends = _build_signals_from_topic(topic)

    # Agent 2: Strategist
    logger.info(">>> Agent 2: Strategist")
    try:
        brief = run_strategist(trends)
    except Exception as e:
        logger.error("Strategist failed: %s", e, exc_info=True)
        _rollback_last_picked_topic(rollback_id)
        return None

    logger.info("Strategist returned brief: %r", brief.get("hook"))

    if dry_run:
        logger.info("DRY RUN complete. Brief:")
        logger.info(json.dumps(brief, indent=2, ensure_ascii=False))
        print(f"\n=== DRY RUN ===")
        print(f"Hook: {brief.get('hook')}")
        print(f"Trend: {brief.get('chosen_trend')}")
        print(f"Scenes: {len(brief.get('scenes', []))}")
        return brief

    # Agent 3: Asset Builder — return value is the single config consumed by Assembler
    logger.info(">>> Agent 3: Asset Builder")
    try:
        config, _synced_pipeline = run_asset_builder(brief)
    except Exception as e:
        logger.error("Asset Builder failed: %s", e, exc_info=True)
        _rollback_last_picked_topic(rollback_id)
        return None

    logger.info("Asset Builder returned %d scenes", config.get("scene_count", 0))

    # Agent 4: Assembler
    logger.info(">>> Agent 4: Assembler")
    try:
        video_path = run_assembler(config)
    except Exception as e:
        logger.error("Assembler failed: %s", e, exc_info=True)
        _rollback_last_picked_topic(rollback_id)
        return None

    if explicit_topic_id is not None:
        _mark_topic_used(explicit_topic_id)

    elapsed = (datetime.now() - start).total_seconds()
    logger.info("=" * 60)
    logger.info("Pipeline complete in %.1f seconds", elapsed)
    logger.info("Video: %s", video_path)
    logger.info("=" * 60)
    print(f"\nVideo saved: {video_path}")
    return video_path


def run_review(
    force: bool = False,
    manual_topic: str | None = None,
    topic_id: int | None = None,
    review_output_dir: Path | None = None,
    skip_editor: bool = False,
) -> bool:
    """
    Strategist only: write brief.json + script.txt, STATUS=draft; optional blocking editor opens script.txt.

    If ``review_output_dir`` is set, that folder is used; otherwise allocates output/<timestamp>/.
    """
    rollback_id: int | None = None

    if manual_topic:
        logger.info("Using manual topic: %s", manual_topic)
        trends = [{
            "source": "manual",
            "text": manual_topic,
            "user": "operator",
            "engagement": 999,
            "relevance_score": 10.0,
            "keyword": manual_topic.split()[0] if manual_topic else "payment",
        }]
    elif topic_id is not None:
        topic = get_topic_by_id(topic_id)
        logger.info("Using topic id %d: %s", topic_id, topic["angle"][:80])
        trends = _build_signals_from_topic(topic)
    else:
        topic = pick_topic(force=force)
        rollback_id = topic["id"]
        trends = _build_signals_from_topic(topic)

    logger.info(">>> Agent 2: Strategist (review mode — stops after brief)")
    try:
        brief = run_strategist(trends)
    except Exception as e:
        logger.error("Strategist failed: %s", e, exc_info=True)
        _rollback_last_picked_topic(rollback_id)
        return False

    if review_output_dir is not None:
        output_dir = review_output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = allocate_output_run_dir(PROJECT_ROOT)
        output_dir.mkdir(parents=True, exist_ok=True)
    brief_path = output_dir / "brief.json"
    brief_path.write_text(
        json.dumps(brief, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    script_path = output_dir / "script.txt"
    script_path.write_text(brief.get("full_narration", ""), encoding="utf-8")
    _write_status(output_dir, "draft")
    _write_current_review_pointer(output_dir)

    logger.info(
        "Draft written to %s + %s — %s",
        brief_path.name,
        script_path.name,
        "opening script editor" if not skip_editor else "edit script.txt then run --continue",
    )
    print(f"\nReview folder: {output_dir}")
    print(
        "Edit script.txt (opens by default); --continue uses it when it differs from brief full_narration and reapportions scenes for TTS."
    )
    print("Edit overlays/prompts in brief.json separately if needed, save, close the editor, then run:")
    print("  python run.py --continue")
    print("  (or: python run.py --continue \"%s\")" % output_dir)
    if skip_editor:
        print(
            "\n(--review-skip-editor) Edit script.txt (or brief.json), save, "
            "then run --continue before building assets.",
            flush=True,
        )
    else:
        _open_file_blocking(script_path)
    return True


def run_continue(output_dir: Path) -> bool:
    """
    Load brief.json from disk (does not run Strategist), validate, build assets, assemble, STATUS=complete.

    When ``script.txt`` is present and non-empty, if its normalized text differs from ``full_narration``,
    ``script.txt`` replaces ``full_narration`` before the asset builder (same whitespace rules as narration sync).
    """
    out = output_dir.resolve()
    if not out.is_dir():
        logger.error("Not a directory: %s", out)
        print(f"Error: not a directory: {out}", file=sys.stderr)
        return False

    brief_path = out / "brief.json"
    if not brief_path.is_file():
        logger.error("Missing brief.json: %s", brief_path)
        print(f"Error: missing brief.json in {out}", file=sys.stderr)
        return False

    try:
        brief = load_brief_json(brief_path)
    except json.JSONDecodeError as e:
        print(str(e), file=sys.stderr)
        print(
            "Fix the JSON syntax in your editor and run --continue again.",
            file=sys.stderr,
        )
        return False

    try:
        validate_production_brief(brief)
    except ValueError as e:
        print(f"Brief validation failed: {e}", file=sys.stderr)
        return False

    script_path = out / "script.txt"
    if script_path.is_file():
        from tools.narration_sync import normalize_text

        script_text = normalize_text(script_path.read_text(encoding="utf-8"))
        fn_existing = normalize_text(brief.get("full_narration", ""))
        if script_text and script_text != fn_existing:
            brief["full_narration"] = script_text
            logger.info(
                "script.txt superseded brief.json full_narration — resync will follow"
            )
            try:
                validate_production_brief(brief)
            except ValueError as e:
                print(f"Brief validation failed after applying script.txt: {e}", file=sys.stderr)
                return False

    original_brief_bytes = brief_path.read_bytes()

    logger.info(">>> Agent 3: Asset Builder (continue from %s)", out)
    try:
        config, _narration_resplit = run_asset_builder(
            brief,
            output_dir=out,
            brief_path=brief_path,
            pre_run_brief_bytes=original_brief_bytes,
        )
    except Exception as e:
        logger.error("Asset Builder failed: %s", e, exc_info=True)
        return False

    logger.info(">>> Agent 4: Assembler (skip_brief_write=True — preserves hand-edited brief fields on disk)")
    try:
        video_path = run_assembler(config, skip_brief_write=True)
    except Exception as e:
        logger.error("Assembler failed: %s", e, exc_info=True)
        return False

    _write_status(out, "complete")
    print(f"\nVideo saved: {video_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="PayTrust Content Agent")
    parser.add_argument("--once", action="store_true", help="Run once, then exit")
    parser.add_argument("--dry-run", action="store_true", help="Brief only, no render (no output folder unless --review)")
    parser.add_argument("--review", action="store_true",
                        help="Strategist only: write output folder + STATUS=draft, open script.txt in editor, exit")
    parser.add_argument(
        "--review-folder",
        type=str,
        metavar="FOLDER",
        default=None,
        help="With --review: write draft to this folder (relative paths are under paytrust-agent/)",
    )
    parser.add_argument(
        "--review-skip-editor",
        action="store_true",
        help="With --review: do not launch the blocking editor; edit script.txt yourself, then --continue",
    )
    parser.add_argument(
        "--continue",
        dest="continue_dir",
        nargs="?",
        const="",
        metavar="FOLDER",
        default=None,
        help=(
            "Resume from a review folder (optional path; omit path for last draft). "
            "If script.txt exists and differs from full_narration, script.txt replaces it first. "
            "If full_narration then differs from scene narrations, scenes are reshaped for TTS "
            "(and brand.workflow.refresh_text_overlays_after_narration_resync may regenerate text overlays 0–3); "
            "brief.backup.json preserves the prior brief.json."
        ),
    )
    parser.add_argument("--force", action="store_true", help="Ignore used_topics history (pick from all topics)")
    parser.add_argument("--manual", type=str, metavar="TOPIC",
                        help="Use this exact topic instead of picking one")
    parser.add_argument("--topic-id", type=int, metavar="ID", default=None,
                        help="Run pipeline for this id from config/topics.json")
    args = parser.parse_args()

    if args.review_skip_editor and not args.review:
        parser.error("--review-skip-editor requires --review")
    if args.review_folder and not args.review:
        parser.error("--review-folder requires --review")

    if args.manual:
        args.once = True
    if getattr(args, "topic_id", None) is not None:
        args.once = True

    if args.continue_dir is not None:
        if args.review or args.dry_run or args.once:
            parser.error("--continue cannot be combined with --review, --dry-run, or --once")
        if args.continue_dir != "":
            raw = Path(args.continue_dir)
            out = raw.resolve() if raw.is_absolute() else (PROJECT_ROOT / raw).resolve()
            if not out.is_dir():
                print(f"Error: not a directory: {out}", file=sys.stderr)
                sys.exit(1)
            ok = run_continue(out)
        else:
            resolved = resolve_implicit_continue_folder()
            if resolved is None:
                print(
                    "Could not resolve a draft folder. Run --review first, or pass a folder:\n"
                    "  python run.py --continue output\\YYYY-MM-DD_26 v",
                    file=sys.stderr,
                )
                sys.exit(1)
            ok = run_continue(resolved)
        sys.exit(0 if ok else 1)

    if args.review:
        review_out_arg: Path | None = None
        if args.review_folder:
            rf = Path(args.review_folder)
            review_out_arg = rf.resolve() if rf.is_absolute() else (PROJECT_ROOT / rf).resolve()
        ok = run_review(
            force=args.force,
            manual_topic=args.manual,
            topic_id=args.topic_id,
            review_output_dir=review_out_arg,
            skip_editor=args.review_skip_editor,
        )
        sys.exit(0 if ok else 1)

    if args.once or args.dry_run:
        run_pipeline(
            dry_run=args.dry_run,
            force=args.force,
            manual_topic=args.manual,
            topic_id=args.topic_id,
        )
    else:
        import schedule
        import time

        logger.info("Scheduler started. Videos will be produced daily at 08:00.")
        schedule.every().day.at("08:00").do(run_pipeline, force=args.force)

        # Run once immediately on startup
        run_pipeline(force=args.force)

        while True:
            schedule.run_pending()
            time.sleep(60)


if __name__ == "__main__":
    main()
