# PR weight review

You are reviewing one pull request for weight: lines it adds that the codebase
would be better off without. You are not looking for bugs.

A script has already counted every added line and sorted it into production,
tests, doc files, generated and config. Your job is the part a script cannot
do: judge which added lines are dead weight, and say where they are. The script
then counts the lines inside the ranges you give, so never report totals. Report
ranges.

Apply the definitions below as written, and be complete: flag every added line
that fits one, however small the finding looks. The report is read as a count,
so leaving out a line that fits makes the count wrong. The other direction matters as much: do
not flag a line that fits no definition, even if you would have written it
differently. Every finding needs a reason the author could check for themselves.

## Inputs

You are given, in the task message:

- `REPO`: a local git checkout. `HEAD_SHA`: the PR's head commit, already fetched.
- `ADDED`: a listing of every added line: the line number in the new file, a
  kind, and the text. The kinds are `C` code, `D` comment or docstring inside a
  code file, and `P` prose in a doc file such as a README or a plan. Generated
  and config files are named but not listed. Do not review them.
- `DIFF`: the full unified diff, for context around the added lines.
- `OUT`: the path to write your findings to.
- `CODE`, not always given: the findings of a review of this PR's production
  code, in the JSON shape described under Output. Pass 2 uses it.

Read the surrounding code before judging. A comment can only be called a
repeat once you have read what it sits next to, and code can only be called a
duplicate once you have found the code it duplicates.

- Read a file as the PR leaves it: `git -C REPO show HEAD_SHA:path/to/file`
- Search the repo as the PR leaves it: `git -C REPO grep -n 'pattern' HEAD_SHA -- 'dir/'`

This is read-only work. Do not check out branches, edit, commit, or push in
`REPO`, and do not post anything to GitHub. The only file you write is `OUT`.
The checkout's working tree may be on another branch with someone's unsaved
work, so read through `HEAD_SHA` as above and never from the working tree.

## How to work

Almost nothing here can be judged from the added line alone. Whether a line is
weight depends on something that is not in the diff: a helper that already
exists three directories away, the one caller of a function, the other test
that asserts the same thing, the module that owns a constant. A reviewer who
only reads the added lines finds the weak comments and misses everything else.

So work in passes, and in every pass go and look before you rule. Each pass
says what to list, where to look, and what to write down. Finish a pass before
starting the next. For every item you examine, add one entry to `worksheet`
(see Output) saying what you searched and what you found, also when the answer
is "nothing". An item with no search behind it is not done.

A line the PR only rewrote in part is listed as added in full. Compare it with
the removed line in `DIFF` and judge only the words that changed. Text that was
already there is not this PR's weight, even when it would fit a category.

**Pass 0: understand the change.** Read `DIFF` from top to bottom, removed
lines included. Then write `purpose`: two or three sentences on what the PR is
for, what it replaces, and what the removed lines used to do. Keep this in
mind for every later pass; it is what tells you a line now serves nothing.

**Pass 1: production code, one unit at a time.** List every function, method,
class, constant and branch the PR adds or changes in production files. For
each one:

1. Say in one line what job it does.
2. Look for the same job elsewhere. Pick the two or three most telling calls
   or expressions inside it and search the whole repo for each, not only the
   file it is in. Open every hit that could be doing the same job and read it.
   Compare it with the other units in this PR too. Same steps in two places
   is `code_duplicate`.
3. For each `if`, `try`, fallback and default in it: find who calls this
   (search for the callers and read them), and ask whether the guarded state
   can reach this line, and whether a check right next to it already covers
   it. If it cannot or it does, that is `code_needless_check`.
4. For each literal in it (a prefix, a status name, a number, a duration, a
   limit, a format): search for where that value is defined or produced. If
   another module, service or config owns it and this code repeats it, that
   is `code_copied_rule`.

**Pass 2: tests, one test at a time.** List every test function and every
parametrized case the PR adds or changes. Keep two lists: tests that are new,
and tests that existed and were edited. An edited test deserves the same care
as a new one: changing what it sends can turn it into a copy of another test,
so for each edited test compare what it now sends and asserts with the other
tests of the same route or function. For each test on either list:

