# Chart Test Plan

## Objective

Verify that every chart type listed under `visualization.allowed_chart_types` can be generated successfully through the `task_execution_chat` usecase, and specifically catch the pie-chart regression where the response falls back to description-only output.

## Scope

- Run `P01` through `P19` from `docs/chart_test_prompts.md`.
- Run regression case `R01` from `docs/chart_test_prompts.md`.
- Confirm both backend artifact generation and frontend rendering behavior.

## Preconditions

1. Backend is running with visualization enabled.
2. `task_execution_chat` is the selected usecase for the client or request payload.
3. `policy.visualization.enabled` is true, otherwise chart generation can be denied before artifact creation.
4. Start each primary case in a fresh session, or clear session history between runs.
5. Capture the response body and trace id for every failed case.

## Execution Procedure

1. Execute prompts `P01` through `P19` one by one.
2. For each prompt, verify the response does not fall back to text-only guidance such as "I couldn't generate the chart" or "I can describe how to create one".
3. Verify the response includes exactly one artifact and that the artifact `chart_type` matches the expected type for that prompt.
4. Verify the artifact `renderer` is `echarts` and `spec_version` is `1.0`.
5. Verify the chart renders correctly in the frontend, especially for visually distinct cases: `pie`, `donut`, `heatmap`, `gantt`, `radar`, and `table`.
6. If trace output is available, verify there is no `agent_failed` event and no `agent_tool_intent_error` for the case.
7. For inline-data prompts `P01` through `P19`, verify no external data tool call was required. These prompts should succeed from inline data alone.
8. Execute `R01` last and verify it produces a pie chart with two slices representing `yes = 77` and `no = 23`.

## Expected Pass Criteria

- All 19 primary prompts return a chart artifact of the expected type.
- `R01` returns a pie chart instead of a fallback explanation.
- No case returns a missing-data prompt for inputs that are already present inline.
- No case emits `agent_tool_intent_error`.
- Frontend rendering matches the returned artifact type for every case.

## Suggested Follow-up Checks

After `P02`, ask this follow-up in the same session:

```text
What was the expense value for 2026-03?
```

Expected result: a direct answer that returns `4500` without leaking raw dataset rows into the prompt or asking the user to resend the data.

After `P05`, ask this follow-up in the same session:

```text
What was the highest signup value shown in the chart?
```

Expected result: a direct answer that returns `51` using stored chart context.

## Failure Triage Guide

- If the response is description-only, inspect task-execution routing first to confirm the request was classified as a visualization request and delegated to `chart_agent`.
- If the trace shows `agent_tool_intent_error`, inspect the chart-agent intent/tool path. For the inline-data prompts, tool execution should not be necessary.
- If the artifact is present but the UI does not render it, inspect the frontend renderer and artifact-to-ECharts mapping.
- If the trace shows a policy denial, inspect `policy.visualization` configuration before debugging agent logic.
- If only `R01` fails while `P08` passes, the regression is in natural-language chart-data synthesis rather than renderer support.

## Automation Plan

1. Add a parameterized integration test that reuses the datasets in `backend/tests/fixtures/visualization/chart_validation_cases_v1.json` and asserts the returned artifact type for each allowed chart type.
2. Add one dedicated integration test for `R01` under the `task_execution_chat` flow so the natural-language pie split is locked in as a regression check.
3. In that automated suite, assert that inline-data cases complete without tool calls and without `agent_failed` trace events.
4. Keep the prompt catalog in `docs/chart_test_prompts.md` as the manual smoke-test source of truth, and update it whenever `allowed_chart_types` changes.

## Evidence Template

Use this table while running the plan:

| Case | Expected type | Status | Trace id | Artifact id | Notes |
| --- | --- | --- | --- | --- | --- |
| P01 | bar |  |  |  |  |
| P02 | grouped_bar |  |  |  |  |
| P03 | stacked_bar |  |  |  |  |
| P04 | horizontal_bar |  |  |  |  |
| P05 | line |  |  |  |  |
| P06 | multi_line |  |  |  |  |
| P07 | area |  |  |  |  |
| P08 | pie |  |  |  |  |
| P09 | donut |  |  |  |  |
| P10 | scatter |  |  |  |  |
| P11 | bubble |  |  |  |  |
| P12 | histogram |  |  |  |  |
| P13 | box_plot |  |  |  |  |
| P14 | heatmap |  |  |  |  |
| P15 | treemap |  |  |  |  |
| P16 | waterfall |  |  |  |  |
| P17 | gantt |  |  |  |  |
| P18 | radar |  |  |  |  |
| P19 | table |  |  |  |  |
| R01 | pie |  |  |  |  |