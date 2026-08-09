# Groktimized Grok Build UI

This directory contains the narrow, reproducible patch used by the public
Groktimizer installer. It is based on `xai-org/grok-build` commit
`8a14c91d88875a831a38b3a066b1683116bcb31c` and changes presentation only.

The patch gives the plain `Groktimized 2` model name an actual RGB purple text
style in both full and minimal render modes, and keeps it first in `/model`.
The model remains a normal Grok Build catalog entry configured in
`~/.grok/config.toml`.

`scripts/build_groktimized_grok.sh` clones the pinned source, applies the patch,
runs its focused test and release build, then creates the checksummed release
archive. The archive includes the upstream license and third-party notices.