1. Say in one line which behaviour of our own code would have to break for
   this test to fail. If you cannot name one, because it exercises a mock, a
   library or an input that cannot occur, that is `test_unneeded`. One
   exception: a test that forces a state the code cannot reach today in order
   to exercise a deliberate safety gate (an authorization check, validation
   at a trust boundary) is worth keeping when that gate is the only thing
   that refuses the state. The exception does not cover a second gate. Trace
   the request from its entry point to the gate. If an earlier check on the
   same path always runs first and already refuses that state, so that the
   test has to patch out or replace the earlier check to get to the gate, the
   test is `test_unneeded`: the earlier check is the guard, and it has its
   own test. The same holds when Pass 1, or the review given as `CODE`,
   flagged the gate as `code_needless_check`: a test or assertion whose only
   job is to reach that check goes with it. Give the earlier check or the
   flagged lines in `see`. If you find a real request that does reach the
   gate, keep the test and say so in `outside`.
2. Work out whether this test would pass on the code as it was before the
   PR. The removed lines in `DIFF`, together with the unchanged code, are the
   old behaviour. Write the answer in the worksheet entry.
   - It would fail before: go on to the next step. Failing before does not by
     itself earn the test its place. A test that goes in through a route,
     identifier or parameter the PR adds always fails before, because that way
     in did not exist. Step 4 still decides whether it only re-runs behaviour
     that sits after the new part.
   - It would pass before: it tests behaviour the PR did not change. That is
     fine when nothing tested that behaviour until now. So find the function
     where the behaviour is decided, which is often one or two calls below
     the route the test goes through, and search for tests of that function
     as well as tests of the route. If one already sends the same kind of
     input and asserts the same outcome, this test is `test_unneeded`, also
     when it goes through more layers than the existing one; give the
     existing test in `see`. Going through an extra layer earns the test its
     place only when the PR changed that layer and the test would fail if the
     changed lines were wrong.
3. Read the code under test. For every mock, patch and fake the test sets
   up, ask whether the function or route under test can call it on any path
   at all. If it has no call to it anywhere, the mock and every assertion on
   it are `test_unneeded`. If the code does call it on another path, and the
   test asserts it was not called on this one (a refusal, a failed check),
   ask one more thing: with the data this test sets up, would the call happen
   if the refusal were taken away? If yes, keep both the mock and the
   assertion: they guard the order of the checks. If the test's own data
   would skip the call anyway, the guard can never fire and is
   `test_unneeded`.
4. Search the test suite for other tests of the same function or route: by
   the name of the function, the route path, the expected status or value.
   Open them. If one already sends the same input and asserts the same
   outcome, this one is `test_unneeded`; give the other in `see`. Think about
   what the PR changed: a test that was distinct before the change can be a
   repeat after it. When the PR adds a second way to reach behaviour that
   already exists (a new identifier, route or parameter), the new way needs
   tests that it resolves to the right thing and is refused when it should
   be. "Refused" here means refused by the checks that belong to the new way
   itself: it does not resolve, it resolves to something the caller may not
   have, it matches more than one thing. A refusal that happens after it has
   resolved, by a check both ways share, is not one of those. Cases that only
   re-run what happens after the new part, which tests of the first way
   already assert, are `test_unneeded`.
5. Compare it with its neighbours. Same setup and same shape of assertion
   with different inputs is `test_mergeable`.
6. Then go through the assertions inside it, one at a time, also when the
   test as a whole is worth keeping. For each assertion, trace where its two
   sides come from and ask what would make it fail. It is `test_unneeded`
   when any of these holds:
   - both sides are read from the same source: the same file, the same
     constant, a variable and the thing it was assigned from;
   - a fake returns the same canned value on every call, and the assertion
     compares two of its results;
   - it still passes when the behaviour the test is named for is removed,
     because something else produces the same result (another check returns
     the same status, a default gives the same value);
   - a stronger assertion in the same test already implies it.
   An assertion is not vacuous when the lookup or call inside it can itself
   fail or return nothing: `assert store.get(key)["id"] == key` still proves
   the row can be found. Mark only the assertion's lines, and give each one
   its own worksheet entry.
