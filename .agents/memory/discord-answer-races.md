---
name: Discord answer races
description: Event-ordering constraints for simultaneous Discord guesses.
---

Discord can deliver multiple replies close together. A correct answer may clear the active game before another handler processes a late reply, so stale messages must be ignored during the resolution transition.

**Why:** Without atomic state removal and a short transition guard, a valid round can produce misleading “no active game” replies.

**How to apply:** Resolve a prompt with an atomic pop, remember its message ID, and suppress stale reply handling while the result/next prompt is being announced.