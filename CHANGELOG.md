# CHANGELOG

<!-- version list -->

## v1.3.1 (2026-08-09)

### Bug Fixes

- **safety**: Infra failures exit 2, close the entity-scope fail-open, add span excision
  ([`6f9dbd4`](https://github.com/edycutjong/antigen/commit/6f9dbd4c5309c212d379414d4580576d31dccb2a))

- **web**: Remove a fabricated exploit from the public deck and landing page
  ([`95539d6`](https://github.com/edycutjong/antigen/commit/95539d6ae9c3c00fc096d9be374cbbee01daf08e))

### Documentation

- Report the hijack number the transcript actually supports, and fix four checkable contradictions
  ([`1ef1ac4`](https://github.com/edycutjong/antigen/commit/1ef1ac41528e52bff42ecbedc97d76e9c3fd62e0))

- Retract four unevidenced claims, correct the SDK advice, cut the README to 1,370 lines
  ([`e42741d`](https://github.com/edycutjong/antigen/commit/e42741df4de958c69408c6d8da60101a348d9126))

- Scope the demo video to the run it was recorded from
  ([`a2934d7`](https://github.com/edycutjong/antigen/commit/a2934d78da29fcf32c8b8e08bcedf2653ece4c87))

- **evidence**: Measure the false-positive rate on 38,031 descriptions we did not write
  ([`377ba92`](https://github.com/edycutjong/antigen/commit/377ba92c727ce545670f9030c65381d5c4d86558))

- **evidence**: Prove the incident-ledger overwrite against a real GMS
  ([`b4daa52`](https://github.com/edycutjong/antigen/commit/b4daa5235ec5562330e0bc2041b2a81bfe1be764))

- **evidence**: The hijack A/B, actually run and actually recorded
  ([`34c0d71`](https://github.com/edycutjong/antigen/commit/34c0d71b67ed30a33b4a23000e58c9fde3e20ce9))

### Testing

- **hijack**: Capture the A/B as an auditable transcript, not a summary line
  ([`971cea3`](https://github.com/edycutjong/antigen/commit/971cea3c31aa9b88b877081c7cd656a6dab4275f))


## v1.3.0 (2026-08-09)

### Bug Fixes

- **docs**: Withdraw the `total: 30 while returning 26` claim — a truncation misread
  ([`112ffaf`](https://github.com/edycutjong/antigen/commit/112ffafaeeccb1e09dce40d705719c3891e8efff))

### Documentation

- Reconcile the Metadata Tests survey with the new Actions concession
  ([`a4bdc9e`](https://github.com/edycutjong/antigen/commit/a4bdc9e9c040b7e7b3377c33bed27834933c925a))

- **evidence**: Re-capture the live transcript against the code that ships
  ([`cc085de`](https://github.com/edycutjong/antigen/commit/cc085de257b3dafcbe19ff6c12e9f6591dac852b))

### Features

- **seed**: Add --scale N to seed a catalog past the GMS's 50-row search page
  ([`dab5818`](https://github.com/edycutjong/antigen/commit/dab5818ec1f8efdc6938d761a59f21b0e5a0553c))


## v1.2.1 (2026-08-09)

### Bug Fixes

- **cli**: Fail closed in rescan, cure, certify and blast-radius too
  ([`95ae0be`](https://github.com/edycutjong/antigen/commit/95ae0be71cf0ad900fe67bef533b7042ac58e889))

- **gateway**: Report a successful-but-empty document enumeration
  ([`4a3e171`](https://github.com/edycutjong/antigen/commit/4a3e1717571ae6ed60f313a1c05a2215117d0ab7))

- **scan**: Make the doc pre-filter a real superset of the detector
  ([`f05453a`](https://github.com/edycutjong/antigen/commit/f05453a7585d077f341e95910b0851ea0790bd48))

- **web**: Remove the invented showcase-datapack figure and stale counts
  ([`aaf2444`](https://github.com/edycutjong/antigen/commit/aaf2444b200769a943afd49384e7d6f3e4cbc544))

### Continuous Integration

- Distinguish a Vercel quota skip from a deploy failure
  ([`3d99991`](https://github.com/edycutjong/antigen/commit/3d99991a3425368b1592204001cd4bd93104e8eb))

### Documentation

- Correct three claims refuted by the sources they cite
  ([`6c4e1cc`](https://github.com/edycutjong/antigen/commit/6c4e1cc49bdb97fcf0f038a5cad53e0ba24644a2))

- **transcript**: Rename the stale eight_claimed_agent_tools label
  ([`1faf051`](https://github.com/edycutjong/antigen/commit/1faf0517384539b3d0f3c61ca0e7eaad6fe8d20f))


## v1.2.0 (2026-08-09)

### Bug Fixes

- **cure**: Converge the KB-document cure, stamp a real lastScanned, skip re-certify
  ([`a7e82be`](https://github.com/edycutjong/antigen/commit/a7e82bea5e9532416fadf783abd8e2fdf52b22b5))

### Documentation

- Least-privilege operator guidance + an example CI workflow for adopters
  ([`51e126b`](https://github.com/edycutjong/antigen/commit/51e126ba9fffacb0f9c2324fdae98a4188565893))

- True up the test count to 130 and name the new suites
  ([`b37a3d8`](https://github.com/edycutjong/antigen/commit/b37a3d894478d8373dc07ca32c28156c30324f29))

- **examples**: Regenerate the defused diffs from the real banner composer
  ([`22669f4`](https://github.com/edycutjong/antigen/commit/22669f48941b8b0cc84fec9b5dd37b0f9305222d))

- **rfc**: Retract Finding 2's claim against mcp-server-datahub main
  ([`0ede86b`](https://github.com/edycutjong/antigen/commit/0ede86b7cc77ff064e1594f81822c93b488a8891))

- **skill**: Rebuild antigen-scan to the datahub-skills house layout
  ([`51650ae`](https://github.com/edycutjong/antigen/commit/51650ae30b9f2930774aec03b51cb0c9bcd232f1))

### Features

- **cli**: --max-mutations circuit breaker for unattended --apply runs
  ([`6e08d9b`](https://github.com/edycutjong/antigen/commit/6e08d9b2ad47c8200cbc2f9053adb4e8c589170e))


## v1.1.1 (2026-08-09)

### Bug Fixes

- **web**: Pitch deck test count 80 -> 114
  ([`771eaa4`](https://github.com/edycutjong/antigen/commit/771eaa42e971174efd77c5f7fac118833b5037c7))


## v1.1.0 (2026-08-09)

### Bug Fixes

- **cure**: Stop citing a payload file that is never written, and say what is really kept
  ([`47fdcb1`](https://github.com/edycutjong/antigen/commit/47fdcb12b2bc724e31e9c7bba4122bb52470ea00))

- **gateway**: Page search at the live GMS cap of 50, and paginate documents
  ([`5b95b03`](https://github.com/edycutjong/antigen/commit/5b95b03ce9d9e50f8875f7f383980dc98f2320a6))

- **gateway**: Report degraded live reads instead of swallowing them
  ([`d62da20`](https://github.com/edycutjong/antigen/commit/d62da201dacc060b8694b631e28e7df9c6f47541))

- **scan**: Fail closed on a degraded sweep — exit 2, never a silent all-clear
  ([`1740615`](https://github.com/edycutjong/antigen/commit/174061546b22d008e21a835bb9916af5bdd6ef55))

- **scan**: Widen the document pre-filter to cover persona jailbreaks
  ([`a7ec43e`](https://github.com/edycutjong/antigen/commit/a7ec43e756a0e5dc4abd1a062fd847eca3a8c12d))

### Continuous Integration

- **security**: Exclude TruffleHog's Lob detector — it verifies arbitrary strings
  ([`ca1882c`](https://github.com/edycutjong/antigen/commit/ca1882ce796bcd3d282b594cc681d3c3a896908a))

### Documentation

- **detect**: Retitle module docstring — the detector is deliberately replaceable; the remediation
  loop is the contribution
  ([`0f6779f`](https://github.com/edycutjong/antigen/commit/0f6779ff5e792521229547974c1212719535c6f3))

- **readme**: Add a 4-line quickstart and table of contents above the fold
  ([`4bc4838`](https://github.com/edycutjong/antigen/commit/4bc483812a91b1599480500f6f68b8ba01268e72))

- **readme**: Cite colliding prior art — AgentAntibody, mcp-context-protector, ETDI, DLP write-back,
  CDR
  ([`78d4a0f`](https://github.com/edycutjong/antigen/commit/78d4a0f80ed44bfeda69e8c67907b14d6d29e216))

- **readme**: Concede datahub-classify and Actions-framework overlaps; add Actions listener to
  roadmap
  ([`edfb02f`](https://github.com/edycutjong/antigen/commit/edfb02f7f5dc69972efd3358dad1b03e126ddaa0))

- **readme**: Label the dry-run transcript as the offline corpus double's numbers
  ([`5e97021`](https://github.com/edycutjong/antigen/commit/5e970210b1d385f2188fed94bf2f05d0da3b5bb5))

- **readme**: Name three known detector evasions in Honest limitations — base64, char-spacing, doc
  pre-filter gap
  ([`76036c5`](https://github.com/edycutjong/antigen/commit/76036c5df19f3e036d138418444b45b424ebfed4))

- **readme**: Reframe blast radius as tracing Documentation Propagation — DataHub's own default-on
  amplifier
  ([`a3ec958`](https://github.com/edycutjong/antigen/commit/a3ec958ac259aedf6602dc4295216d38c9943f1b))

- **readme**: True up the test count to 114 and name the new suites
  ([`06d08a0`](https://github.com/edycutjong/antigen/commit/06d08a01ce88f1d956a817abe6bfc538fdc7958b))

- **seed**: Update the live run order for the --apply write gate
  ([`bd69bb9`](https://github.com/edycutjong/antigen/commit/bd69bb95d6c8262d729a41930b898736fa33f6c2))

### Features

- **cli**: Dry-run by default on live mutating runs, --apply to write
  ([`802c7a1`](https://github.com/edycutjong/antigen/commit/802c7a1d47048330448c1ad1adc29703160dae42))

### Testing

- **cli**: Rename a test whose name tripped TruffleHog's Lob detector
  ([`87005f3`](https://github.com/edycutjong/antigen/commit/87005f30e65a4efdd43eec2768a1bb194ebedf1b))


## v1.0.11 (2026-08-09)

### Bug Fixes

- **web**: Serve /pitch and /pitch/ via rewrites to pitch.html
  ([`e516703`](https://github.com/edycutjong/antigen/commit/e51670399599ef71021fd9d55b053edd9ee2731c))

- **web**: True-up site numbers — 80-test suite, 24/24 run.sh subset, ~5 ms gate, 9 DataHub tools,
  drop leaked data-tbd marker
  ([`a8756e0`](https://github.com/edycutjong/antigen/commit/a8756e0b8d7e2e6776639a2ae812c8feb9a8e44d))

### Documentation

- Reconcile cross-surface numbers — 9 tools, ~5 ms gate, offline-vs-live corpus labels, python -m
  register_properties
  ([`a638e3c`](https://github.com/edycutjong/antigen/commit/a638e3cbcca3982362df2cacd2fb63318a49dde5))


## v1.0.10 (2026-08-09)

### Bug Fixes

- **assets**: Og image to spec — 1200x630, 175 KB, with a call to action
  ([`cdbe01a`](https://github.com/edycutjong/antigen/commit/cdbe01ae8b013361094903ad936eadd1791ce55b))

### Documentation

- Test count 79 -> 80, and name the 5th READ tool
  ([`ff2b096`](https://github.com/edycutjong/antigen/commit/ff2b09698d7a0d9d1d3c74a7c9ce86bb4654535a))


## v1.0.9 (2026-08-08)

### Bug Fixes

- **assets**: Correct inflated hijack and entity numbers across every image
  ([`903d60c`](https://github.com/edycutjong/antigen/commit/903d60c347550acdbba02962e425c9b8f483a859))

### Documentation

- Add the live tool-call transcript judges can grep
  ([`58bc301`](https://github.com/edycutjong/antigen/commit/58bc3016b66f86f1c4bf48b59095f4e764023ce0))

- Record the upstream docs PR (acryldata/mcp-server-datahub#202)
  ([`781b8b4`](https://github.com/edycutjong/antigen/commit/781b8b4faf3181fa5a2f2f921a9fb26f46010fcd))

- **readme**: Engage the prior art and ground the threat in evidence
  ([`050423b`](https://github.com/edycutjong/antigen/commit/050423bbe972ad962de6d8f659f5538ded93dcb6))


## v1.0.8 (2026-08-08)

### Bug Fixes

- **docs**: Correct the tag reserved-characters claim; it does not reproduce
  ([`fe7bdf7`](https://github.com/edycutjong/antigen/commit/fe7bdf718249469458ebd35bc661d6fc33fe4ed4))


## v1.0.7 (2026-08-08)

### Bug Fixes

- **cure**: Remediate on real catalogs; key ad-hoc incidents by digest
  ([`092b0a1`](https://github.com/edycutjong/antigen/commit/092b0a1cd3574f21e47a8e657590b5a33bc4df7a))

### Documentation

- **pitch**: Drop unverifiable 'only submission' claims
  ([`98c5b2f`](https://github.com/edycutjong/antigen/commit/98c5b2f76e7e2d9588857338b007688bbfea0faa))


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
