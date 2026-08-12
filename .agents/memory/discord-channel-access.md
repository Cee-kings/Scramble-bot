---
name: Discord channel access
description: Permission and command-availability constraints for the Discord game bot.
---

The bot's gateway connection and slash-command registration do not guarantee that it can post game messages in every server or channel. Discord may allow the bot to appear online while denying channel access, producing a `403 Missing Access` when a round starts.

**Why:** Server and channel permission overwrites can differ between guilds, and slash commands that require Manage Messages also depend on the invoking user's permissions.

**How to apply:** When a server-specific game fails, check the bot's View Channel, Send Messages, Embed Links, and Read Message History permissions in the target channel, then check the user's Manage Messages permission for `/scramble` and `/challenge`.