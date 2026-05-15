# KIS Domestic Stock Interview Questions

Ask only the questions needed for the current task.

| Trigger | Question | Answer Shape | Plan Field | Required When | Inference |
| --- | --- | --- | --- | --- | --- |
| onboarding | Which execution modes are in scope: no-order, paper, live? | enum list | `execution_modes` | always | may infer from docs if explicit |
| onboarding | Which KIS profiles/endpoints are allowed? | short text | `kis_profiles` | KIS used | do not infer secrets |
| rebuild planning | Which modules own broker calls today? | paths | `broker_modules` | module split | infer from code search |
| rebuild planning | Which files define strategy parameters? | paths | `strategy_parameter_files` | strategy code touched | infer from code search |
| risky checkpoint | Is any order/account/balance call being introduced or enabled? | boolean | `broker_action_scope` | broker adapter touched | must answer explicitly |
| risky checkpoint | What is the kill switch and how is it verified? | path/command | `kill_switch_evidence` | paper/live planned | infer only if tests exist |
| risky checkpoint | What prevents duplicate orders? | path/command | `duplicate_order_evidence` | order intent touched | infer only if tests exist |
| risky checkpoint | What maximum-loss controls are enforced? | path/command | `max_loss_evidence` | paper/live planned | infer only if tests exist |
| validation | Which warm-up/source data is required for strategy readiness? | path/schema | `warmup_contract` | strategy evaluation touched | infer from tests/artifacts |
