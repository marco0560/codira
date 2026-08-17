# How to use Codira with my coding agent

The best coding-agent conversations do not begin with “please search the whole
repository.” They begin with a small set of real files, real symbols, and a
clear task. Codira supplies that starting point locally, so an agent can spend
its attention on reasoning about the change instead of rediscovering the
project.

There are two good ways to connect it:

- **Local MCP** gives a compatible local agent live, read-only Codira tools.
  It is ideal for ongoing work in Codex or Claude Code.
- **`ctx --prompt`** produces a compact, reviewable handoff that you paste into
  any web-based agent conversation. It is ideal when a browser chat cannot
  reach your machine.

Both modes are grounded in the same repository-local index.

## Before the agent starts

Install Codira and build the target repository's index:

```bash
cd /path/to/your/repository
codira index
```

Then give the agent a question with a boundary and a goal. Compare:

```text
Bad: find the login code
Better: trace failed-login recording from the HTTP handler to persistence,
including its regression tests; do not edit anything yet.
```

An agent should still read the returned source and tests. Codira narrows the
search space; it does not make guesses or replace review.

## Codex: a live repository guide

Codex can use Codira through its local stdio MCP configuration. From the
repository you want Codex to inspect, generate the entry:

```bash
codira-mcp-config codex --root "$PWD"
```

Copy the output into either the user configuration at `~/.codex/config.toml`
or the project-scoped `.codex/config.toml` for a trusted project. It has this
shape, with an absolute repository path:

```toml
[mcp_servers.codira]
command = "codira-mcp"
args = ["--root", "/absolute/path/to/repository"]
```

Restart Codex and ask it to use Codira deliberately:

```text
Use the Codira tools first. Map the request-validation path, identify the
production symbols and regression tests, and read the primary files before
proposing an edit.
```

Codira's MCP server is local and read-only. It is fixed to one repository when
it starts, cannot be retargeted by a later request, and has no shell-execution
tool. After tracked edits, run `codira index` again before relying on the next
MCP retrieval result.

Codex can also consume structured command output when you prefer an explicit
handoff over live tools:

```bash
codira ctx "trace request validation and its tests" --json
codira symlist --prefix src --json
```

For current configuration choices, see the [official OpenAI MCP
documentation](https://developers.openai.com/codex/mcp/).

## Claude Code: the same local knowledge, project-scoped

Claude Code uses the same standard stdio MCP shape. Create or extend
`.mcp.json` at the target repository root, preserving unrelated entries:

```json
{
  "mcpServers": {
    "codira": {
      "command": "codira-mcp",
      "args": ["--root", "/absolute/path/to/repository"]
    }
  }
}
```

Use an absolute path instead of relying on the client’s working directory.
Restart Claude Code or reload its MCP configuration, approve the server when
it asks, then set the expectation for its first move:

```text
Use Codira before broad searching. Give me the 5 most relevant symbols and
files for this defect, explain their roles, and wait for my confirmation before
editing.
```

The server tools are intentionally bounded: a question returns enough context
to orient the agent without silently dumping the whole repository into the
conversation. For current project trust and MCP controls, consult the [Claude
Code MCP documentation](https://code.claude.com/docs/en/mcp).

## The web: carry a precise snapshot into a chat

A browser chat cannot access a local `codira-mcp` process merely because it is
running on your computer. That is where `--prompt` shines:

```bash
codira ctx "trace request validation and identify the regression tests" --prompt
```

Paste the complete output into the conversation, followed by the instruction
you want the agent to perform. The rendered handoff contains the task, primary
and supporting targets, and disciplined rules for working only from the
identified repository evidence.

Although the CLI calls this output “Codex-ready,” it is normal text. It works
well with Claude on the web, ChatGPT, or another coding assistant. Think of it
as a signed-off brief: you can read it first, remove anything unnecessary, and
then decide exactly what to share. Generate a new brief after a material code
change or when you switch to a different task.

If the browser agent understands JSON better than prose, use the richer
machine-readable form instead:

```bash
codira ctx "trace request validation and identify the regression tests" --json
codira calls validate_request --json
```

`--json` is an output mode, not an unbounded export. It keeps the command's
normal retrieval and limits while making the result predictable for a program
or agent to consume.

## Give an agent more than one kind of clue

Different Codira commands create different kinds of useful context. Mix them
to match the task rather than repeatedly asking the agent to search.

| Question | Command | What the agent gets |
| --- | --- | --- |
| What are the project’s landmarks? | `codira symlist --limit 30` | Indexed symbols and connectivity counts |
| Where is this exact behavior defined? | `codira sym validate_request` | Exact matching symbol records |
| What happens next? | `codira calls validate_request --tree` | A bounded static call traversal |
| Who relies on it? | `codira refs validate_request --incoming --tree` | Incoming callable-object references |
| Which files should I inspect first? | `codira ctx "<task>"` | Task-focused source and documentation context |

For a visual discussion, export a bounded traversal as Graphviz DOT and attach
the rendered image or share the DOT file with the agent:

```bash
codira calls validate_request --tree --dot > request-validation.dot
dot -Tsvg request-validation.dot -o request-validation.svg
```

`--dot` requires `--tree` and cannot be combined with `--json`: one produces a
graph description, the other a structured command result.

## Keep a long-running agent session honest

An agent’s context can outlive the state of the repository. Re-index after a
completed edit batch before asking Codira for the next answer:

```bash
codira index
```

For a repository under steady development, enable Codira's optional automatic
indexing daemon in `.codira/config.toml`:

```toml
[daemon]
enabled = true
debounce_ms = 250
```

Then run it in the foreground or install the repository-scoped user service:

```bash
codira daemon run
# or
codira daemon install
codira daemon start
```

The daemon queues normal incremental indexes after relevant, non-ignored file
changes. It is separate from the optional query daemon, which only keeps
eligible read queries warm. See [Configuration](configuration.md) for the
service lifecycle and [Local MCP quickstart](mcp.md) for fixed-root and named
workspace startup.

## A collaboration rhythm that feels good

1. You name the outcome and the constraints.
2. Codira provides the short list of evidence.
3. The agent reads that evidence and proposes a small plan.
4. You approve the direction.
5. The agent edits, tests, and the index is refreshed for the next question.

That rhythm keeps the agent fast without asking it to be magical. It also
leaves you able to explain why a particular file, symbol, or dependency was in
scope.
