# Scope of this run: tests only

Follow weight.md with one change of scope. Do Pass 0, then Pass 2 in full,
then Pass 5. Skip Passes 1, 3 and 4. Report findings only in the categories
`test_unneeded` and `test_mergeable`. Other reviewers cover production code,
comments and doc files, so spend all your effort on Pass 2: every added or
changed test, parametrized case and assertion gets its searches and its
worksheet entry.

`CODE` holds what the production-code reviewer found on this PR. Read it
before Pass 2 and use it as Pass 2 step 1 says. Do not repeat its findings.
