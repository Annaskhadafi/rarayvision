# Agent Instructions & Project Rules

Whenever working on MetaTrader 4 (MQL4) or MetaTrader 5 (MQL5) Expert Advisors, indicators, scripts, graphical panels, or trade management logic in this project, **ALWAYS use and apply the `mql-developer` skill**.

## MQL Development Workflow & Rules

1. **Skill Integration**:
   - Always load and follow the instructions in the `mql-developer` skill (`.agents/skills/mql-developer/SKILL.md`).
   - Refer to reference guides in `.agents/skills/mql-developer/references/` for MQL4/MQL5 syntax, trading operations, UI panels, architecture patterns, and external communication.

2. **MQL Coding Best Practices**:
   - **Double Comparisons**: Always use `NormalizeDouble()` or tolerance when comparing double price values.
   - **Looping Orders**: Iterate `OrdersTotal() - 1` down to `0` when scanning or closing orders in MQL4.
   - **Price Normalization**: Normalize all entry prices, SL, and TP values before calling `OrderSend` or `OrderModify`.
   - **UI Performance**: Never run heavy `iCustom()` loops on every single tick. Rate-limit indicator calculations to new bar open, timer intervals, or button events.

3. **Compilation & Verification**:
   - Always compile MQL files using MetaEditor (`metaeditor.exe /compile:... /log:...`).
   - Verify that the result contains **0 errors and 0 warnings** before declaring completion.