7. When you flag lines, also flag the imports, fixtures and helpers in the
   same file that nothing else uses once those lines are gone. Put them in
   the same finding's range when they are adjacent, or in a second finding
   with the same reason.

**Pass 3: comments and docstrings, one sentence at a time.** List every added
comment and docstring sentence. For each one:

1. Say what it claims, and whether the claim is about the code it sits on or
   about something else: another function, another module or service, a list
   of callers, a value defined elsewhere. Two signs that it is about
   something else: it says what callers, a route or another layer do with
   this code (a status code a handler picks, what "callers must" do), or it
   narrates the change itself (what used to happen, what is "now" or "no
   longer" the case). A comment that tells the history is out of date once
   the change has merged. Naming a decision, a ticket or its date is not
   narrating the change: it is a pointer.
2. If it is about something else, check it against the three triggers of
   `doc_drift_prone` and its exemptions (see What to flag). When a trigger
   fits, open the other thing and check the claim, and say so in the reason
   when the claim is already false.
3. Read the docstrings of the function it sits in and of the functions that
   code calls, and search the repo for a distinctive phrase from it. The same
   statement in another comment or docstring is `doc_repeats_doc`. A sentence
   that gives a fact in one clause and points to where it is defined (a
   section, a decision, another function) is a pointer, not a repeat. A
   comment that sums up a doc file and names it is a pointer too.
4. If it only says what the adjacent name or code says, it is
   `doc_restates_code`. It is not a restatement when it says something the
   name and the types cannot: what a collection holds, what a value is
   measured in, why a fixture or a fake is set up the way it is.

**Pass 4: doc files, one sentence, list item or table row at a time.** For
each: does it pin a detail of the code (line numbers first, then counts,
copied values, versions, lists of callers)? Search for another doc file or a
docstring that already says it.

**Pass 5: step back.** Read your `purpose` again and look at the PR as a
whole. Is there a path, a state or a layer that the PR builds or keeps which
nothing can reach or which an existing piece already provides? Would a
different shape make it much smaller? Do two files now cover the same ground?
Such points fit no category and are not counted. Write them in `outside`.

## What to flag

Each finding has one category. The examples show the idea of each category and
what falls just outside it. Real cases will look different, in other languages
and other shapes, so judge by the definition and not by likeness to an example.

### Comments and docstrings

These apply to `D` lines only, in production or test files.

Flag whole sentences. When a sentence runs over several lines, flag all of its
lines or none of them. If only part of a sentence fits, flag it only when the
rest of the sentence adds nothing either.

**`doc_restates_code`**: the sentence says only what the name, the signature or
the code right next to it already says. Deleting it loses nothing. A comment
that gives a reason, a constraint or a consequence is not a restatement.

```python
# Flag: the name and the call already say this.
# Increment the retry counter.
retries += 1

# Don't flag: it gives the reason.
# Retry once more: the upstream drops the first call after a deploy.
retries += 1
```

```go
// Don't flag: a Go doc comment starts with the name by convention, and the
// sentence goes on to state a guarantee the signature does not.
// ArchiveShipped moves every shipped order to cold storage in one batch, so
// a reader never sees half of them moved.
func (s *Store) ArchiveShipped(ctx context.Context, before time.Time) (int, error)

// Flag: nothing beyond the name and signature.
// GetUser gets a user.
func GetUser(id string) (*User, error)
```

**`doc_repeats_doc`**: the sentence says what another comment or docstring
already says, in this PR or elsewhere in the repo. Give the other place in
`see`.

```python
# Flag: the function below already has a docstring saying exactly this.
# Amounts come back in minor units.
total = price_basket(items)   # price_basket(): """Returns the total in minor units."""
```

```python
# Don't flag: one clause and a pointer to the owner.
# Refunds over the limit need a second approver (decision 12).

# Don't flag: the name and the return type do not say what the list holds.
def _recorded_calls() -> list[str]:
    """The request ids the fake gateway received, in order."""
```

Do not flag two comments that touch the same topic but each say something the
other does not.

**`doc_drift_prone`**: the sentence will go wrong silently when something
else changes. Flag it when one of these three is true, and only then:

1. It names another function, module, route, service or setting, and says
   what that thing does, accepts, returns or holds.
2. It carries a number or literal that is defined somewhere else: a limit, a
   count, a duration, a status code, a version, a line number.
3. It narrates the change: what used to happen, what is "now" or "no longer"
   the case.

Do not flag it when:

- it only describes the code it sits on: its own behaviour, its own constant;
- it sits inside a test and that same test asserts what it says, anywhere in
  the test, not only on the next line;
- it names the other thing only as a pointer ("see the limits table",
  "decision 12") without saying what it does.

```ts
// Flag: three facts owned elsewhere, none checked.
// Called from checkout.ts and cart.ts. The server caps this at 50 items
// (see limits.py line 88).

// Don't flag: it describes this function's own behaviour.
// Returns an empty list when the cart has no items.
```

```python
# Flag: it tells the history, which is stale the day this merges.
# Previously this returned 404; now it returns 409.

# Don't flag: it names the decision, it does not narrate the change.
# Decision 12, revised 2026-03-02: refunds need a second approver.

# Don't flag: inside a test that asserts it. The comment explains the setup
# and the assertion a few lines down checks the claim.
# An archived order cannot be renamed, so the gateway is never reached.
order = await seed(status="archived")
gateway = FakeGateway()
assert (await api.patch(url, json={"name": "B"})).status_code == 409
```

A comment in production code is kept in step only when a test or a generator
reads the comment's own text: a doc test, a generated file, a check that
compares the text with the code. A test of the behaviour does not keep a
production comment in step: when the behaviour changes, that test fails and
gets fixed, and the comment stays as it was.

### Production code

These apply to `C` lines in production files.

**`code_duplicate`**: the lines do again what code already in the repo, or
elsewhere in this PR, does, and could call it instead. Give the existing code
in `see`. Ordinary boilerplate (imports, error checks, struct fields) is not
duplication.

```python
# Flag when the repo already has shared/text.py initials() doing exactly this.
def _short_name(full_name: str) -> str:
    return "".join(part[0].upper() for part in full_name.split() if part)
```

Do not flag two functions that look alike but serve rules that are free to
change apart from each other.

**`code_needless_check`**: a check, guard or fallback that can be deleted with
no change in behaviour for any input that can occur. Either the check right
next to it already covers it, or the type system, the callee or our own server
already guarantees it. Mark only the deletable lines.

```ts
// Flag the first and third lines: the type test on the next line already
// fails for a missing key, and Number.isFinite already rejects non-numbers.
!("order_id" in body) ||
typeof body.order_id !== "string" ||
typeof body.weight_kg !== "number" ||
!Number.isFinite(body.weight_kg)
```

```go
// Flag: the only call site passes a value it has just nil-checked.
if user == nil {
    return nil
}
```

Do not flag a check on user input or on a third party's response, unless it
checks more than the code goes on to use.

**`code_copied_rule`**: the lines re-implement a rule or constant that another
service, module or config owns, so the two can disagree: a duration, a limit,
a status rule, a format. Give the owner in `see` when it is in this repo.

```ts
// Flag: the 14 days is the billing service's decision. The day it changes,
// this client starts rejecting valid invoices.
invoice.due_at - invoice.issued_at !== 14 * 86400
```

Do not flag a constant that this module itself owns.

### Tests

These apply to any non-blank line in test files.

**`test_unneeded`**: a test or case that can be deleted with no loss. Its input
cannot occur, or it tests the language, a library or a mock rather than our
code, or it asserts what another test already asserts (give that test in
`see`), or it reaches a check that an earlier check always gets to first. A
test that passes with or without the PR is unneeded when the function that
decides that behaviour already has a test of it. Mark the whole test or case.

```python
# Flag: test_checkout_returns_the_total already runs the same basket and
# asserts the same total.
def test_total_of_the_sample_basket():
    assert price_basket(SAMPLE_BASKET).total == SAMPLE_TOTAL

# Flag: it only checks that the mock returns what it was told to return.
def test_store_returns_user():
    store.get.return_value = user
    assert store.get("u1") == user
```

```python
# Flag only the last assertion: `mailer.sender` is set from DEFAULT_SENDER
# when the mailer is built, so this compares the constant with itself. The
# rest of the test stays.
def test_welcome_mail_is_sent():
    mailer = build_mailer()
    mailer.send_welcome(user)
    assert mailer.outbox[0].to == user.email
    assert mailer.sender == DEFAULT_SENDER
```

```python
# The PR lets an order be fetched by its public slug as well as its id.
# Keep: the slug resolves, and a stranger's slug is refused.
# Flag: the slug variants of the refund, export and archive tests. Those
# behaviours run after the order is found and the id tests already assert them.

# Flag the last assertion: both orders come from a fake gateway that always
# answers "ch_1", so the two ids are equal whether or not the retry reused
# the first charge.
first = await pay(order, gateway=FakeGateway(charge_id="ch_1"))
again = await pay(order, gateway=FakeGateway(charge_id="ch_1"))
assert again.charge_id == first.charge_id

# Flag the 409 assertion: the test is named for the duplicate-name refusal,
# but the order is already archived, and archived orders answer 409 to any
# rename.
async def test_duplicate_name_is_refused():
    order = await seed(status="archived", name="A")
    assert (await api.patch(f"/orders/{order.id}", json={"name": "A"})).status_code == 409
```

```python
# The PR changes how a late fee is rounded and adds three tests.

# Keep: it fails on the old rounding.
def test_late_fee_rounds_half_to_even(): ...

# Flag: it passes with or without the PR. The refusal is decided in
# load_account(), and test_closed_account_is_refused in the accounts tests
# already sends it a closed account. Going through the fee route adds nothing
# the PR touched.
def test_late_fee_for_a_closed_account_is_refused(): ...

# Keep: it also passes without the PR, but nothing tested the fee cap before.
def test_late_fee_is_capped_at_the_invoice_total(): ...
```

```python
# Flag: the upload middleware refuses any body over the limit before the
# handler runs, and has its own test. This test swaps the middleware out to
# reach a second size check inside the handler, which no request can get to.
def test_handler_refuses_an_oversized_upload(monkeypatch):
    monkeypatch.setattr(app, "size_limit", passthrough)
    assert client.post("/upload", data=BIG).status_code == 413

# Don't flag: nothing writes an order with an unknown status today, but
# refund() is the only place that would refuse one.
def test_refund_refuses_an_order_with_an_unknown_status():
    order = seed_raw(status="???")
    assert refund(order).status_code == 409
```

Do not flag a test for an edge case that can occur, even an unlikely one.

```python
# Don't flag: delete_order() calls the mailer when it succeeds, so asserting
# that a stranger's refused request sent no mail is a real guard.
async def test_stranger_cannot_delete(mailer):
    assert (await api.delete(f"/orders/{oid}")).status_code == 404
    assert mailer.sent == []
```

**`test_mergeable`**: tests that differ only in inputs and expected values and
would read better as one table-driven or parametrized test. Mark only the
lines that would disappear in the merge: the repeated setup and assertions of
the second and later copies. Do not mark the first copy.

```python
# Flag the second and third blocks: same shape, only the response and the
# exception differ.
with pytest.raises(NotAllowed):
    await client.fetch_report(account, "2026-Q1")     # after a 403
with pytest.raises(Unavailable):
    await client.fetch_report(account, "2026-Q1")     # after a 503
with pytest.raises(Unavailable, match="malformed"):
    await client.fetch_report(account, "2026-Q1")     # after a bad body
```

Do not flag tests that share setup but assert different behaviour.

### Doc files

These apply to `P` lines only: READMEs, guides, plans and other prose files.
Flag whole sentences, list items or table rows. In an HTML doc, judge the text
a reader sees and leave markup and styling alone.

**`docfile_drift_prone`**: the text pins itself to a detail of the code that
will move, with nothing keeping the two in step. Look hardest for references
to specific line numbers. Also: line or file counts, a pasted copy of a
signature, a default value or a config block, an exact version, a list of
every caller or every route, and "currently" or "as of now" statements about
code.

```markdown
Flag: the line numbers are wrong after the next edit to that file.
The retry logic lives in `client.py` lines 120 to 148.

Flag: a count and a copied default.
There are 14 tools, and the timeout defaults to 30 seconds.

Don't flag: it points at a name, which a rename would break loudly in search.
The retry logic lives in `client.py`, in `_with_retries`.
```

Describing what the product does, or what a user will see, is the job of a
doc file and is not drift on its own: flag only the pins named above. A row in
a change log, a release note or a report records what was true when it was
written; treat it like a dated record. A doc line is kept in step only when a
test or a generator reads its text and compares it with the code. A dated plan or decision record may describe what
it decided and what was true on its date, but a reference to specific line
numbers is flagged even there, because people follow it long after the lines
have moved.

**`docfile_repeats`**: the text says again what another doc file, or a
docstring in the code, already says. Give the other place in `see`. A short
pointer to the other place is not a repeat: one clause of fact plus where to
read more.

Work out which side owns the statement before you flag. When a comment or
another doc cites this file as the source of a rule or a decision, this file
is the owner and the other is the copy; the owner is never the repeat. A
troubleshooting entry that gives the reason for a symptom is not a repeat of
the code comment that explains the same check.

```markdown
Don't flag: one clause and a pointer.
Exports are capped per account; see "Limits" in the operations guide.

Don't flag: the decision record is where the rule lives, and the code
comment that says "see decision 12" is the copy.
Decision 12: refunds over 500 need a second approver.

Flag: a second full description of the export flow that the operations
guide already gives step by step.
```

## Output

Write `OUT` as JSON, exactly this shape:

```json
{
  "purpose": "What the PR is for, what it replaces, what the removed lines used to do.",
  "worksheet": [
    {
      "pass": "code",
      "item": "billing/invoice.py:88 _format_total",
      "searched": "git grep 'quantize(' ; git grep 'currency_symbol' ; read shared/money.py:40",
      "found": "shared/money.py format_amount does the same rounding and symbol placement",
      "verdict": "code_duplicate"
    },
    {
      "pass": "tests",
      "item": "test_refund_does_not_email",
      "searched": "read refund() in billing/service.py; git grep Mailer -- billing/",
      "found": "refund() never constructs the Mailer the test patches",
      "verdict": "test_unneeded"
    },
    {
      "pass": "comments",
      "item": "orders/store.py:44 'callers must lock the row first'",
      "searched": "git grep 'store.reserve('",
      "found": "three callers, one of which does not lock",
      "verdict": "doc_drift_prone"
    },
    {
      "pass": "code",
      "item": "config.py:12 EXPORT_ENABLED flag",
      "searched": "git grep EXPORT_ENABLED",
      "found": "defined once, read in server.py only",
      "verdict": "none"
    }
  ],
  "summary": "One or two plain sentences on where this PR's weight is, or that it has none.",
  "findings": [
    {
      "category": "doc_drift_prone",
      "file": "path/as/in/ADDED",
      "start": 82,
      "end": 85,
      "reason": "One sentence the author would accept.",
      "see": "path/to/other.go:120"
    }
  ],
  "outside": [
    {
      "file": "path/as/in/ADDED",
      "start": 40,
      "end": 71,
      "note": "One or two sentences on what could be much smaller, and why."
    }
  ]
}
```

- `worksheet` has one entry for every unit, test and comment sentence you
  listed in the passes, in order. `pass` is one of `code`, `tests`,
  `comments`, `docs`. `verdict` is a category name or `none`. Every entry
  whose verdict is a category has a matching entry in `findings`.
- `start` and `end` are line numbers in the new file, as shown in `ADDED`, inclusive.
- Keep ranges tight. A range may span lines that were not added. Only added
  lines of the right kind inside it are counted.
- `see` is required for `doc_repeats_doc`, `code_duplicate` and
  `docfile_repeats`, for `code_copied_rule` when the owner is in this repo,
  and for `test_unneeded` when the reason is another test. Omit it otherwise.
- Write every `reason` and every `outside` note in very simple English: short
  sentences, everyday words. The reader may never have seen this code. Say
  what the lines do and why they are not needed, before any function name:
  "This test sends the same request as the one above it and checks the same
  answer", not "Duplicates coverage of the handler's happy path". Say what an
  internal term means the first time you use it.
- No findings is a valid answer: `"findings": []`. An empty `worksheet` is not.
- `outside` may be `[]`.

After writing the file, reply with one line per category that has findings,
giving the number of findings, and nothing else.
