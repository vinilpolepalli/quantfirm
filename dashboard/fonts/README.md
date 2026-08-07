Self-hosted latin subsets, both under the SIL Open Font License 1.1:

  instrument-serif-400.woff2   Instrument Serif — Rodrigo Fuenzalida, Jordan Egstad
  jetbrains-mono-{400,500,700}.woff2
                               JetBrains Mono — JetBrains

Self-hosted rather than linked from a CDN so the dashboard has no third-party
runtime dependency and renders identically offline.

Static weights, not the variable file: headless Chromium's --print-to-pdf does
not embed a variable font, so the daily PDF reports silently fell back to a
system mono. Three static instances fix that at ~21KB each.
