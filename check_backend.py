#!/usr/bin/env python3
"""Make one tiny structured request to a deliberately configured backend."""
import argparse
import llm_mkv_translate as app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--backend", choices=["openai", "agy", "codex", "claude-code"])
    parser.add_argument("--model")
    args = parser.parse_args()
    try:
        config = app.ayarlar(args.config)
        for key in ("backend", "model"):
            if getattr(args, key):
                config[key] = getattr(args, key)
        ok, message = app.backend_check(config)
        print("OK" if ok else "FAIL: " + message)
        return 0 if ok else 1
    except (ValueError, OSError, app.ModelHatasi) as error:
        print("FAIL: " + app._redact(str(error)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
