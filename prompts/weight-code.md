# Scope of this run: production code only

Follow weight.md with one change of scope. Do Pass 0, then Pass 1 in full,
then Pass 5. Skip Passes 2, 3 and 4. Report findings only in the categories
`code_duplicate`, `code_needless_check` and `code_copied_rule`. Other reviewers
cover tests, comments and doc files, so spend all your effort on Pass 1: every
added or changed unit gets its searches and its worksheet entry.
