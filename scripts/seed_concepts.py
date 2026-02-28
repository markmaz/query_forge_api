from __future__ import annotations

import argparse

from app.services.semantic.concept_seed import ConceptSeedService


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotent bootstrap for core semantic concepts used by slot-driven planning."
    )
    parser.add_argument("--vertical", default="education", help="Vertical namespace to seed (default: education)")
    args = parser.parse_args()

    svc = ConceptSeedService()
    out = svc.ensure_seeded(args.vertical)
    print(
        {
            "vertical_norm": out.get("vertical_norm"),
            "concepts_processed": out.get("concepts_processed"),
            "aliases_processed": out.get("aliases_processed"),
        }
    )


if __name__ == "__main__":
    main()
