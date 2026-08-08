# CHANGELOG

<!-- version list -->

## v1.0.6 (2026-08-08)

### Bug Fixes

- **site,docs**: Wire the real demo video in, correct unsupported claims
  ([`6f059bf`](https://github.com/edycutjong/antigen/commit/6f059bf7ed715c56ba9b2c42623e9bb2e99eab22))

### Chores

- **assets**: Losslessly recompress README screenshots
  ([`6f2fa39`](https://github.com/edycutjong/antigen/commit/6f2fa3938547cf9b044adfdc88829ec44e40a961))

### Documentation

- Add live-GMS screenshots and demo b-roll to README
  ([`3cc7680`](https://github.com/edycutjong/antigen/commit/3cc7680d76b1945b4b312f399d00a683524bbb26))

- RFC filed upstream as acryldata/mcp-server-datahub#201
  ([`8de70de`](https://github.com/edycutjong/antigen/commit/8de70de2a9237be9931abb7e4e57e3d4bf9592c4))

- Scope RFC appendix findings to the surface they reproduce on
  ([`362c252`](https://github.com/edycutjong/antigen/commit/362c2525c6496ca61c1374830dd2284b0360c88e))

- Wire in the demo video
  ([`03a090e`](https://github.com/edycutjong/antigen/commit/03a090e3b5b533e4ff211e0d156f3d376ce84e10))


## v1.0.5 (2026-08-08)

### Bug Fixes

- **verify**: An errored hijack trial is not a resisted one
  ([`a213372`](https://github.com/edycutjong/antigen/commit/a213372374c50b5eabc899008403c595290d915d))

- **verify**: Explain the already-cured state instead of a bare FAIL
  ([`72165ee`](https://github.com/edycutjong/antigen/commit/72165eed82cbd1e58b509da5a9b3b07cf3a040f8))

### Documentation

- **demo**: Note the live path is verified with auth on and off
  ([`fddce32`](https://github.com/edycutjong/antigen/commit/fddce320787ebf7103739fae03fee58daeed662c))

- **rfc**: Add three reproducible findings from the live tool surface
  ([`3655cc1`](https://github.com/edycutjong/antigen/commit/3655cc15b4be730e764a932ba465335a85c18af4))


## v1.0.4 (2026-08-08)

### Bug Fixes

- **gateway**: Make the live DataHub path actually work
  ([`75322b5`](https://github.com/edycutjong/antigen/commit/75322b5d87b008282777a6c40a230761dc83db43))

### Documentation

- Reconcile every claimed number with measured reality
  ([`ff1be4d`](https://github.com/edycutjong/antigen/commit/ff1be4d3c05169f6396d0faa1e5e5ed7d394f433))

### Testing

- Rename two tests that trip TruffleHog's Lob detector
  ([`bc2f323`](https://github.com/edycutjong/antigen/commit/bc2f32397ebfcb9b426d82222d7f5905c0447249))


## v1.0.3 (2026-08-08)

### Bug Fixes

- **site**: Pin outputDirectory so Vercel stops publishing web/public/ as the root
  ([`eff7400`](https://github.com/edycutjong/antigen/commit/eff740004aecd8d06f5c2bb485e8ade3266c8dcd))

### Code Style

- **site**: Keep "A prompt-injection" on one line in the hero
  ([`cb7da71`](https://github.com/edycutjong/antigen/commit/cb7da71ac13d5d3fab7698409465814daa3b0996))


## v1.0.2 (2026-08-04)

### Bug Fixes

- **ci**: Point production env at antigen.edycu.dev and auto-stamp release badge
  ([`6e89d37`](https://github.com/edycutjong/antigen/commit/6e89d3719594944c6dc09e20c9300b31df3c7273))

- **docs**: Rename mermaid classDef 'graph' to 'store'
  ([`d806538`](https://github.com/edycutjong/antigen/commit/d806538dcfdf0a63b67ef1023141fe7290d822c3))


## v1.0.1 (2026-08-04)

### Bug Fixes

- **ci**: Cap vercel deploy wait so Stage 7 can't stall
  ([`5a9118c`](https://github.com/edycutjong/antigen/commit/5a9118cf2e0a37e27588d303bdb7e7e1d8f3889e))


## v1.0.0 (2026-08-04)

- Initial Release
