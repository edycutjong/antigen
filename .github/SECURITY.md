# Security Policy

Antigen is a security control, so we hold ourselves to the standard we ask of the
catalogs we scan.

## Supported Versions
| Version | Supported |
|---|---|
| latest (`main`) | ✅ |

## Reporting a Vulnerability
Please **do not** open a public issue for security vulnerabilities — including
detection-bypass techniques that would let a payload evade `antigen scan`. Instead,
report them privately:

- Email **edy.cu@live.com**, or
- Use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) (Security → Report a vulnerability).

You'll get an acknowledgment within 48 hours and a resolution timeline after triage.
Please give us a reasonable window to patch before public disclosure.

## Scope of interest
- **Detector evasion** — a real prompt-injection string that `antigen scan` does not
  flag (a false negative), especially novel Unicode/homoglyph evasions.
- **Cure incompleteness** — any agent-readable surface where a payload (or a recoverable
  encoding of it) survives `antigen cure`.
- **Data handling** — any path where a recoverable payload is written back to the graph
  instead of only an irreversible hash.

## Not in scope
- False positives on benign prose are handled as normal bugs (open a public issue).
- Antigen never stores credentials; they belong in `~/.config`, never in the repo.
