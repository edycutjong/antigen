# CHANGELOG


## v0.1.0 (2026-08-04)

### Bug Fixes

- **ci**: Set semantic-release build_command to empty string
  ([`e2804ab`](https://github.com/edycutjong/antigen/commit/e2804abf9cf9df1570bdb32533e010b93215e0c6))

PSR v9 rejects a boolean build_command; an empty string disables the package build so the release
  job only versions, changelogs, and tags.

### Features

- Initial build — Antigen prompt-injection immune system for DataHub
  ([`20f0d14`](https://github.com/edycutjong/antigen/commit/20f0d14dda824b63ce4f78e57f7516085db693f1))

Static marketing site (web/), core detector/engine, verify + bench proofs, multi-stage CI/CD with
  semantic-release and Vercel prod deploy of web/.
