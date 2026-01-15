# Todo Loop

Execute all pending todos by spawning Task agents, using Ralph Wiggum loop pattern.

## What This Skill Does

Combines the Ralph Wiggum iteration technique with Task agent spawning to autonomously work through all todos. It:

1. **Syncs** internal TodoWrite state to `.claude/shared-todos.md`
2. **Spawns** a Task agent for the first pending todo
3. **Loops** until all todos are marked complete

## Process

### STEP 1 - ALWAYS SYNC INTERNAL TODOS TO SHARED FILE

1. Read `c:\Users\Admin\Documents\Coinswarm-1\.claude\shared-todos.md`
2. Check your internal TodoWrite state for ANY 'pending' or 'in_progress' items
3. For EACH internal todo that is NOT already in shared-todos.md:
   - Append it as `- [ ] [task description]` under `## Active Todos`
4. This sync happens EVERY iteration to catch new todos added during work

### STEP 2 - FIND NEXT TASK

1. Re-read `c:\Users\Admin\Documents\Coinswarm-1\.claude\shared-todos.md`
2. Find the FIRST line matching `- [ ]` (uncompleted task)
3. If NO uncompleted tasks exist, output `<promise>ALL TASKS COMPLETED</promise>` and stop

### STEP 3 - SPAWN WORKER

Use the Task tool with `subagent_type='general-purpose'` with this prompt template:

```
YOUR TASK: [paste the task text here]

WHEN COMPLETE: Edit c:\Users\Admin\Documents\Coinswarm-1\.claude\shared-todos.md
Change your task line from "- [ ]" to "- [x]"

Work autonomously. Do not ask questions. Complete the task fully.
```

Wait for agent to finish.

### STEP 4 - LOOP

- Do NOT output the completion promise
- The loop will restart and repeat from STEP 1

## Rules

- Sync EVERY iteration (new todos may appear from spawned agents)
- Only spawn ONE agent per iteration to maintain order
- Use absolute file paths always
- Only output `<promise>ALL TASKS COMPLETED</promise>` when zero `- [ ]` lines remain

## When to Use

- You have a list of tasks to work through autonomously
- You want parallel-style execution with Task agents
- You need to leave Claude running unattended on multiple tasks

## Shared Todo File Format

The file `.claude/shared-todos.md` uses this format:

```markdown
## Active Todos

- [ ] First pending task
- [ ] Second pending task
- [x] Already completed task

## Completed

| Task | Session | Completed |
|------|---------|-----------|
| Example task | session-123 | 2025-01-02 |
```

## Starting the Loop

After this skill executes, start the Ralph loop with:

```
/ralph-wiggum:ralph-loop "Execute the todo-loop skill instructions from .claude/skills/todo-loop/SKILL.md" --completion-promise "ALL TASKS COMPLETED"
```

Or manually follow the steps above in an iterative fashion.
