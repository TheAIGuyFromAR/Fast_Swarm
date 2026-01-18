---
active: true
iteration: 1
max_iterations: 0
completion_promise: "ALL TASKS COMPLETED"
started_at: "2026-01-03T04:50:01Z"
---

TODO EXECUTOR WITH SYNC:

STEP 1 - ALWAYS SYNC INTERNAL TODOS TO SHARED FILE:
- Read c:\Users\Admin\Documents\Coinswarm-1\.claude\shared-todos.md
- Check your internal TodoWrite state for ANY 'pending' or 'in_progress' items
- For EACH internal todo that is NOT already in shared-todos.md:
  - Append it as '- [ ] [task description]' under '## Active Todos'
- This sync happens EVERY iteration to catch new todos added during work

STEP 2 - FIND NEXT TASK:
- Re-read c:\Users\Admin\Documents\Coinswarm-1\.claude\shared-todos.md
- Find the FIRST line matching '- [ ]' (uncompleted task)
- If NO uncompleted tasks exist, output <promise>ALL TASKS COMPLETED</promise> and stop

STEP 3 - SPAWN WORKER:
- Use the Task tool with subagent_type='general-purpose'
- Prompt for the agent:
  'YOUR TASK: [paste the task text here]
   
   WHEN COMPLETE: Edit c:\Users\Admin\Documents\Coinswarm-1\.claude\shared-todos.md
   Change your task line from "- [ ]" to "- [x]"
   
   Work autonomously. Do not ask questions. Complete the task fully.'
- Wait for agent to finish

STEP 4 - LOOP:
- Do NOT output the completion promise
- The loop will restart and repeat from STEP 1

RULES:
- Sync EVERY iteration (new todos may appear from spawned agents)
- Only spawn ONE agent per iteration
- Use absolute file paths always
- Only output <promise>ALL TASKS COMPLETED</promise> when zero '- [ ]' lines remain
