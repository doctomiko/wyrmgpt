import argparse
import json
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.config import (
    load_deployment_defs,
    load_provider_defs,
    load_summary_config,
)
from server.context import _get_prompt
from server.db import (
    db_session,
    db_get_transcript_for_summary,
    init_schema,
    db_save_conversation_summary_artifact,
)
from server.providers.base import ChatProvider, ModelCatalogProvider
from server.providers.openai_provider import OpenAIProvider
from server.providers.registry import ProviderRegistry
from server.providers.types import ModelCatalog, ModelInput, ProviderDef
from server.summary_helper import summarize_conversation_text


def load_model_catalog() -> ModelCatalog:
    path = ROOT / "server" / "model_catalog.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print("Failed to load model_catalog.json:", e)
    return {}


def build_provider_registry(model_catalog: ModelCatalog) -> ProviderRegistry:
    providers = load_provider_defs()
    deployments = load_deployment_defs()

    compat_factory = lambda provider_def: OpenAIProvider(provider_def, model_catalog=model_catalog)

    chat_factories: dict[str, Callable[[ProviderDef], ChatProvider]] = {
        "openai": compat_factory,
        "ollama": compat_factory,
        "lmstudio": compat_factory,
        "openai_compat": compat_factory,
    }

    catalog_factories: dict[str, Callable[[ProviderDef], ModelCatalogProvider]] = {
        "openai": compat_factory,
        "ollama": compat_factory,
        "lmstudio": compat_factory,
        "openai_compat": compat_factory,
    }

    return ProviderRegistry(
        providers=providers,
        deployments=deployments,
        chat_factories=chat_factories,
        catalog_factories=catalog_factories,
    )


def list_conversation_ids(include_archived: bool = False) -> list[str]:
    with db_session() as conn:
        if include_archived:
            rows = conn.execute(
                "SELECT id FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM conversations WHERE archived = 0 ORDER BY updated_at DESC"
            ).fetchall()
    return [r["id"] for r in rows]


def has_summary(conn, conversation_id: str) -> bool:
    aid_row = conn.execute(
        """
        SELECT id, summary_text
        FROM artifacts
        WHERE source_kind = 'conversation:summary'
          AND source_id = ?
          AND is_deleted = 0
        """,
        (conversation_id,),
    ).fetchone()
    return bool(aid_row and (aid_row["summary_text"] or "").strip())


def main() -> None:
    sum_cfg = load_summary_config()
    model_catalog = load_model_catalog()
    registry = build_provider_registry(model_catalog)

    ap = argparse.ArgumentParser()
    ap.add_argument("--include-archived", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--deployment",
        default="summary_default",
        help="Deployment id to use for summarization (default: summary_default)",
    )
    ap.add_argument(
        "--model",
        default="",
        help="Deprecated alias for deployment id. Prefer --deployment.",
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args()

    requested = (args.deployment or "").strip() or "summary_default"
    if args.model and not args.deployment:
        requested = args.model.strip()

    if requested not in registry.deployments:
        raise RuntimeError(
            f"Summary deployment '{requested}' is not configured. "
            f"Use a deployment id from [deployments], typically 'summary_default'."
        )

    target = registry.resolve_deployment_for_capability(
        "chat",
        requested,
        fallback_to_default_chat=False,
    )
    provider = registry.get_chat_provider(target)

    print("Running init_schema...")
    init_schema()
    print("Done.")

    ids = list_conversation_ids(include_archived=args.include_archived)
    if args.limit is not None:
        ids = ids[: args.limit]

    print(
        f"Summarizing {len(ids)} conversations using deployment={target.id} "
        f"provider={target.provider_id} model={target.model} force={args.force}"
    )

    ok = 0
    skip = 0
    fail = 0

    system_prompt = _get_prompt(
        default_prompt=sum_cfg.summary_conversation_prompt,
        filepath=sum_cfg.summary_conversation_prompt_file,
        cfg_default="SUMMARY_CONVO_PROMPT",
        cfg_filepath="SUMMARY_CONVO_PROMPT_FILE",
    )

    def complete_via_provider(system_prompt_text: str, user_prompt_text: str, max_output_tokens: int) -> str:
        model_input: ModelInput = [
            {"role": "system", "content": system_prompt_text},
            {"role": "user", "content": user_prompt_text},
        ]
        result = provider.complete(
            target,
            model_input,
            request_options={"max_output_tokens": max_output_tokens},
        )
        return (result.text or "").strip()

    for i, cid in enumerate(ids, start=1):
        try:
            with db_session() as conn:
                if (not args.force) and has_summary(conn, cid):
                    skip += 1
                    print(f"[{i}/{len(ids)}] skip {cid} (summary exists)")
                    continue

            try:
                title, transcript = db_get_transcript_for_summary(cid)
            except ValueError as e:
                skip += 1
                print(f"[{i}/{len(ids)}] skip {cid} ({e})")
                continue
            except KeyError as e:
                skip += 1
                print(f"[{i}/{len(ids)}] skip {cid} ({e})")
                continue

            print(
                f"[{i}/{len(ids)}] summarizing {cid} "
                f"title={title!r} transcript_chars={len(transcript)}"
            )

            summary_text = summarize_conversation_text(
                complete_fn=complete_via_provider,
                model=target.model,
                title=title,
                transcript=transcript,
                cfg=sum_cfg,
                system_prompt=system_prompt,
            )

            summary_text = (summary_text or "").strip()
            if not summary_text:
                raise RuntimeError(
                    f"empty summary (title={title!r}, transcript_chars={len(transcript)})"
                )

            db_save_conversation_summary_artifact(cid, summary_text, target.model)

            ok += 1
            print(f"[{i}/{len(ids)}] ok   {cid}  ({len(summary_text)} chars)")
            if args.sleep:
                time.sleep(args.sleep)

        except Exception as e:
            fail += 1
            print(f"[{i}/{len(ids)}] FAIL {cid}: {e!r}")

    print(json.dumps({"ok": ok, "skipped": skip, "failed": fail}, indent=2))


if __name__ == "__main__":
    main()