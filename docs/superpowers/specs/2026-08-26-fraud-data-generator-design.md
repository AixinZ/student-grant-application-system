# Fraud Data Generator Design

## Purpose

Add a synthetic fraud-data generator to the existing local Student Grant
Applications Flask site. An operator enters a requested row count and downloads
an Excel workbook whose schema exactly matches `Sample Raw Data.xlsx`. Generated
records are varied, internally coherent, and labelled by the subset of the
provided fraud rules that the sample columns can support.

The generator is intended for local analysis and model-development work. It
does not claim that a rule hit proves fraud; `FRAUD_Label ` represents whether
at least one supported screening rule matched.

## Scope

The feature will:

- Preserve the existing application-entry and application-history behaviour.
- Add a `Data Generator` item to the existing top navigation.
- Add a dedicated generator page with one row-count input.
- Accept between 10,000 and 250,000 data rows, inclusive.
- Return one `.xlsx` download containing exactly the sample's 19 columns in the
  same order and with the same header spelling, including the trailing space in
  `FRAUD_Label `.
- Generate approximately 10% rule-positive records, with ordinary random
  variation expected to keep the observed rate near 9% to 11% for a 10,000-row
  download and closer to 10% for larger downloads.
- Calculate every label from generated field values through the rule engine.
- Avoid changing or storing records in the existing SQLite database.
- Remove temporary generated files after their download response completes.

The feature will not add fields that are absent from the sample, implement rules
whose required fields are absent, modify the source workbook, or train a
statistical generative model.

## Workbook Contract

The output worksheet will use this exact header order:

1. `CLIENT_DEPENDENT_STATUS`
2. `DISABILITY_STATUS_IND`
3. `INSTITUTION_CITY`
4. `INSTITUTION_PROVINCE`
5. `INSTITUTION_COUNTRY`
6. `OUT_OF_PROV_IND`
7. `NBR_OF_DEPENDENTS`
8. `TOTAL_NEED`
9. `STUDENT_AGE`
10. `STUDENT_CITY`
11. `STUDENT_PROVINCE`
12. `STUDENT_COUNTRY`
13. `CLIENT_CATEGORY`
14. `MARITAL_STATUS`
15. `GRANTS_ONLY_IND`
16. `CRA_MARITAL_STATUS`
17. `CRA_CITY`
18. `CRA_PROVINCE`
19. `FRAUD_Label `

Identifier and categorical fields will be written as text. Dependents and age
will be integers. Total need will be numeric and may include cents. Fraud labels
will be the exact text `Yes` or `No`.

The workbook will contain one worksheet, a frozen header row, and an autofilter.
It will be written incrementally so that large outputs do not require retaining
the entire cell grid in memory.

## Supported Screening Rules

Header comparisons are case-normalized. A record is labelled `Yes` when any of
the following predicates is true; otherwise it is labelled `No`.

1. `MARITAL_STATUS` differs from `CRA_MARITAL_STATUS`.
2. `STUDENT_PROVINCE` is not `SK`.
3. `TOTAL_NEED` is greater than 50,000 and `GRANTS_ONLY_IND` is `Y`.
4. `STUDENT_AGE` is greater than 65.
5. `CRA_PROVINCE` is nonblank and is not `SK`.
6. `INSTITUTION_PROVINCE` is not `SK`, `STUDENT_PROVINCE` is not `SK`, and
   `CRA_PROVINCE` is `SK`.
7. `STUDENT_PROVINCE` is not `SK` and `INSTITUTION_COUNTRY` is not `CANADA`.
8. `STUDENT_COUNTRY` is not `CANADA` and `STUDENT_PROVINCE` is not `SK`.

Rules that require SIN, correspondence, income, phone, IP-address, CRA dependent,
or last-name-change fields are excluded because those fields are absent from the
sample schema.

Thresholds are strict: a total need of exactly 50,000 and an age of exactly 65
do not trigger their respective rules. A blank CRA province does not prove that
the province is outside Saskatchewan and therefore does not trigger rule 5.

## Generation Model

The implementation will use rule-constrained synthetic generation rather than
copying complete source rows or fitting a statistical model to only 1,000
records.

### Ordinary records

About 90% of records will be sampled from coherent, non-triggering scenarios.
The generator will preserve relationships such as:

- `CLIENT_CATEGORY`, marital status, dependent status, and dependent count are
  mutually plausible.
- Institution city, province, and country describe the same location.
- Student city, province, and country describe the same location.
- `OUT_OF_PROV_IND` agrees with the student and institution provinces.
- CRA marital status normally agrees with student marital status.
- Need, age, disability, and grants-only values use varied distributions rather
  than fixed templates.

