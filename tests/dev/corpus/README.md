# Regression corpus — plans a real model actually wrote

Not invented failures. `qwen_twitter_plan.yaml` is the byte-exact plan
Qwen3.6-35B-A3B (IQ2_XXS, thinking off) produced from
*"lee Agents.md y hazme un plan par hacer un twitter"*, recovered from its
session log. Getting it to validate took that session four rounds, and the
model resolved the schema by reading ~500 lines of `plan_validator_plugin.py`
source — the one thing the reading path exists to prevent.

Every defect in it came from a shape the plan template did not show. The
template now shows all three feature shapes, and each of these rules answers
with the YAML that fixes it; `test_plan_validator.py` asserts both against
this file. If someone reopens one of those holes, it fails in CI instead of
being rediscovered in a lost session.
