"""
UserEntity — the `users` domain's UBIQUITOUS LANGUAGE.

This is NOT a mirror of the table. It is what the domain calls a user, and it
is the vocabulary every plugin in this domain must speak: same field names,
same shapes. The manifest publishes it next to the table so a feature author
sees both.

Two deliberate differences from `users` (both are the point, not an oversight):

  - `password_hash` is a COLUMN and is NOT a field here. It never leaves the
    system, so it is not part of the domain's language. A plugin that needs it
    reads the column directly in its SQL; nothing that speaks this vocabulary
    can leak it by accident.
  - `roles` is `TEXT` on disk (JSON) and `list[str]` here. Storage shape and
    domain shape are different questions.

RULE: one thing per file — the entity. HTTP request/response schemas belong
      inside each plugin (they are per-feature projections of this vocabulary,
      and may legitimately add fields with no column behind them, like the
      plaintext `password` on a create request).
"""

from pydantic import BaseModel, EmailStr


class UserEntity(BaseModel):
    id: int | None = None
    name: str
    email: EmailStr
    roles: list[str] = ["user"]
