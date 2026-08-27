# Manual Browser Acceptance Checklist

Run these checks after starting the local server at
`http://127.0.0.1:5000`. Record the date, browser, operating system, and the
result of every item. The automated suite covers deterministic logic and HTTP
behavior; the browser checks below verify the user experience and local runtime.

Use a clearly fictional test applicant, for example: name `Alex Student`, annual
income `42000.50`, address `123 Main Street`, age `24`, education `Bachelor's
Degree`, marital status `Single`, dependents `0`, and province `British Columbia
(BC)`.

## Submission and validation

- [ ] Submit the fictional valid applicant. Confirm one details page opens, it
  displays all submitted values, a percentage, a text decision, `random-v1`, and
  a submission time.
- [ ] Refresh the resulting details page. Confirm no second application is
  created; History contains only the original submission for that action.
- [ ] Submit blank values for each required field in turn. Confirm clear English
  validation feedback and no new history record.
- [ ] Check name boundaries and characters: one character is rejected; 2 and 100
  letters (with spaces, hyphens, or apostrophes where applicable) are accepted;
  101 characters, a digit, and a control or Unicode line-separator character are
  rejected.
- [ ] Check address boundaries and characters: fewer than 5 characters is
  rejected; 5 and 200 characters are accepted; 201 characters and a control or
  Unicode line-separator character are rejected.
- [ ] Check annual income boundaries: `0` and `999999999.99` are accepted;
  `-1`, `1000000000`, `1.999`, `NaN`, `Infinity`, and `-Infinity` are rejected.
- [ ] Check age boundaries: `16` and `100` are accepted; `15`, `101`, and a
  fractional value such as `18.5` are rejected.
- [ ] Check dependent boundaries: `0` and `20` are accepted; `-1`, `21`, and a
  fractional value such as `1.5` are rejected.
- [ ] Check that only the displayed education, marital-status, and province
  choices are accepted; use browser developer tools only in a development copy
  to submit an invalid value and confirm it is rejected with no new record.
- [ ] In a development/test configuration with an injected approval engine,
  submit a valid application at probability `0.5`. Confirm its decision text is
  `Not Approved`.
- [ ] In the same injected development/test configuration, submit a valid
  application at a probability just above the threshold (for example `0.5001`).
  Confirm its decision text is `Approved`. These injected checks are not
  available from the normal random-production screen.

## History, details, and immutability

- [ ] Create enough fictional records to exceed one history page. Confirm
  History shows 20 records per page, newest first, and Previous/Next navigation
  reaches the remaining records.
- [ ] Search with a partial student name in mixed case. Confirm matching is
  case-insensitive and partial; combine it with each decision filter (`All`,
  `Approved`, and `Not Approved`) and confirm the result set is correct.
- [ ] Refresh or copy a filtered/paginated History URL. Confirm search, decision,
  and page state remain in the URL and reproduce the same view.
- [ ] Open View details for a history row. Confirm the read-only details page
  includes every applicant field, approval probability, decision, engine, and
  submitted time, and links back to History and New Application.
- [ ] Open a nonexistent record URL such as `/applications/999999`. Confirm an
  English not-found page is shown.
- [ ] Inspect New Application, History, and Details. Confirm there are no Edit,
  Delete, or Reevaluate controls. In a development environment, request `PUT`,
  `PATCH`, and `DELETE` on a known detail URL and confirm each returns `405` and
  the record remains unchanged.
- [ ] Submit/select the province in lowercase in a development request where
  applicable, then confirm the saved and displayed province/territory code is
  uppercase (for example `BC`).

## Keyboard, layout, and visual accessibility

- [ ] Complete a valid submission using only the keyboard: use Tab/Shift-Tab,
  keyboard selection controls, Enter/Space, the navigation links, and View
  details. Confirm the focus order is logical and every action works.
- [ ] Tab through each page and confirm the visible focus indicator is clear,
  including header navigation and the Skip to main content link.
- [ ] Submit an invalid form. Confirm focus moves to the error summary; each
  summary link moves focus to the named invalid field, and the field error is
  announced/associated with that control.
- [ ] At a 320 CSS-pixel-wide viewport, verify the form becomes one column,
  content remains usable without clipping, and the History table can be
  horizontally scrolled within its labelled region.
- [ ] Check text, controls, error messages, links, and focus indicators for
  readable contrast against their backgrounds (use the browser's accessibility
  tools if available).
- [ ] Confirm both outcomes convey their decision with text (`Approved` or `Not
  Approved`), so the meaning is understandable without relying on badge color.

## CSV scoring

- [ ] Open `/csv-scoring` from the local navigation. Complete the entire
  upload, selected-column, model-selection, scoring, and download flow using
  only the keyboard (Tab/Shift-Tab, Enter, and Space). Confirm the drop zone,
  fields, selector, status, and download link have a logical focus order and
  visible focus indicator.
- [ ] Upload invalid CSVs: a file over 100 MB, a file with fewer than 100,000
  rows, a file with more than 250,000 rows, a file with a duplicate or `SCORE`
  header, and an invalid delimiter or encoding. Confirm each is rejected with a
  safe error and no source values, filename, local path, or partial result.
- [ ] Upload a representative large CSV within the 100,000–250,000 row limit
  that includes every required model header. Confirm the page reports progress,
  completes, and preserves source row order.
- [ ] Select a non-contiguous subset of original fields. Download the result,
  open it in Excel, and confirm it is readable without an encoding prompt. The
  exact output columns are the selected original columns followed by `SCORE`;
  confirm `SCORE` is the final column, has six decimal places, stays in `0..1`,
  and represents low risk at `0` and high risk at `1`.
- [ ] Confirm the available Isolation Forest choice is labelled experimental.
  Treat its scores as screening evidence, not proof of fraud; do not use a
  label or score as a fraud finding.
- [ ] Record the upload and job identifiers. After one-hour temporary
  retention (or an injected test clock), confirm source and result cleanup:
  metadata, status, and download URLs return not found, and no temporary files
  remain. Confirm cleanup also leaves no partial result after a forced failure.

## Log privacy and local persistence

- [ ] After a normal fictional submission and a deliberately invalid one, inspect
  `instance/student_grants.log`. Confirm it contains operational events only and
  does not contain the applicant's name, address, income, or other submitted
  values.
- [ ] Stop the server with `Ctrl-C`, restart it, and confirm the fictional
  history record still exists in `instance/student_grants.sqlite` through the
  History page.

## Sign-off

| Date | Tester | Browser/version | Result | Notes or defects |
| --- | --- | --- | --- | --- |
|  |  |  | Pass / Fail |  |
