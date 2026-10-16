# Research activity heatmap

## Goal

Give the researcher a quiet, useful daily rhythm view that encourages returning to
the library. The visualization should describe research work already performed,
not reward importing the largest number of PDFs.

## Data contract

The backend stores one aggregate row per local calendar day. Each row contains
counts for `reading`, `notes`, `language`, `search`, and `imports`, plus the total.
The API returns the requested date range, daily entries, current streak, active
days in the last 30 days, and total activity. Missing days are returned as zero
entries so the client can render a stable 53-week grid.

The event endpoint accepts one activity kind and an optional paper id. The client
deduplicates passive reading events per paper and day in memory and local storage;
explicit actions such as saving a note, finishing a translation, submitting a
search, or importing a paper are recorded once. This keeps the local database
small and prevents scrolling from generating a request per wheel event.

## User experience

The library page places a compact `研究节律` panel below the page heading and
before the paper table. A 53-week grid uses four intensity levels plus empty. A
hover or keyboard focus tooltip shows the date, total activity, and the five
activity categories. Clicking a day filters the library to papers touched that
day; clicking the selected date again clears the filter. The panel also shows
current streak, active days in the last 30 days, and total activity.

The component uses existing CSS variables, has no chart dependency, supports dark
theme and both locales, and remains horizontally scrollable on narrow screens.

## Error handling and privacy

Activity tracking is local-only. A failed activity request must never interrupt
reading, importing, translation, or note saving. The client queues a bounded
number of unsent events and drops them after a retry limit. The API validates the
kind, date range, and optional paper id; it does not accept arbitrary timestamps
from the browser.

## Verification

Backend tests cover aggregation, zero-filled ranges, streak calculation, invalid
kinds, and unknown paper ids. Frontend tests cover the grid's accessible labels,
activity level classes, day selection filtering, and the fact that a reading
session does not emit duplicate events. The production build and the existing
workspace/readers suites remain required checks.
