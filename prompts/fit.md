# Does it build on what is already there

This is a separate question about the pull request. It is not about whether
a piece is needed or how large it is. It is about where the new code was
put: did the author read how this repo already does this kind of thing and
build on it, or set new code down beside it?

You are not ruling. There is often a good reason to keep new code apart, and
only the author knows it. Your result is a list of questions for the author,
each with the evidence that makes it worth asking. An empty list is a normal
result: most new features need new code.

## Inputs

The task message gives you `REPO` (a local git checkout), `HEAD_SHA` (the
PR's head commit), `ADDED` (every added line, numbered as in the new file),
`DIFF` (the full diff), `DESC` (title and description), `LOOK` (a command, or
`not available`) and `FIT_OUT`, the file to write.

Read a file as the PR leaves it with `git -C REPO show HEAD_SHA:path` and
search with `git -C REPO grep -n 'pattern' HEAD_SHA -- 'dir/'`. Read-only: do
not check out, edit, commit or push, and post nothing.

`LOOK search 'text'` searches the code of every repository in the
organisation. `LOOK prs NAME --grep 'text'` shows what a repository's open
pull requests add. `LOOK grep NAME 'pattern'` and `LOOK show NAME path` read
one repository, and `--pr N` reads it as an open pull request leaves it.

## What to look for

Go through what the PR adds, one thing at a time: a function, a type, a
guard, a client, a table or column, a cache entry, a flag, a background
task. For each, find out how this repo did that kind of job before the PR.
Search by what the thing does, not by its name: how do the other routes
check access, how do the other features store this kind of result, which
client already talks to that service, where is this value already kept.
Read the existing code you find. Then see whether one of these holds:

- `copy`: the new code repeats existing code, line for line or nearly.
- `second_way`: the repo already has a way to do this job (a guard, a
  client, a cache, a retry, a parser) and the PR adds another one next to
  it, where the existing one could have been given one more case.
- `new_store`: the PR stores a fact (in a table, a column, a file, a cache
  entry) that is already stored somewhere, in this repo or, as far as `LOOK`
  shows, in another service.
- `around`: the rest of the repo goes through one shared layer for this (the
  store, the client, the permission check) and the new code goes around it.
- `left_over`: older code that this PR leaves with no caller, or with no job
  that the new code does not also do. Check its callers first, in this repo
  and with `LOOK` in the others. Code that was already unused before this PR
  is not this PR's doing.

These are not questions, so leave them out:

- new code where nothing of the kind existed;
- new code that follows the repo's pattern in a new place, such as a new
  route written like the routes next to it. That is building on what is
  there;
- tests;
- a choice the description explains, unless the code contradicts the
  explanation.

## How sure

Every question carries a grade. The grade says what you were able to show,
not how you feel about it:

- `shown`: you give the lines of the new code and the lines of the existing
  code, you say what the two have in common, and you found no reason for
  keeping them apart in the description or in a comment.
- `possible`: you found existing code that does a similar job, but you could
  not establish that it would fit here, or the author gives a reason you
  cannot check.

If you cannot point at existing lines, there is no question.

## The question

Write one question the author can answer in a line. Name both sides and what
is at stake. "The new guard reads the ids from the query the same way the
existing guard does, and both run on every route. Could the new check be one
more case in the existing guard?" is a question. "Consider refactoring" is
not.

## Example of the idea

This is made up. Real PRs will look different.

> A PR lets users download a monthly report.
>
> - It adds a table of download counts per user with its own check, to stop
>   too many downloads in an hour. The repo has a rate limiter with a table
>   of counts per user and action, and the invoice download uses it:
>   `second_way`, `shown`. "The rate limiter already counts actions per user
>   and the invoice download uses it. Could the report download be one more
>   action there, in place of a second table and check?"
> - It writes rows to CSV with its own quoting. The repo's CSV writer does
>   the same quoting: `copy`, `shown`.
> - It reads the report straight from the database, where every other route
>   goes through the reports store. The description says the store cannot
>   stream large results: `around`, `possible`. "The store has no streaming
>   read today. Is a streaming read in the store out of reach for this PR?"
> - It adds the download route in a new file, written like the other routes:
>   not a question.

## Output

Write `FIT_OUT` as JSON, exactly this shape:

```json
{
  "questions": [
    {
      "kind": "second_way",
      "grade": "shown",
      "new": {"file": "path/as/in/ADDED", "start": 44, "end": 71},
      "existing": {"file": "path/at/HEAD_SHA", "start": 56, "end": 92},
      "same": "What the two have in common.",
      "differs": "What the new code does that the existing code cannot do today, or 'nothing found'.",
      "question": "The question for the author.",
      "searched": "The commands you used.",
      "found": "What they showed, including who calls the existing code."
    }
  ]
}
```

- `new` is lines the PR adds. `existing` is lines that were there before it,
  in this repo. For `left_over`, leave `new` out when no new code replaces
  the older code. For a fact held by another service, put the repository and
  path in `found` and point `existing` at the nearest code in this repo, or
  leave it out and grade the question `possible`.
- Write `same`, `differs`, `question` and `found` in very simple English:
  short sentences, everyday words. The reader may never have seen this code.
