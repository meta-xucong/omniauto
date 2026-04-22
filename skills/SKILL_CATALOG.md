# Project Skill Catalog

This file lists project-local skills that have been explicitly approved by the user.

## Current State

The repository currently has two user-approved formal project-local skills.

## task_skills/

- `minesweeper_autoplay`
  - runtime bundle: `.agents/skills/minesweeper-autoplay/`
  - human entry: `skills/task_skills/minesweeper_autoplay/README.md`
  - scope: runs, regression-tests, diagnoses, and iterates the Windows Minesweeper autoplay workflow

## capability_skills/

- `guarded_knowledge_closeout`
  - runtime bundle: `.agents/skills/guarded-knowledge-closeout/`
  - human entry: `skills/capability_skills/guarded_knowledge_closeout/README.md`
  - scope: governs how automatic knowledge closeout, manual closeout, and strict AI review candidates must behave

Other task families such as marketplace research and WPS automation are still intentionally **not** being promoted into formal project-local skills in this refactor.

## Future Sections

- `task_skills/`
  - user-approved task-family skills
- `capability_skills/`
  - user-approved reusable capability skills
