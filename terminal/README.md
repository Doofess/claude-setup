`profile.json` is this PC's measured Windows Terminal look (2026-10-23): the font face and cell height, and the built-in `Campbell` colour scheme.
`install.ps1` writes it into `profiles.defaults` of Windows Terminal's `settings.json` (`-KeepFont` and `-KeepScheme` keep the machine's own) and its `Same experience` step checks it.
The status bar's and the `session-cards` mod's colours are the scheme's own 16, and the icons need the Nerd Font's glyph widths, so a different scheme or font is a different screen.

