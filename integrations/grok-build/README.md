# Groktimized Grok Build

This directory contains the narrow, reproducible patch used by the public
Groktimizer installer. It is based on `xai-org/grok-build` commit
`8a14c91d88875a831a38b3a066b1683116bcb31c`.

The patch gives the plain `Groktimized 2` model name an actual RGB purple text
style in both full and minimal render modes, and keeps it first in `/model`.
The installer registers both `Groktimized 2` (the accelerated deployment) and
`Grok 2` (the standard deployment) as normal catalog entries in
`~/.grok/config.toml`. A second narrow compatibility patch teaches the
text-only Grok-2 llama.cpp chat template Grok Build's tool schemas, preserves
tool-result history as text, and converts its streamed `<tool_call>` envelopes
back into native Grok Build tool calls. It activates only for the upstream
model IDs `grok-2` and `grok-2-fast`; every other model keeps stock behavior.

The two deployed Grok 2 llama.cpp chat templates do not reliably emit usable
tool calls even with the compatibility prompt. For tool-bearing turns, the
patched build therefore uses `grok-4.5` on the official xAI API as an explicit
tool-runtime fallback whenever `XAI_API_KEY` or `XAI_API_KEY_2` is available.
Both keys are rotated when present. They may be exported normally or placed in
the current project's `.env`; the patch does not persist or log them. Set
`GROKTIMIZED_DISABLE_TOOL_PLANNER=1` to force the text-only path, or override
`GROKTIMIZED_TOOL_PLANNER_MODEL` and `GROKTIMIZED_TOOL_PLANNER_BASE_URL` for a
different compatible planner. Plain chat without tools still uses the selected
Grok 2 endpoint directly. There are no task-specific or canned responses.

`scripts/build_groktimized_grok.sh` clones the pinned source, applies both
patches, runs their focused tests and the release build, then creates the
checksummed release archive. The archive includes the upstream license and
third-party notices.
