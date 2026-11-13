# Scope of this run: comments, docstrings and doc files only

Follow weight.md with one change of scope. Do Pass 0, then Passes 3 and 4 in
full, then Pass 5. Skip Passes 1 and 2. Report findings only in the categories
`doc_restates_code`, `doc_repeats_doc`, `doc_drift_prone`,
`docfile_drift_prone` and `docfile_repeats`. Other reviewers cover production
code and tests, so spend all your effort on Passes 3 and 4: every added comment
or docstring sentence, in production and test files alike, and every added
doc-file sentence gets its searches and its worksheet entry.