Every ordinary record will be evaluated by the rule engine. If it unexpectedly
matches a rule, it will be regenerated rather than receiving an overridden
label.

### Risk scenarios

Each record independently has an approximately 10% chance of being generated
from a risk scenario. Risk scenarios deliberately create field values that
satisfy one or more supported rules. Scenario weights will give all eight rules
meaningful coverage while keeping the more common province and high-need
patterns more frequent than rare age or marital mismatches.

Risk records are also passed through the same rule engine. The generator never
writes `Yes` without a matching predicate and never changes a computed label to
meet a quota. Because scenario selection is probabilistic, the final positive
rate varies naturally around 10%.

### Diversity and missingness

Categorical pools will include Saskatchewan, other Canadian, United States, and
international locations represented by coherent city/province/country tuples.
Continuous values will be sampled across realistic ranges, with additional
boundary coverage around age 65 and total need 50,000. Missing-value rates
matching the sample may be used for institution and CRA location fields when the
resulting record remains interpretable.

The generator will accept an injectable random-number source. Production uses a
fresh random stream for each request; automated tests use fixed seeds for
repeatability.

## Components and Data Flow

The feature will use focused components with explicit responsibilities:

- A schema/profile module owns the exact headers, coherent categorical value
  pools, distribution parameters, and risk-scenario weights.
- A rule module evaluates one record and returns both the Boolean fraud label
  and the matched rule identifiers.
- A generation module creates ordinary or risk records, validates their
  invariants, and adds the computed `FRAUD_Label ` value.
- A streaming XLSX exporter writes headers and generated rows into a temporary
  workbook without holding the complete output in memory.
- A Flask form validates the requested row count.
- A Flask route renders the page on `GET` and returns the generated workbook on
  a valid `POST`.

The request flow is:

1. The operator opens `Data Generator` from the top navigation.
2. The operator enters a row count from 10,000 through 250,000.
3. The server validates the form and creates a protected temporary output file.
4. Records are generated one at a time, evaluated, and streamed into the XLSX.
5. The completed file is returned as an attachment named
   `synthetic_fraud_data_<rows>_<YYYYMMDD>.xlsx`.
6. Response cleanup removes the temporary file.

## User Interface

The generator page will reuse the existing site shell, typography, colours,
focus treatment, and responsive form styling. It will contain:

- A page title and short explanation that labels represent rule matches.
- A numeric `Number of rows` input with visible 10,000 and 250,000 limits.
- A `Generate Excel File` submit button.
- Accessible inline and summary validation messages.
- A small note that larger downloads may take longer.

Client-side behaviour may disable the submit button and change its text while a
valid form is submitting. Server-side validation remains authoritative. The
page will not expose controls for label ratios, rule weights, random seeds, file
paths, or filenames.

## Validation and Error Handling

Non-integer, missing, below-minimum, and above-maximum row counts will return the
form with a validation error and no generated file. CSRF protection will use the
existing Flask-WTF integration.

Generation and export failures will be logged through the application's existing
privacy-safe diagnostic mechanism. The operator will receive a general retry
message, not a filesystem path, stack trace, record contents, or internal error
message. A failed operation will never return a partial workbook. Temporary
files will be removed after successful responses and after failures.

Only the server-selected temporary directory and server-generated filename will
be used. User input cannot select a path or filename.

## Testing and Acceptance Criteria

Automated tests will verify:

- Each of the eight predicates independently matches and does not match.
- Exact boundary behaviour at 50,000 total need and age 65.
- A blank CRA province does not trigger the non-Saskatchewan CRA rule.
- Multiple matching rules still produce one `Yes` label.
- A record with no matches produces `No`.
- Generated records obey the stated cross-field invariants.
- Fixed-seed output is reproducible and diverse across categorical and numeric
  values.
- A sufficiently large fixed-seed sample produces a positive rate close to 10%
  and exercises all eight supported rules.
- The output contains exactly the 19 required headers in order, has the requested
  number of data rows, and retains numeric cell types for numeric fields.
- The generated XLSX package opens successfully in an independent workbook
  reader.
- `GET /data-generator`, valid form submission, minimum and maximum values,
  validation errors, CSRF behaviour, safe failure responses, and navigation are
  correct.
- Temporary files are removed on success and failure.
- Existing application tests continue to pass unchanged.

A performance acceptance run will generate 250,000 rows while confirming that
the exporter streams rows and that process memory does not grow in proportion
to an in-memory 250,000-by-19 cell grid.

The feature is complete when an operator can generate and open valid workbooks
at both supported size limits, labels can be reproduced from the eight rule
predicates, the observed rule-positive rate is near 10%, and the existing
application remains unaffected outside the added navigation entry.
