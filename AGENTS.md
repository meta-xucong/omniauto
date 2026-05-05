# Codex Project Rules

## Windows Encoding Safety

This project may contain Chinese text. Treat all source files as UTF-8.

- Prefer `apply_patch` for manual source edits.
- Do not rewrite source files with Windows PowerShell 5.1 text pipelines such as:
  - `Get-Content file | Set-Content file`
  - `Out-File`
  - `>`
  - `>>`
- This applies especially to `.js`, `.ts`, `.tsx`, `.vue`, `.html`, `.css`, `.json`, `.py`, and `.md` files.
- If a bulk rewrite is required, explicitly read and write UTF-8 without BOM, or use Node.js `fs` APIs with `utf8`.
- After editing frontend JavaScript or TypeScript files, run `node --check`, lint, or the relevant project test command.
