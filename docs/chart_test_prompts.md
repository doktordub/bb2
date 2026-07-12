# Chart Test Prompts

These prompts are intended for the `task_execution_chat` usecase.

The primary prompts `P01` through `P19` are minimal chart-generation checks for every value currently listed under `visualization.allowed_chart_types` in `backend/config/app.yaml`. They intentionally use inline JSON so failures isolate chart intent parsing, routing, chart building, and rendering instead of external tool calls.

The regression prompt `R01` reproduces the pie-chart scenario that currently falls back to a descriptive answer.

## Prompt Index

| ID | Expected chart type | Purpose |
| --- | --- | --- |
| P01 | bar | Single-series categorical bar chart |
| P02 | grouped_bar | Two-series grouped comparison |
| P03 | stacked_bar | Stacked category totals |
| P04 | horizontal_bar | Horizontal categorical ranking |
| P05 | line | Single-series time trend |
| P06 | multi_line | Multi-series time trend |
| P07 | area | Filled time-series trend |
| P08 | pie | Slice proportions |
| P09 | donut | Donut-style proportions |
| P10 | scatter | Two-axis numeric correlation |
| P11 | bubble | Scatter with bubble size |
| P12 | histogram | Numeric distribution |
| P13 | box_plot | Distribution by category |
| P14 | heatmap | Two-dimensional intensity matrix |
| P15 | treemap | Hierarchical area comparison |
| P16 | waterfall | Positive and negative deltas |
| P17 | gantt | Task schedule with start and end dates |
| P18 | radar | Multi-series capability comparison |
| P19 | table | Tabular artifact rendering |
| R01 | pie | Exact regression prompt from the reported failure |

## P01 - bar

Expected artifact: `bar`

Prompt:

Generate a bar chart titled "Revenue by Month" with month on the x-axis and revenue on the y-axis using this data:

```json
[
  {"month": "2026-01", "revenue": 1200},
  {"month": "2026-02", "revenue": 1350},
  {"month": "2026-03", "revenue": 1500}
]
```

## P02 - grouped_bar

Expected artifact: `grouped_bar`

Prompt:

Generate a grouped bar chart titled "Income vs Expense" with month on the x-axis and income and expense as the two series using this data:

```json
[
  {"month": "2026-01", "income": 5200, "expense": 4100},
  {"month": "2026-02", "income": 5400, "expense": 4300},
  {"month": "2026-03", "income": 5600, "expense": 4500}
]
```

## P03 - stacked_bar

Expected artifact: `stacked_bar`

Prompt:

Generate a stacked bar chart titled "Sales Mix by Quarter" with quarter on the x-axis and direct and partner stacked in each bar using this data:

```json
[
  {"quarter": "Q1", "direct": 210, "partner": 90},
  {"quarter": "Q2", "direct": 230, "partner": 110},
  {"quarter": "Q3", "direct": 260, "partner": 130}
]
```

## P04 - horizontal_bar

Expected artifact: `horizontal_bar`

Prompt:

Generate a horizontal bar chart titled "Tickets by Team" with team as the category and tickets as the value using this data:

```json
[
  {"team": "Alpha", "tickets": 82},
  {"team": "Beta", "tickets": 76},
  {"team": "Gamma", "tickets": 64}
]
```

## P05 - line

Expected artifact: `line`

Prompt:

Generate a line chart titled "Weekly Signups" with date on the x-axis and signups on the y-axis using this data:

```json
[
  {"date": "2026-01-01", "signups": 42},
  {"date": "2026-01-08", "signups": 45},
  {"date": "2026-01-15", "signups": 51}
]
```

## P06 - multi_line

Expected artifact: `multi_line`

Prompt:

Generate a multi line chart titled "Latency by Environment" with date on the x-axis and prod and staging as separate lines using this data:

```json
[
  {"date": "2026-01-01", "prod": 180, "staging": 220},
  {"date": "2026-01-02", "prod": 175, "staging": 210},
  {"date": "2026-01-03", "prod": 170, "staging": 205}
]
```

## P07 - area

Expected artifact: `area`

Prompt:

Generate an area chart titled "Active Users" with date on the x-axis and users on the y-axis using this data:

```json
[
  {"date": "2026-02-01", "users": 120},
  {"date": "2026-02-02", "users": 132},
  {"date": "2026-02-03", "users": 141}
]
```

## P08 - pie

Expected artifact: `pie`

Prompt:

Generate a pie chart titled "Yes vs No" using label for the slice name and value for the slice size with this data:

```json
[
  {"label": "yes", "value": 77},
  {"label": "no", "value": 23}
]
```

