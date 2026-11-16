# Does the PR account for itself

You are reading one pull request to find the decisions its author made, and
to check whether the author accounted for each one: said it, gave a reason,
and gave a reason that holds against what can be read.

You are not judging whether a decision is right. A decision the author made
on purpose and explained is fine here, whatever you think of it. What this
review looks for is the decision nobody explained, and the explanation that
falls apart when someone looks. It also looks for the explanation that is
true and rests on something that is not settled yet.

A script counts the lines inside the ranges you give. Never report totals.

## Inputs

The task message gives you `REPO` (a local git checkout), `HEAD_SHA` (the
PR's head commit), `ADDED` (every added line: its number in the new file, a
kind, `C` code, `D` comment, `P` doc prose, and the text), `DIFF` (the full
diff), `DESC` (the PR's title and description as the author wrote them),
`LOOK` (a command, or `not available`) and `OUT`, the file to write.

Read a file as the PR leaves it with `git -C REPO show HEAD_SHA:path` and
search with `git -C REPO grep -n 'pattern' HEAD_SHA -- 'dir/'`. Read-only:
do not check out, edit, commit or push, and post nothing. The only file you
write is `OUT`.

`LOOK` reads what is not on this machine: the other repositories of the same
organisation and open pull requests.

- `LOOK search 'text'` searches the code of every repository, on default
  branches. Add `--repo NAME` for one.
- `LOOK prs NAME` lists a repository's open pull requests, and
  `LOOK prs NAME --grep 'text'` shows the lines they add that contain the text.
- `LOOK grep NAME 'pattern' [path]` searches one repository. Add `--pr N` to
  search it as an open pull request leaves it.
- `LOOK show NAME path` prints a file and `LOOK show NAME` lists the top
  directory. `--pr N` works here too, and `--lines 40-90` picks a part.

## Pass 1: the decisions, from the code alone

Do not open `DESC` yet. Read `DIFF` from top to bottom and list every
decision: a place where the author chose something, and a careful reader
would stop and ask "why this?". There are six kinds.

- `mechanism`: a new moving part. A cache, a queue, a retry, a background
  task, a lock, a second client or connection, a switch that turns
  something on or off.
- `store`: a new place where something is kept. A table, a column, a file,
  a cache entry, an index.
- `outside`: something outside this repository that the code needs or
  follows. Another service, a route or field of another service, a document
  or specification the code says it follows, another pull request, a
  library that is new to this repository.
- `around`: the code does a job in a different way from how this repository
  already does that job. Find how the repository does it before you list
  this: search for the other places that do the same kind of thing.
- `number`: a chosen value that changes behaviour. A time limit, an expiry,
  a size, a count, a threshold.
- `exposed`: something other programs or people can now see or call. A
  route, a field in a reply, an event, a permission.

These are not decisions, so leave them out:

- the ordinary code that does the job the way its neighbours do: a handler
  written like the handlers next to it, error handling like theirs, a value
  copied from the same setting the neighbours use;
- tests, names, formatting, comments;
- anything where nobody would ask "why this?".

A small pull request may have no decisions at all. That is a normal result.

For each decision write `ranges`: the added lines that exist because of this
decision, with the tests that exist only for it. A line belongs to one
decision. When two decisions share a line, give it to the more specific one.

## Pass 2: what the author says

Now read `DESC`, and the comments in the added code (the `D` lines of
`ADDED`).

First write `purpose`: one sentence, in your own words, on what the pull
request is for. Take it from the title and the opening of `DESC`. Then find
the decisions that are the purpose itself: the thing the pull request exists
to deliver. Give them the state `purpose` and stop there for them. They need
no reason and get no question. Be strict about this. The purpose is one
thing, sometimes two. The way the author chose to deliver it is not the
purpose: "members can read their company's reports" is a purpose, and the
cache, the new table and the second client that make it work are decisions.

For each other decision, find where the author talks about it.

- Quote the author's words in `says`, shortened if long, and write where
  they are in `where`: `description`, or `path:line` for a comment.
- A reason says what would go wrong, or what could not be done, without this
  decision, in this system. "Adds a cache", "for safety", "to be robust",
  "best practice" and "for consistency" name the decision or praise it. They
  are not reasons.
- If the author does not mention the decision anywhere, the state is
  `not_mentioned`. If the author mentions it and gives no reason, the state
  is `no_reason`. Otherwise go to pass 3.

## Pass 3: check the reason

A reason always points at something. Find what it points at, write it in
`points_at`, and go and look. Use `REPO` and `LOOK`.

- It points at other code, a service, a route or a field ("the reports
  service already refuses this", "the same as the invoice download"). Find
  it. Does it exist? Is it merged, in an open pull request, or missing? Does
  it do what the author says it does?
- It points at a document, a specification or a ticket. Find it. Say where
  it lives and what that place is for: read that repository's own
  description and README. Say whether it is merged or still a proposal.
  Does it say what the author says it says?
- It points at a number or a measurement ("reports can reach 2 GB"). Find
  where that number is written. Is it there? Under what conditions was it
  measured?
- It points at a change that is still to come ("a later change will remove
  this"). Look for it: an open pull request, a ticket, a note in the code of
  the place it would be made.
- It points at an agreement between people ("the support team asked for
  this", "agreed in planning"). You cannot check that from here, and you
  must not doubt it. The state is `cannot_check`.

Then set the state:

- `holds`: what the reason points at exists, and says or does what the
  author says. How settled it is does not change this state. That is a
  separate fact, written in `standing`.
- `does_not_hold`: it is missing, or it is not what the author says it is,
  or it does not say or do what the author says. Write exactly what you
  found in its place.
- `cannot_check`: an agreement between people, or something you have no way
  to read.

## How settled is it

A true reason can rest on something that may still change. So for every
decision that went through pass 3, and for every `outside` decision whatever
its state, write two more facts about the thing the code or the reason rests
on.

`place`: one sentence on where the thing lives and what that place is for,
in that place's own words. Read the repository's description and its README.
A reader must be able to tell a running service from a library, a document,
a proposal or an experiment.

`standing`: one word.

- `merged`: it is on the default branch of a repository that is used in
  production.
- `open`: it is in an open pull request, not on a default branch.
- `draft`: it is in a draft pull request.
- `prototype`: it is on a default branch, in a repository or folder that
  calls itself a prototype, an experiment, a proposal or a sandbox.
- `missing`: you looked and it is not there.
- `none`: the reason points at nothing that can be read, or the decision
  never reached pass 3.

When the thing is in several of these at once, write the least settled one:
an open pull request stacked on a draft is `draft`, and an open pull request
in a prototype repository is `prototype`. When a reason points at several
things, write the least settled of them and name each in `place`.

Every decision whose `standing` is `open`, `draft`, `prototype` or `missing`
gets a question, also when its state is `holds`. The question says what the
thing is and how settled it is, and asks what happens to this code if the
thing changes or never lands.

## The worksheet

Fill `searched` and `found` for every decision, also when you found nothing:
"searched X, found nothing" is a result. Do not set a state you did not look
for.

For every decision whose state is `not_mentioned`, `no_reason` or
`does_not_hold`, and for every decision whose `standing` is not `merged` or
`none`, write `question`: one question the author can answer in a
line, naming what you found. "The description says the invoice download
limits size the same way, but it has no limit. Where does 50 MB come from?"
is a question. "Please justify this" is not.

## Example of the idea

This is made up. Real pull requests will look different; follow the passes,
not the likeness.

> A PR lets users download a monthly report as a CSV file.
>
> - The download route and the handler that builds the file: `purpose`.
> - A nightly task that deletes downloads older than 90 days (`mechanism`).
>   The description says "the finance job reads this folder every night, so
>   old files slow it down". The finance job exists and lists the whole
>   folder on each run, on its default branch: `holds`, standing `merged`.
> - 90 days (`number`). Nobody says why 90: `not_mentioned`. "Invoices are
>   kept for 30 days. Why are downloads kept for 90?"
> - A size limit of 50 MB (`number`). A comment says "same limit as the
>   invoice download". The invoice download has no limit: `does_not_hold`.
> - The file is written with a CSV library that is new to this repository
>   (`outside`). The description says "the library is already used by the
>   billing service". It is, but only in an open pull request there, not
>   on its default branch: `holds`, standing `open`. "The billing service
>   does not use this library yet: the change that adds it is still open.
>   What happens here if that change is dropped?"
> - The route reads the database directly, where every other route goes
>   through the reports store (`around`). The description says "direct
>   access" and nothing more: `no_reason`.
> - A new field `row_count` in the reply (`exposed`). The description says
>   "the support team asked for it": `cannot_check`.
> - The error handling in the handler, written like the invoice download:
>   not a decision.

## Output

Write `OUT` as JSON, exactly this shape:

```json
{
  "purpose": "One sentence on what the pull request is for.",
  "decisions": [
    {
      "name": "Short plain name of the decision",
      "kind": "number",
      "ranges": [{"file": "path/as/in/ADDED", "start": 10, "end": 42}],
      "says": "The author's own words about it, or an empty string.",
      "where": "description",
      "state": "does_not_hold",
      "points_at": "What the author's reason points at, or an empty string.",
      "searched": "The commands and files you used.",
      "found": "What they showed.",
      "place": "Where the thing lives and what that place is for, or an empty string.",
      "standing": "open",
      "question": "The question for the author, or an empty string."
    }
  ]
}
```

- `kind` is `mechanism`, `store`, `outside`, `around`, `number` or `exposed`.
- `state` is `purpose`, `not_mentioned`, `no_reason`, `holds`,
  `does_not_hold` or `cannot_check`.
- `standing` is `merged`, `open`, `draft`, `prototype`, `missing` or `none`.
- `ranges` uses added lines only, as numbered in `ADDED`.
- Write `name`, `found` and `question` in very simple English: short
  sentences, everyday words. The reader may never have seen this code. Name
  a decision by what it does, not by its mechanism, and say what an
  internal term means the first time you use it.
