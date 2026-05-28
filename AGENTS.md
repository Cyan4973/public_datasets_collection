# AGENTS.md

Operate autonomously inside this repository.

Do not ask for per-edit approval for normal file creation, modification,
deletion, renaming, or formatting within this repository.

Require explicit user approval only when:
- downloading or fetching external dataset resources
- editing files outside this repository
- running destructive git or history operations
- deleting non-generated user data under `.data/`
- making changes the user explicitly asked to review before applying

When working autonomously:
- briefly state what you are changing and keep moving
- never download datasets yourself; write download scripts for the user to run
- process dataset contents only after the user confirms local files are present
