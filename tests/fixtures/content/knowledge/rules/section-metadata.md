---
title: Section Metadata
verified: 2026-09-01
ttl: domain
conflict: unresolved
---

# Section Metadata

<!-- kb-section: verified=2026-09-20; ttl=people -->

The comment above is before the first H2, so it has no effect.

## Valid override

<!-- kb-section: verified=2026-08-01; ttl=process; sources=observations/archived/20260412T101500-a1b2c3d4.md, observations/archived/20260903T120000-c3d4e5f6.md -->

Text after the valid comment.

### Inherits the parent's verified date

<!-- kb-section: ttl=people -->

This H3 takes verified from its H2 and ttl from its own comment.

## Blank lines before the comment

<!-- kb-section: verified=2026-07-01 -->

Text.

## Multi-line comment

<!-- kb-section: verified=2026-05-05;
     ttl=status -->

Text.

## Comment after body text

Body text first.

<!-- kb-section: verified=2026-01-01 -->

Text.

## Comment with trailing text

<!-- kb-section: verified=2026-06-01 --> trailing prose

## Comment inside a fence

```markdown
<!-- kb-section: verified=2025-01-01 -->
```

## Unknown keys and bad pairs

<!-- kb-section: verified=2026-04-04; colour=blue; nonsense; ttl=process -->

Text.