## P09 - donut

Expected artifact: `donut`

Prompt:

Generate a donut chart titled "Revenue Split" using segment for the slice name and revenue for the slice size with this data:

```json
[
  {"segment": "Enterprise", "revenue": 620},
  {"segment": "SMB", "revenue": 310},
  {"segment": "Startup", "revenue": 70}
]
```

## P10 - scatter

Expected artifact: `scatter`

Prompt:

Generate a scatter chart titled "Study Hours vs Score" with hours on the x-axis and score on the y-axis using this data:

```json
[
  {"hours": 2, "score": 68},
  {"hours": 4, "score": 79},
  {"hours": 6, "score": 91}
]
```

## P11 - bubble

Expected artifact: `bubble`

Prompt:

Generate a bubble chart titled "Pipeline Quality" with confidence on the x-axis, velocity on the y-axis, and amount as bubble size using this data:

```json
[
  {"confidence": 0.65, "velocity": 18, "amount": 120000},
  {"confidence": 0.80, "velocity": 24, "amount": 180000},
  {"confidence": 0.55, "velocity": 15, "amount": 90000}
]
```

## P12 - histogram

Expected artifact: `histogram`

Prompt:

Generate a histogram chart titled "Resolution Time Distribution" using hours as the distribution value from this data:

```json
[
  {"hours": 1.5},
  {"hours": 2.0},
  {"hours": 3.25},
  {"hours": 4.0}
]
```

## P13 - box_plot

Expected artifact: `box_plot`

Prompt:

Generate a box plot chart titled "Latency by Region" with region as the category and latency as the distribution value using this data:

```json
[
  {"region": "us-east", "latency": 145},
  {"region": "us-east", "latency": 152},
  {"region": "eu-west", "latency": 181},
  {"region": "eu-west", "latency": 176}
]
```

## P14 - heatmap

Expected artifact: `heatmap`

Prompt:

Generate a heatmap chart titled "Usage Heatmap" with month on the x-axis, region on the y-axis, and value as the cell intensity using this data:

```json
[
  {"month": "2026-01", "region": "us-east", "value": 82},
  {"month": "2026-01", "region": "eu-west", "value": 74},
  {"month": "2026-02", "region": "us-east", "value": 91},
  {"month": "2026-02", "region": "eu-west", "value": 79}
]
```

## P15 - treemap

Expected artifact: `treemap`

Prompt:

Generate a treemap chart titled "Revenue by Segment" using segment as the category and revenue as the area value with this data:

```json
[
  {"segment": "Enterprise", "revenue": 620},
  {"segment": "SMB", "revenue": 310},
  {"segment": "Startup", "revenue": 70}
]
```

## P16 - waterfall

Expected artifact: `waterfall`

Prompt:

Generate a waterfall chart titled "Margin Bridge" with stage in order and delta as the positive or negative change using this data:

```json
[
  {"stage": "Starting Margin", "delta": 120},
  {"stage": "Discounts", "delta": -35},
  {"stage": "Upsell", "delta": 20}
]
```

## P17 - gantt

Expected artifact: `gantt`

Prompt:

Generate a gantt chart titled "Release Plan" using task, start, and end from this data:

```json
[
  {"task": "Design", "start": "2026-03-01", "end": "2026-03-05"},
  {"task": "Build", "start": "2026-03-06", "end": "2026-03-14"},
  {"task": "QA", "start": "2026-03-15", "end": "2026-03-19"}
]
```

## P18 - radar

Expected artifact: `radar`

Prompt:

Generate a radar chart titled "Capability Scorecard" with metric as the axis and team_alpha and team_beta as the two series using this data:

```json
[
  {"metric": "Reliability", "team_alpha": 82, "team_beta": 75},
  {"metric": "Speed", "team_alpha": 76, "team_beta": 80},
  {"metric": "Coverage", "team_alpha": 88, "team_beta": 79}
]
```

## P19 - table

Expected artifact: `table`

Prompt:

Generate a table chart titled "Monthly Status Table" using this data:

```json
[
  {"month": "2026-01", "status": "green", "revenue": 1200},
  {"month": "2026-02", "status": "green", "revenue": 1350},
  {"month": "2026-03", "status": "yellow", "revenue": 1500}
]
```

## R01 - pie regression from reported failure

Expected artifact: `pie`

Prompt:

```text
draw a pie chart showing 77% for 'yes' and the rest as 'no'
```

This prompt is intentionally not expressed as inline JSON. It verifies the natural-language-only path that should infer the missing `no = 23` slice without falling back to a descriptive answer.