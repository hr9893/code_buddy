# code_buddy
A coding assistant agent to help you complete your coding task.

## Run the terminal console

Start the interactive PowerShell-friendly console from the repository root:

```powershell
uv run python main.py
```

It uses normal terminal scrollback rather than a full-screen interface. Log output
remains plain and selectable while the command prompt stays available. Enter
`help` to see commands such as `start`, `stop`, `status`, `history`, `logs`, and
`quit`. Use `approve` or `reject` if a guarded action requests confirmation.

## Chat model configuration

The orchestrator and all subagents use the same DeepSeek model. Set the API key
in `.env`:

```dotenv
DEEPSEEK_API_KEY=your-deepseek-api-key
```

The model is `deepseek-chat`. Missing keys and provider errors are reported
directly; the app does not switch to a different provider automatically.

## Issue handling

The orchestrator makes one structured routing call, selects one specialist, and
invokes it directly. Model-call budgets scale with the routed effort:

| Effort | Repo explorer | Coder | PR agent |
| --- | ---: | ---: | ---: |
| Simple | 3 | 8 | 4 |
| Moderate | 8 | 16 | 8 |
| Complex | 12 | 24 | 12 |

Each specialist has a hard budget and recursion limit. If it reaches either
limit before completing, the issue is recorded as failed rather than running
indefinitely; any remote branch or edits already made remain available for
review. Code-change tasks use GitHub API tools end to end: the coder creates a
remote branch, edits files on that active branch, and opens the pull request.
Local shell git commands do not select the GitHub API branch and are not
available to the coder. File updates send the complete final contents and are
limited to one successful update per path per issue.
