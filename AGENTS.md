# Repository Guidelines

## Project Structure & Module Organization

This repository is currently an empty scaffold. No application source, tests, assets, dependency manifests, or build configuration are present. Existing hidden directories are `.git/`, `.agents/`, `.codex/`, and `.aws/`.

When adding the first implementation, use the selected framework's standard layout. Otherwise, place source code in `src/`, tests in `tests/`, and static resources in `assets/`. Add a `README.md` explaining the project's purpose and directory structure. Keep application files out of the existing hidden directories.

## Build, Test, and Development Commands

No build, test, or local development commands are configured yet. Do not assume commands such as `npm test` or `make build` are available.

- `ls -la` lists the current workspace, including hidden directories.
- `rg --files` lists ordinary project files after they are added.

When introducing tooling, include the dependency manifest and appropriate lockfile. Document exact installation, development, build, and test commands in `README.md`, then update this guide.

## Coding Style & Naming Conventions

No language, formatter, or linter has been established. Adopt the chosen language's standard conventions, use consistent indentation, and avoid mixing tabs and spaces. Configure formatting and linting alongside the first source files.

Use descriptive names for modules and functions. Keep naming consistent within each language and group related functionality together.

## Testing Guidelines

No testing framework or coverage requirement exists yet. Introduce automated tests with the first executable behavior, covering expected outcomes, edge cases, and failure paths. Follow the selected framework's test naming conventions and document how to run the suite.

## Commit & Pull Request Guidelines

Git history is unavailable in this workspace, so no existing commit convention can be inferred. Use concise, imperative commit subjects, such as `Add initial project structure`, and keep each commit focused.

Pull requests should explain the purpose, summarize changes, and report validation performed. Link relevant issues and include screenshots for visible interface changes. Identify any setup steps needed to reproduce the result.

## Security & Configuration

Never commit credentials, tokens, or local secrets. Provide placeholder configuration examples and ignore local configuration files when adding version control rules.
